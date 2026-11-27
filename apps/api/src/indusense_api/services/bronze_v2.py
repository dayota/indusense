"""Orchestration du parcours v2 ; le catalogue et les données ont leurs transactions propres."""
import csv
import hashlib
import io
import json
import os
import tempfile
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from uuid import UUID, uuid4

import sqlalchemy as sa
import yaml
from fastapi import HTTPException

from indusense_ingestion.bronze_contracts import COMPATIBILITY, config_hash, parse_contracts, validate_or_raise
from indusense_ingestion.bronze_domain import SourceSpec
from indusense_ingestion.bronze_sources import FilesystemSourceInspector, source_spec
from indusense_ingestion import bronze_engine as loader
from indusense_ingestion.contracts import UniqueKeyLoader

from .. import catalog as db
from . import bronze_storage as legacy
from .preparation import editable, exact_files, files_for, materialize, public_file
from .workflow import locked_version, record
from . import model_database


def contract_schema(root):
    schema = json.loads((root / 'config/schema/bronze.v2.schema.json').read_text(encoding='utf-8'))
    types = schema['properties']['columns']['items']['properties']['type']['enum']
    if not isinstance(types, list) or not types or any(not isinstance(value, str) for value in types):
        raise ValueError("Le schéma Bronze doit définir les types de colonnes autorisés")
    timezone = schema['properties']['timezone']
    native_types = schema['$defs']['postgresql_native_type']['enum']
    # Les séries sont des raccourcis DDL ; PostgreSQL n'autorise pas SERIAL[].
    serial_types = {'SERIAL', 'SMALLSERIAL', 'BIGSERIAL', 'SERIAL2', 'SERIAL4', 'SERIAL8'}
    postgres_types = sorted(set(native_types) | {name + '[]' for name in native_types if name not in serial_types})
    return {'column_types': types, 'operations': schema['properties']['derived_columns']['items']['properties']['operation']['enum'],
            'timezones': timezone.get('enum', [timezone.get('const', 'UTC')]),
            'silver_types': {kind: sorted(values) for kind, values in COMPATIBILITY.items()},
            'postgres_types': postgres_types, 'schema': schema}


def reference_contracts(root):
    paths = {path.stem: path for path in sorted((root / "config/bronze").glob("*.yml"))}
    groups = {}
    for name, path in paths.items():
        for config in parse_contracts(path.read_text()):
            source = config.get("source", {})
            if source.get("format") == "SQL":
                key = (source.get("path"), source.get("encoding"))
                groups.setdefault(key, set()).add(name)
    bundles = {"bundle:" + ",".join(sorted(names)): sorted(names) for names in groups.values() if len(names) > 1}
    return paths, bundles


def contract_catalog(engine, root, version_id):
    from . import local_contracts
    options = []
    with engine.connect() as connection, tempfile.TemporaryDirectory() as folder:
        for file in files_for(connection, version_id):
            tables = [None]
            if file['format'] == 'sql':
                source = materialize(file, Path(folder) / str(file['id']))
                encoding = parse_contracts(file['loaded_yaml'])[0]['source']['encoding'] if file['loaded_yaml'] else 'utf-8'
                inspector = FilesystemSourceInspector(root, {file['filename']: source['path']})
                tables = list(inspector.sql_tables(SourceSpec(file['filename'], 'SQL', encoding)))
            for table in tables:
                choices = local_contracts.available(connection, version_id, file, root, table)
                for relative, path, contract_version in ([local_contracts.latest(choices)] if choices else []):
                    options.append({'value': 'local' if contract_version is None else path.stem,
                                    'label': path.name, 'path': relative, 'version': contract_version,
                                    'file_id': str(file['id']), 'tables': [table] if table is not None else []})
    return options


def inspect_sql(engine, version_id, file_id, encoding, root):
    with engine.connect() as connection:
        file = connection.execute(sa.select(db.preparation_files).where(db.preparation_files.c.id == file_id,
            db.preparation_files.c.model_version_id == version_id)).mappings().first()
    if file is None: raise HTTPException(404, "Fichier introuvable pour cette version")
    if file['format'] != 'sql': raise ValueError("L'inspection des tables concerne uniquement les fichiers SQL")
    with tempfile.TemporaryDirectory() as folder:
        source = materialize(file, Path(folder))
        spec = SourceSpec(file['filename'], 'SQL', encoding)
        inspector = FilesystemSourceInspector(root, {file['filename']: source['path']})
        tables = inspector.sql_tables(spec)
    return {'file_id': str(file_id), 'sha256': file['sha256'], 'encoding': encoding, 'tables': [
        {'name': name, 'rows': len(table['rows']), 'columns': [column for column in table['schema']],
         'provided_columns': sorted({column for names in table['insert_columns'] for column in names})}
        for name, table in tables.items()]}


def existing_contracts(connection, reference, root, version_id, file, table=None):
    from . import local_contracts
    expected = table if table is not None else Path(file['filename']).stem
    choices = local_contracts.available(connection, version_id, file, root, table)
    chosen = next((choice for choice in choices if reference in (choice[1].name, choice[1].stem)), None)
    generic = reference in ('local', expected, expected + '.yml')
    if not generic and chosen is None:
        raise ValueError("Seul le contrat correspondant dans le dossier _contracts de cette version peut être chargé")
    _, config = local_contracts.read(connection, version_id, file, root, table, required=True,
                                    contract_version=local_contracts.candidate_version(chosen) if chosen and not generic else None)
    return [config]


def invalidate(connection, version_id):
    connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version_id)
                       .values(identities_reviewed=False, migration=None, approved_hash=None))


def propose(file, choice, path, root):
    source_path = f"uploads/{file['id']}/{file['filename']}"
    inspector = FilesystemSourceInspector(root, {source_path: path})
    source = {"path": source_path, "format": file["format"].upper(), "encoding": choice.encoding}
    if file["format"] == "csv":
        source.update(field_delimiter=choice.delimiter, row_delimiter=choice.row_delimiter, has_header=True)
        spec = source_spec({"source": source})
        schema = inspector.inspect(spec)
        # Proposition bornée ; elle ne remplace jamais une clé métier ou une unité explicite.
        from itertools import islice
        sample = list(islice(inspector.rows(spec), 1000))
        columns = []
        for column in schema.columns:
            values = [row[column.name] for row in sample if row[column.name] not in (None, "")]
            kind = "TEXT"
            if values:
                for candidate in ("INTEGER", "NUMBER", "DATE", "TIMESTAMP"):
                    try:
                        for value in values: loader.cast(value, candidate)
                        kind = candidate
                        break
                    except (ValueError, ArithmeticError):
                        continue
            item = {"source_name": column.name, "target_name": column.name, "type": kind,
                    "silver_type": {"INTEGER": "BIGINT", "NUMBER": "DOUBLE PRECISION"}.get(kind, kind)}
            if kind == "NUMBER": item["unit"] = None
            columns.append(item)
        return [{"version": "1.0.0", "kind": "BRONZE", "timezone": "UTC", "source": source,
                 "target": {"schema": "bronze", "table": legacy.normalized_name(file["dataset_name"]), "natural_key": []},
                 "max_cast_error_ratio": 0.0, "columns": columns, "derived_columns": []}]
    tables = inspector.sql_tables(SourceSpec(source_path, "SQL", choice.encoding))
    configs = []
    for name, table in tables.items():
        supplied = {column for names in table["insert_columns"] for column in names}
        mapping = {"IDENTITY": "IDENTIFIER", "FLOAT": "NUMBER", "DATETIME": "TIMESTAMP", "DATETIME_UTC": "TIMESTAMPTZ"}
        columns = []
        for column, spec in table["schema"].items():
            if column not in supplied: continue
            kind = mapping.get(spec["type"], spec["type"])
            sql_type = "TEXT" if kind == "IDENTIFIER" else "DOUBLE PRECISION" if kind == "NUMBER" else "INTEGER" if kind == "INTEGER" else spec["sql_type"].upper()
            columns.append({"source_name": column, "target_name": column, "type": kind, "silver_type": sql_type,
                            **({"unit": None} if kind == "NUMBER" else {})})
        configs.append({"version": "1.0.0", "kind": "BRONZE", "timezone": "UTC", "source": {**source, "table": name},
                        "target": {"schema": "bronze", "table": legacy.normalized_name(name), "natural_key": []},
                        "max_cast_error_ratio": 0.0, "columns": columns, "derived_columns": []})
    return configs


def contract_editor(engine, version_id, data, root):
    """Contrat local correspondant ou formulaire ; aucune recherche dans le catalogue global."""
    from . import local_contracts
    with engine.begin() as connection, tempfile.TemporaryDirectory() as folder:
        version = connection.execute(sa.select(db.model_versions).where(db.model_versions.c.id == version_id)).mappings().first()
        if version is None: raise HTTPException(404, "Version introuvable")
        prep = connection.execute(sa.select(db.preparations).where(db.preparations.c.model_version_id == version_id)).mappings().first()
        readonly = version['read_only'] or version['status'] != 'ingestion-bronze' or bool(prep and prep['state'] != 'draft')
        if not readonly: editable(connection, version_id)
        files = exact_files(connection, version_id, data.files)
        result, changed = [], False
        for choice in data.files:
            file = files[choice.id]
            if readonly and file['saved_yaml']:
                generated = parse_contracts(file['saved_yaml'])
            else:
                local_csv = local_contracts.read(connection, version_id, file, root)[1] if file['format'] == 'csv' else None
                if local_csv is not None:
                    generated = [local_csv]
                else:
                    source = materialize(file, Path(folder) / str(file['id']))
                    generated = propose(file, choice, source['path'], root)
            editors, configs = [], []
            for draft in generated:
                table = draft['source'].get('table') if file['format'] == 'sql' else None
                if readonly and file['saved_yaml']:
                    relative, _ = local_contracts.path_for(connection, version_id, file, root, table, contract_version=draft['version'], snapshot=True)
                    config, existing = draft, False
                else:
                    relative, config = local_contracts.read(connection, version_id, file, root, table)
                    existing = config is not None
                config = config or draft
                if not readonly:
                    config['source']['path'] = local_contracts.source_path(connection, version_id, file, root)
                text = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
                editors.append({'table': table, 'path': relative, 'existing': existing, 'config': config,
                                'yaml': text if existing or readonly else None})
                configs.append(config)
            text = yaml.safe_dump(configs[0] if len(configs) == 1 else configs, sort_keys=False, allow_unicode=True)
            saved = parse_contracts(file['saved_yaml']) if file['saved_yaml'] else None
            if not readonly:
                values = {'loaded_yaml': text, 'contract_mode': 'existing' if all(item['existing'] for item in editors) else 'generate',
                          'contract_ref': None}
                if saved != configs:
                    values.update(saved_yaml=None, summary=None, report=None, table_specs=None)
                    changed = True
                connection.execute(db.preparation_files.update().where(db.preparation_files.c.id == file['id']).values(**values))
            result.append({'id': str(file['id']), 'revision': file['revision'], 'filename': file['filename'], 'editors': editors, 'saved': saved == configs})
        if changed and not readonly: invalidate(connection, version_id)
    return {'files': result, **contract_schema(root)}


def load_contracts(engine, version_id, data, root):
    from . import local_contracts
    with engine.begin() as connection, tempfile.TemporaryDirectory() as folder:
        editable(connection, version_id)
        files = exact_files(connection, version_id, data.files)
        for choice in data.files:
            file = files[choice.id]
            if file['format'] == 'sql' and choice.tables is not None:
                source = materialize(file, Path(folder) / str(file['id']))
                generated = {config['source']['table']: config for config in propose(file, choice, source['path'], root)}
                names = [table.table for table in choice.tables]
                if len(names) != len(set(names)) or set(names) != set(generated):
                    raise ValueError("Choisis exactement un contrat pour chaque table détectée dans le fichier SQL")
                configs = []
                for table in choice.tables:
                    if table.mode == 'generate':
                        config = generated[table.table]
                    else:
                        matches = [config for config in existing_contracts(connection, table.contract, root, version_id, file, table.table)
                            if config.get('source', {}).get('format') == 'SQL' and config['source'].get('table') == table.table]
                        if len(matches) != 1: raise ValueError(f"{table.table}: le contrat choisi doit désigner exactement cette table SQL")
                        config = matches[0]
                    configs.append(config)
            elif choice.mode == "existing":
                configs = existing_contracts(connection, choice.contract, root, version_id, file)
            else:
                source = materialize(file, Path(folder) / str(file["id"]))
                configs = propose(file, choice, source["path"], root)
            for config in configs:
                if config.get('source', {}).get('format') != file['format'].upper():
                    raise ValueError("Le format du contrat ne correspond pas au fichier téléversé")
                config["source"]["path"] = local_contracts.source_path(connection, version_id, file, root)
            text = yaml.safe_dump(configs[0] if len(configs) == 1 else configs, sort_keys=False, allow_unicode=True)
            connection.execute(db.preparation_files.update().where(db.preparation_files.c.id == file["id"]).values(
                contract_mode=choice.mode, contract_ref=choice.contract, loaded_yaml=text, saved_yaml=None,
                sql_choices=[table.model_dump() for table in choice.tables] if choice.tables is not None else None,
                summary=None, report=None, table_specs=None, types_catalog=None))
            record(connection, version_id, "bronze_contract_loaded", {"filename": file["filename"], "mode": choice.mode})
        invalidate(connection, version_id)
    return {"loaded": True}


def inspect_files(files, root, directory, texts=None, *, connection):
    from . import local_contracts
    configs, overrides, by_file = [], {}, {}
    for file in files:
        text = texts[file["id"]] if texts else file["saved_yaml"]
        if not text: raise ValueError(f"{file['filename']}: contrat v2 requis")
        items = parse_contracts(text)
        source = materialize(file, Path(directory) / str(file["id"]))
        expected = local_contracts.source_path(connection, file['model_version_id'], file, root)
        legacy_path = f"uploads/{file['id']}/{file['filename']}"
        for item in items:
            declared = item.get("source", {})
            if not isinstance(declared, dict) or declared.get("path") not in (expected, legacy_path) or declared.get("format") != file["format"].upper():
                raise ValueError(f"{file['filename']}: source.path doit désigner {expected} et le format doit correspondre au fichier")
            overrides[declared['path']] = source['path']
        configs.extend(items)
        by_file[file["id"]] = items
    inspector = FilesystemSourceInspector(root, overrides)
    validate_or_raise(configs, root, inspector)
    for file in files:
        if file['format'] == 'sql':
            names = [config['source']['table'] for config in by_file[file['id']]]
            actual = inspector.sql_tables(source_spec(by_file[file['id']][0]))
            if len(names) != len(set(names)) or set(names) != set(actual):
                raise ValueError(f"{file['filename']}: un contrat distinct est requis pour chacune des tables SQL détectées")
    return configs, inspector, by_file


def identity(configs, inspector):
    tables, notes = [], []
    for config in configs:
        count = 0
        # Index temporaire sur disque : mémoire bornée même pour les cartes d'identité.
        with tempfile.TemporaryDirectory() as folder, closing(sqlite3.connect(str(Path(folder) / "identity.sqlite"))) as index:
            index.execute("CREATE TABLE fingerprints (digest TEXT PRIMARY KEY, n INTEGER NOT NULL)")
            for row in inspector.rows(source_spec(config)):
                count += 1
                digest = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                index.execute("INSERT INTO fingerprints VALUES (?, 1) ON CONFLICT(digest) DO UPDATE SET n=n+1", (digest,))
            duplicates = index.execute("SELECT COALESCE(SUM(n-1),0) FROM fingerprints").fetchone()[0]
        tables.append({"name": config["target"]["table"], "rows": count, "cols": len(config["columns"]),
                       "columns": [{"name": item["source_name"], "type": item["type"]} for item in config["columns"]], "duplicate_rows": duplicates})
        if not count: raise ValueError(f"{config['source']['path']}: aucune ligne à ingérer")
    notes.append("Aucune transformation métier exécutée. Clé métier déclarative, doublons sources conservés.")
    return {"tables": tables, "rows": sum(table["rows"] for table in tables), "duplicate_rows": sum(table["duplicate_rows"] for table in tables), "notes": notes}


def save_contracts(engine, version_id, data, root):
    with engine.begin() as connection, tempfile.TemporaryDirectory() as folder:
        version = editable(connection, version_id)
        files = exact_files(connection, version_id, data.files)
        for entry in data.files:
            file = files[entry.id]
            if file["loaded_yaml"] is None: raise HTTPException(409, "Charge les contrats avant de les sauvegarder")
            if entry.revision != file["revision"]: raise HTTPException(409, "Le contrat a changé dans un autre onglet")
        texts = {}
        for entry in data.files:
            if entry.tables is not None:
                if files[entry.id]['format'] != 'sql' or entry.yaml is not None or entry.config is not None:
                    raise ValueError("Fournis un éditeur par table SQL, sans contrat global supplémentaire")
                configs, names = [], set()
                expected = {config['source']['table'] for config in parse_contracts(files[entry.id]['loaded_yaml'])}
                for table in entry.tables:
                    if (table.yaml is None) == (table.config is None):
                        raise ValueError("Fournis le YAML ou les champs du formulaire, une seule représentation par table")
                    parsed = [table.config] if table.config is not None else parse_contracts(table.yaml)
                    if table.table in names or len(parsed) != 1 or parsed[0].get('source', {}).get('table') != table.table:
                        raise ValueError("Chaque éditeur SQL doit contenir le contrat de sa table, une seule fois")
                    names.add(table.table)
                    configs.extend(parsed)
                if names != expected: raise ValueError("Sauvegarde le contrat de chacune des tables SQL chargées")
                texts[entry.id] = yaml.safe_dump(configs[0] if len(configs) == 1 else configs, sort_keys=False, allow_unicode=True)
            else:
                if entry.config is not None:
                    if entry.yaml is not None or files[entry.id]['format'] != 'csv':
                        raise ValueError("Fournis un seul contrat CSV, en YAML ou avec le formulaire")
                    texts[entry.id] = yaml.safe_dump(entry.config, sort_keys=False, allow_unicode=True)
                else:
                    texts[entry.id] = entry.yaml
        from . import local_contracts
        # Convertir les anciens brouillons uploads/... sans accepter un chemin d'une autre version.
        for file_id, text in texts.items():
            configs = parse_contracts(text)
            file = files[file_id]
            expected = local_contracts.source_path(connection, version_id, file, root)
            legacy_path = f"uploads/{file['id']}/{file['filename']}"
            changed = False
            for config in configs:
                source = config.get('source', {})
                if not isinstance(source, dict):
                    continue  # La validation JSON Schema signalera la structure incorrecte.
                if source.get('path') == legacy_path:
                    source['path'] = expected
                    changed = True
            if changed:
                texts[file_id] = yaml.safe_dump(configs[0] if len(configs) == 1 else configs, sort_keys=False, allow_unicode=True)
        _, inspector, by_file = inspect_files(list(files.values()), root, folder, texts, connection=connection)
        paths = [local_contracts.path_for(connection, version_id, files[file_id], root,
                    config['source'].get('table') if files[file_id]['format'] == 'sql' else None,
                    contract_version=config['version'])[0]
                 for file_id, configs in by_file.items() for config in configs]
        if len(paths) != len(set(paths)):
            raise ValueError("Deux sources produisent le même nom de fichier contrat dans _contracts")
        for entry in data.files:
            summary = identity(by_file[entry.id], inspector)
            specs = {item["target"]["table"]: [{"name": column["source_name"], "spec": {"type": column["type"]}} for column in item["columns"]] for item in by_file[entry.id]}
            connection.execute(db.preparation_files.update().where(db.preparation_files.c.id == entry.id).values(
                saved_yaml=texts[entry.id], loaded_yaml=texts[entry.id], revision=files[entry.id]["revision"] + 1,
                summary=summary, report=None, table_specs=specs, types_catalog=None))
            record(connection, version_id, "bronze_contract_saved", {"filename": files[entry.id]["filename"], "revision": files[entry.id]["revision"] + 1})
        from . import local_contracts
        from . import source_archive
        for entry in data.files:
            source_archive.save(connection, version, files[entry.id], root)
            local_contracts.publish(connection, version_id, files[entry.id], root, by_file[entry.id])
        invalidate(connection, version_id)
    return {"saved": True}


def generate_identities(engine, version_id, root):
    from indusense_ingestion.contract_identity import generate_contract_identity
    from . import local_contracts
    from .source_archive import checked_path
    from . import source_archive
    with engine.begin() as connection, tempfile.TemporaryDirectory() as folder:
        version = editable(connection, version_id)
        files = files_for(connection, version_id)
        if not files: raise ValueError('Au moins un fichier est requis')
        _, inspector, by_file = inspect_files(files, root, folder, connection=connection)
        for file in files:
            expected = local_contracts.source_path(connection, version_id, file, root)
            if any(config['source']['path'] != expected for config in by_file[file['id']]):
                raise ValueError('Réenregistre les contrats avec leur chemin inputs avant de générer les cartes')
            source_archive.save(connection, version, file, root)
        reports = []
        for file in files:
            report = generate_contract_identity(by_file[file['id']], inspector, Path(root) / 'config/types.yaml')
            relative = local_contracts.source_directory(connection, version_id) + '/artifacts/ingestion-' + file['filename'] + '.md'
            path = checked_path(root, relative)
            reports.append((file, relative, path, report))
        # Ne publier aucun rapport si l'une des sources ou recettes est refusée.
        for file, relative, path, report in reports:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.identity-', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(report)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                local_contracts.sync_directory(path.parent)
            finally:
                if temporary is not None: temporary.unlink(missing_ok=True)
            summary = {**file['summary'], 'identity_path': '/' + relative}
            connection.execute(db.preparation_files.update().where(db.preparation_files.c.id == file['id']).values(report=report, summary=summary))
            record(connection, version_id, 'identity_generated', {'filename': file['filename'], 'path': relative, 'revision': file['revision']})
        connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version_id).values(identities_reviewed=False))
    return {'generated': True, 'reports': [relative for _, relative, _, _ in reports]}


def reviewed_plan(files, root, folder, connection):
    configs, inspector, by_file = inspect_files(files, root, folder, connection=connection)
    version = connection.execute(sa.select(db.model_versions).where(db.model_versions.c.id == files[0]["model_version_id"])).mappings().one()
    prep = connection.execute(sa.select(db.preparations).where(db.preparations.c.model_version_id == version["id"])).mappings().one()
    schema = model_database.schema_for(prep, version["number"])
    tracking = model_database.TRACKING_TABLES if schema != "bronze" else ()
    script = loader.migration_script(configs, schema, tracking)
    sql = loader.migration_sql(configs, schema, tracking)
    seal = hashlib.sha256(json.dumps({"files": [{"id": str(file["id"]), "source_hash": file["sha256"],
                "revision": file["revision"], "recipe_hash": config_hash(file["saved_yaml"])} for file in files], "script": script, "sql": sql}, sort_keys=True).encode()).hexdigest()
    return {"hash": seal, "script": script, "sql": sql, "schema": schema, "tables": [config["target"]["table"] for config in configs]}, configs, inspector, by_file


def generate_migration(engine, version_id, root):
    with engine.begin() as connection, tempfile.TemporaryDirectory() as folder:
        editable(connection, version_id)
        prep = connection.execute(sa.select(db.preparations).where(db.preparations.c.model_version_id == version_id)).mappings().one()
        if not prep["identities_reviewed"]: raise HTTPException(409, "Valide les cartes d’identité avant la migration")
        files = files_for(connection, version_id)
        if not files: raise ValueError("Au moins un fichier est requis")
        plan, _, _, _ = reviewed_plan(files, root, folder, connection)
        directory = Path(root) / "artifacts/bronze/migrations"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (plan["hash"] + ".py")).write_text(plan["script"], encoding="utf-8")
        connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version_id).values(migration=plan, approved_hash=None))
        record(connection, version_id, "bronze_migration_generated", {"hash": plan["hash"]})
    return plan


def approve_migration(engine, version_id, digest, root):
    with engine.begin() as connection, tempfile.TemporaryDirectory() as folder:
        editable(connection, version_id)
        prep = connection.execute(sa.select(db.preparations).where(db.preparations.c.model_version_id == version_id)).mappings().one()
        current, _, _, _ = reviewed_plan(files_for(connection, version_id), root, folder, connection)
        if not prep["migration"] or digest != prep["migration"]["hash"] or current != prep["migration"]:
            raise HTTPException(409, "La migration a changé : génère-la et relis-la avant approbation")
        connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version_id).values(approved_hash=digest))
        record(connection, version_id, "bronze_migration_approved", {"hash": digest})
    return {"approved": True}


def create(engine, version_id, data, root, progress=None):
    # Le verrou de session sérialise le chargement et ses journaux à transactions indépendantes.
    with engine.connect() as guard:
        model_id = guard.scalar(sa.select(db.model_versions.c.model_id).where(db.model_versions.c.id == version_id))
        if model_id is None: raise HTTPException(404, "Version introuvable")
        guard.execute(sa.text("SELECT pg_advisory_lock(hashtextextended(:id, 0))"), {"id": "model:" + str(model_id)})
        guard.commit()
        try:
            return _create(engine, version_id, data, root, progress)
        finally:
            guard.execute(sa.text("SELECT pg_advisory_unlock(hashtextextended(:id, 0))"), {"id": "model:" + str(model_id)})
            guard.commit()


def _create(engine, version_id, data, root, progress=None):
    progress = progress or (lambda phase: None)
    progress("Vérification des contrats et des archives")
    with tempfile.TemporaryDirectory() as folder, engine.begin() as connection:
        version = locked_version(connection, version_id)
        prep = connection.execute(sa.select(db.preparations).where(db.preparations.c.model_version_id == version_id)).mappings().first()
        if not prep or prep["protocol"] != 2 or version["status"] != "ingestion-bronze": raise HTTPException(409, "Préparation v2 active requise")
        files = list(exact_files(connection, version_id, data.files).values())
        if not prep["migration"] or not prep["approved_hash"]:
            raise HTTPException(409, "Une migration revue et approuvée est requise")
        for requested in data.files:
            file = next(file for file in files if file["id"] == requested.id)
            if requested.revision != file["revision"]: raise HTTPException(409, "Les contrats ont changé")
            if requested.technical_columns: raise ValueError("Les dérivations sont déclarées dans derived_columns et exécutées en Silver")
        plan, configs, inspector, by_file = reviewed_plan(files, root, folder, connection)
        if not prep["identities_reviewed"] or prep["approved_hash"] != plan["hash"] or prep["migration"] != plan:
            raise HTTPException(409, "Une migration à jour, revue et approuvée est requise")
        name = prep["database_name"]
        if not name:
            model = connection.execute(sa.select(db.models).where(db.models.c.id == version["model_id"])).mappings().one()
            name = model["database_name"] or legacy.normalized_name(model["name"])
            connection.execute(db.models.update().where(db.models.c.id == version["model_id"]).values(database_name=name))
            progress("Préparation de la base du modèle")
            legacy.ensure_model_database(engine, name, version["model_id"])
            connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version_id).values(database_name=name, state="created"))
        target = legacy.version_engine(engine, name)
        try:
            # Le binding de la base est durable avant les tentatives : reprise possible après un échec.
            connection.commit()
            with engine.begin() as journal:
                journal.execute(db.ingestion_batches_log.update().where(
                    db.ingestion_batches_log.c.model_version_id == version_id,
                    db.ingestion_batches_log.c.status == "RUNNING").values(status="FAILED", completed_at=sa.func.now(),
                        report={"error": "Tentative interrompue avant finalisation du journal ; reprise par une nouvelle tentative", "transformations": []}))
            with target.begin() as destination:
                progress("Application de la migration approuvée")
                loader.apply_migration(destination, configs, plan["schema"], model_database.TRACKING_TABLES if plan["schema"] != "bronze" else ())
            model_database.synchronize(engine, version_id)
            outcomes = []
            for file in files:
                for config in by_file[file["id"]]:
                    progress(f"Ingestion de {file['filename']} → {plan['schema']}.{config['target']['table']}")
                    batch_id = uuid4()
                    recipe_hash = config_hash(file["saved_yaml"])
                    source_hash = loader.fingerprint(inspector.path(source_spec(config)))
                    if source_hash != file["sha256"]: raise ValueError("Empreinte source différente de l'archive")
                    with engine.begin() as journal:
                        journal.execute(db.ingestion_batches_log.insert().values(batch_id=batch_id, model_version_id=version_id,
                            source_name=config["source"]["path"], source_format=config["source"]["format"], target_table=config["target"]["table"],
                            source_hash=source_hash, config_hash=recipe_hash, status="RUNNING"))
                    try:
                        report, dictionary = loader.load_configuration(target, inspector, config, recipe_hash, batch_id, schema=plan["schema"])
                    except loader.IngestionFailure as error:
                        report, dictionary = error.report, error.dictionary
                    # Journal conservé même si les données ont été annulées ou la publication disque échoue.
                    with engine.begin() as journal:
                        journal.execute(db.ingestion_batches_log.update().where(db.ingestion_batches_log.c.batch_id == batch_id).values(
                            status=report["status"], records_read=report["records_read"], records_inserted=report["records_inserted"],
                            records_rejected=report["records_rejected"], report=report, dictionary=dictionary, completed_at=sa.func.now()))
                        record(journal, version_id, "bronze_batch_finished", {"filename": file["filename"], "batch_id": str(batch_id), "status": report["status"]})
                    progress("Publication des rapports d'ingestion")
                    path = loader.write_artifacts(root, report, dictionary)
                    with engine.begin() as journal:
                        journal.execute(db.ingestion_batches_log.update().where(db.ingestion_batches_log.c.batch_id == batch_id).values(artifact_path=path))
                    outcomes.append(report)
                    model_database.synchronize(engine, version_id)
            with engine.begin() as journal:
                record(journal, version_id, "bronze_dataset_created", {"database": name, "schema": plan["schema"], "valid_rows": sum(item["records_inserted"] for item in outcomes), "pending_rows": 0})
            model_database.synchronize(engine, version_id)
        finally:
            target.dispose()
    return workspace(engine, version_id)


def workspace(engine, version_id):
    from .source_archive import history
    with engine.connect() as connection:
        version = connection.execute(sa.select(db.model_versions).where(db.model_versions.c.id == version_id)).mappings().first()
        if version is None: raise HTTPException(404, "Version introuvable")
        prep = connection.execute(sa.select(db.preparations).where(db.preparations.c.model_version_id == version_id)).mappings().first()
        files = files_for(connection, version_id, include_content=False)
        archives = history(connection, version_id)
        batches = [dict(row) for row in connection.execute(sa.select(db.ingestion_batches_log).where(db.ingestion_batches_log.c.model_version_id == version_id)
                    .order_by(db.ingestion_batches_log.c.started_at.desc())).mappings()]
    public_files = []
    for file in files:
        public = public_file(file)
        public['sql_contracts'] = [{'table': config['source']['table'], 'encoding': config['source']['encoding'],
            'yaml': yaml.safe_dump(config, sort_keys=False, allow_unicode=True)}
            for config in parse_contracts(file['loaded_yaml'])] if file['format'] == 'sql' and file['loaded_yaml'] else []
        public_files.append(public)
    result = {**(dict(prep) if prep else {"state": "draft", "database_name": None, "identities_reviewed": False, "protocol": 2, "migration": None, "approved_hash": None}),
              "files": public_files, "archives": archives, "readonly": version["read_only"] or version["status"] != "ingestion-bronze" or bool(prep and prep["state"] != "draft"),
              "status": version["status"], "dataset": None, "batches": batches, "can_validate": False,
              "schema_name": model_database.schema_for(prep or {}, version["number"])}
    if prep and prep["database_name"]:
        target = legacy.version_engine(engine, prep["database_name"])
        try:
            with target.connect() as connection:
                inspector = sa.inspect(connection)
                schema = result["schema_name"]
                completed = connection.execute(sa.select(loader.receipts_table(schema))).mappings().all() if inspector.has_table("_ingestion_receipts", schema=schema) else []
                configs = [config for file in files for config in parse_contracts(file["saved_yaml"])]
                tables = []
                for config in configs:
                    table = loader.data_table(config, schema)
                    count = connection.scalar(sa.select(sa.func.count()).select_from(table)) if inspector.has_table(table.name, schema=schema) else 0
                    tables.append({"name": table.name, "source": config["source"].get("table", "data"), "filename": config["source"]["path"],
                                   "file_id": "", "columns": list(table.c.keys()), "rows": count})
                result["dataset"] = {"pending": 0, "valid": sum(item["rows"] for item in tables), "excluded": 0, "tables": tables}
                successful = {(item["target"], item["source_hash"], item["config_hash"]) for item in completed}
                expected = {(config["target"]["table"], file["sha256"], config_hash(file["saved_yaml"])) for file in files for config in parse_contracts(file["saved_yaml"])}
                # Un sceau seul ne suffit pas : les deux artefacts doivent être disponibles.
                publications = {(batch["target_table"], batch["source_hash"], batch["config_hash"]) for batch in batches
                    if batch["status"] in ("SUCCESS", "PARTIAL", "SKIPPED") and batch["artifact_path"]}
                result["can_validate"] = bool(expected) and expected <= successful and expected <= publications and version["status"] == "ingestion-bronze" and not version["read_only"]
                result["can_validate"] = result["can_validate"] and all(
                    table["rows"] == sum(item["report"]["records_read"] for item in completed if item["target"] == table["name"])
                    for table in tables)
        finally:
            target.dispose()
    result["data_ready"] = result["can_validate"]
    with engine.connect() as connection:
        execution = connection.execute(sa.select(db.bronze_executions.c.status).where(db.bronze_executions.c.model_version_id == version_id)
            .order_by(db.bronze_executions.c.created_at.desc()).limit(1)).scalar_one_or_none()
    if execution is not None and execution != "SUCCESS": result["can_validate"] = False
    return result


def validate(engine, version_id):
    with engine.connect() as guard:
        guard.execute(sa.text("SELECT pg_advisory_lock(hashtextextended(:id, 0))"), {"id": str(version_id)})
        guard.commit()
        try:
            return _validate(engine, version_id)
        finally:
            guard.execute(sa.text("SELECT pg_advisory_unlock(hashtextextended(:id, 0))"), {"id": str(version_id)})
            guard.commit()


def _validate(engine, version_id):
    state = workspace(engine, version_id)
    if not state["can_validate"]: raise HTTPException(409, "Tous les lots et rapports doivent être scellés avant de valider Bronze")
    with engine.begin() as connection:
        version = locked_version(connection, version_id)
        if version["status"] != "ingestion-bronze": raise HTTPException(409, "Étape Bronze déjà validée")
        if connection.scalar(sa.select(db.bronze_executions.c.id).where(db.bronze_executions.c.model_version_id == version_id,
                db.bronze_executions.c.status.in_(["QUEUED", "RUNNING"]))):
            raise HTTPException(409, "Attends la fin du chargement avant de valider Bronze")
        connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version_id).values(state="complete"))
        connection.execute(db.model_versions.update().where(db.model_versions.c.id == version_id).values(status="ingestion-silver"))
        record(connection, version_id, "stage_validated", {"stage": "bronze"})
        record(connection, version_id, "status_changed", {"from_status": "ingestion-bronze", "to_status": "ingestion-silver"})
    model_database.synchronize(engine, version_id)
    return workspace(engine, version_id)


def preview(engine, version_id, table_name, offset, limit):
    state = workspace(engine, version_id)
    if not state["database_name"]: raise HTTPException(409, "Crée le Bronze avant consultation")
    configs = [config for file in state["files"] for config in parse_contracts(file["saved_yaml"])]
    config = next((config for config in configs if config["target"]["table"] == table_name), None)
    if config is None: raise HTTPException(404, "Table introuvable")
    target = legacy.version_engine(engine, state["database_name"])
    try:
        table = loader.data_table(config, state["schema_name"])
        with target.connect() as connection:
            rows = connection.execute(sa.select(table).order_by(table.c._source_hash, table.c._row_number).offset(offset).limit(limit)).mappings()
            return {"rows": [{"row_number": row["_row_number"], "data": {key: str(value) if isinstance(value, UUID) else loader.json_value(value) for key, value in row.items()}} for row in rows]}
    finally:
        target.dispose()


def review_schema(engine, version_id, table_name=None, offset=0, limit=20):
    """Consultation du seul schéma bronze de la base liée à la version sélectionnée."""
    with engine.connect() as connection:
        version = connection.execute(sa.select(db.model_versions).where(db.model_versions.c.id == version_id)).mappings().first()
        if version is None:
            raise HTTPException(404, "Version introuvable")
        prep = connection.execute(sa.select(db.preparations).where(db.preparations.c.model_version_id == version_id)).mappings().first()
        name = prep["database_name"] if prep else None
    if not name:
        raise HTTPException(409, "Crée le Bronze avant consultation")
    target = legacy.version_engine(engine, name)
    schema = model_database.schema_for(prep, version["number"])
    try:
        with target.begin() as connection:
            connection.execute(sa.text("SET TRANSACTION READ ONLY"))
            inspector = sa.inspect(connection)
            names = sorted(inspector.get_table_names(schema=schema))
            if table_name is not None:
                if table_name not in names:
                    raise HTTPException(404, "Table Bronze introuvable")
                table = sa.Table(table_name, sa.MetaData(), schema=schema, autoload_with=connection)
                primary = list(table.primary_key.columns)
                # Les tables techniques et de données ont une PK, utilisée pour une pagination stable.
                ordering = primary or [column for column in table.c if not isinstance(column.type, JSONB)]
                query = sa.select(table).order_by(*ordering).offset(offset).limit(limit)
                return {"rows": [{"data": {key: str(value) if isinstance(value, UUID) else loader.json_value(value)
                                  for key, value in row.items()}} for row in connection.execute(query).mappings()]}
            tables = []
            for name in names:
                table = sa.Table(name, sa.MetaData(), schema=schema, autoload_with=connection)
                tables.append({"name": name, "rows": connection.scalar(sa.select(sa.func.count()).select_from(table)),
                    "columns": [{"name": column.name, "type": str(column.type.compile(dialect=connection.dialect)),
                                 "nullable": column.nullable} for column in table.c]})
            return {"schema": schema, "tables": tables}
    finally:
        target.dispose()


def export(engine, version_id, root):
    """Sources et recettes dans leurs chemins relatifs, pour reconstruire hors du catalogue."""
    import zipfile
    state = workspace(engine, version_id)
    if state["protocol"] != 2 or not state["files"] or any(file["saved_yaml"] is None for file in state["files"]):
        raise HTTPException(409, "Des contrats v2 sauvegardés sont requis pour exporter les sources")
    archive = tempfile.TemporaryFile()
    try:
        with engine.connect() as connection, zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            files = files_for(connection, version_id)
            manifest = {"model_version_id": str(version_id), "migration": state["migration"], "approved_hash": state["approved_hash"], "files": []}
            for index, file in enumerate(files):
                source_path = parse_contracts(file['saved_yaml'])[0]['source']['path'].lstrip('/')
                bundle.writestr(source_path, bytes(file["content"]))
                contract_path = f"config/bronze/{index:02d}-{file['id']}.yml"
                bundle.writestr(contract_path, file["saved_yaml"])
                if file['report']:
                    identity_path = (file['summary'] or {}).get('identity_path')
                    if identity_path:
                        bundle.writestr(identity_path.lstrip('/'), file['report'])
                manifest["files"].append({"path": source_path, "sha256": file["sha256"], "contract": contract_path, "config_hash": config_hash(file["saved_yaml"])})
            bundle.writestr("config/schema/bronze.v2.schema.json", (root / "config/schema/bronze.v2.schema.json").read_bytes())
            bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for batch in state["batches"]:
                bundle.writestr(f"artifacts/bronze/{batch['batch_id']}/ingestion-report.json", json.dumps(batch["report"], ensure_ascii=False, default=str))
                bundle.writestr(f"artifacts/bronze/{batch['batch_id']}/data-dictionary.json", json.dumps(batch["dictionary"], ensure_ascii=False, default=str))
        archive.seek(0)
        return archive
    except BaseException:
        archive.close()
        raise

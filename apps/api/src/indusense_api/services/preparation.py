"""Brouillons persistants : téléverser, charger et sauvegarder les contrats."""
import tempfile
from pathlib import Path
from uuid import uuid4

import yaml
from fastapi import HTTPException
from sqlalchemy import select

from .. import catalog as db
from ..schemas import UploadEntry
from .analysis import MAX_BODY_BYTES, MAX_FILES, analyze
from .preload import preload
from .workflow import locked_version, record


def public_file(file):
    return {key: value for key, value in file.items() if key != "content"}


def files_for(connection, version_id, *, include_content=True):
    columns = list(db.preparation_files.c) if include_content else [column for column in db.preparation_files.c if column.name != "content"]
    return connection.execute(select(*columns).where(db.preparation_files.c.model_version_id == version_id)
                              .order_by(db.preparation_files.c.created_at, db.preparation_files.c.id)).mappings().all()


def editable(connection, version_id):
    version = locked_version(connection, version_id)
    if connection.scalar(select(db.bronze_executions.c.id).where(db.bronze_executions.c.model_version_id == version_id,
            db.bronze_executions.c.status.in_(["QUEUED", "RUNNING"]))):
        raise HTTPException(409, "Un chargement Bronze est en cours pour cette version")
    preparation = connection.execute(select(db.preparations).where(db.preparations.c.model_version_id == version_id)).mappings().first()
    if preparation and preparation["protocol"] != 2:
        raise HTTPException(409, "Ancienne préparation : consultation seule")
    if version["status"] != "ingestion-bronze" or (preparation and preparation["state"] != "draft"):
        raise HTTPException(409, "Le Bronze est créé : les étapes précédentes sont en consultation seule. Crée une nouvelle version pour modifier les données.")
    if preparation is None:
        connection.execute(db.preparations.insert().values(model_version_id=version_id))
    return version


def exact_files(connection, version_id, entries):
    files = files_for(connection, version_id)
    ids = [entry.id for entry in entries]
    if len(ids) != len(set(ids)) or set(ids) != {file["id"] for file in files}:
        raise HTTPException(409, "La liste de fichiers a changé. Recharge la préparation avant de continuer.")
    return {file["id"]: file for file in files}


def materialize(file, directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("source." + file["format"])
    path.write_bytes(bytes(file["content"]))
    return {"path": path, "filename": file["filename"], "format": file["format"],
            "sha256": file["sha256"], "size_bytes": len(file["content"])}


def upload(engine, version_id, prepared, entries, root):
    from . import source_archive
    with engine.begin() as connection:
        version = editable(connection, version_id)
        existing = files_for(connection, version_id)
        by_hash = {file["sha256"]: file for file in existing}
        by_name = {file["dataset_name"]: file for file in existing}
        total_bytes = sum(len(file["content"]) for file in existing)
        results = []
        for source, entry in zip(prepared, entries):
            if source["sha256"] in by_hash:
                source_archive.save(connection, version, by_hash[source["sha256"]], root)
                results.append({"id": by_hash[source["sha256"]]["id"], "filename": source["filename"], "status": "duplicate"})
                continue
            if entry.dataset_name in by_name:
                raise HTTPException(409, f"Le nom de dataset {entry.dataset_name} est déjà utilisé dans cette préparation.")
            total_bytes += source["size_bytes"]
            if len(by_hash) >= MAX_FILES or total_bytes > MAX_BODY_BYTES:
                raise HTTPException(413, "La préparation est limitée à 10 fichiers et 100 Mio au total.")
            candidate = {"id": uuid4(), "filename": source["filename"], "sha256": source["sha256"], "content": source["path"].read_bytes()}
            archive = source_archive.save(connection, version, candidate, root)
            record(connection, version_id, "source_archived", {"filename": archive["filename"], "path": archive["path"], "sha256": archive["sha256"]})
            file = connection.execute(db.preparation_files.insert().values(
                id=archive["id"], model_version_id=version_id, dataset_name=entry.dataset_name,
                filename=archive["filename"], format=source["format"], sha256=source["sha256"],
                content=candidate["content"], contract_mode="generate" if source["format"] == "csv" else "existing",
            ).returning(db.preparation_files)).mappings().one()
            by_hash[source["sha256"]] = file
            by_name[entry.dataset_name] = file
            record(connection, version_id, "file_staged", {"filename": source["filename"], "sha256": source["sha256"]})
            results.append({"id": file["id"], "filename": source["filename"], "status": "uploaded"})
        connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version_id).values(identities_reviewed=False, migration=None, approved_hash=None))
    return {"results": results}


def archive_files(engine, version_id, root):
    from . import source_archive
    with engine.begin() as connection:
        version = editable(connection, version_id)
        files = files_for(connection, version_id)
        if not files: raise HTTPException(409, "Téléverse au moins un fichier")
        for file in files:
            archive = source_archive.save(connection, version, file, root)
            record(connection, version_id, "source_archived", {"filename": archive["filename"], "path": archive["path"], "sha256": archive["sha256"]})
    return {"archived": len(files)}


def remove_file(engine, version_id, file_id):
    with engine.begin() as connection:
        editable(connection, version_id)
        file = connection.execute(select(db.preparation_files).where(db.preparation_files.c.id == file_id,
                                  db.preparation_files.c.model_version_id == version_id)).mappings().first()
        if file is None:
            raise HTTPException(404, "Fichier téléversé introuvable")
        connection.execute(db.preparation_files.delete().where(db.preparation_files.c.id == file_id))
        connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version_id).values(identities_reviewed=False, migration=None, approved_hash=None))
        record(connection, version_id, "staged_file_removed", {"filename": file["filename"]})
    return {"removed": True}


def load_contracts(engine, version_id, data, root):
    with engine.begin() as connection, tempfile.TemporaryDirectory(prefix="indusense-contracts-") as folder:
        editable(connection, version_id)
        files = exact_files(connection, version_id, data.files)
        work = Path(folder)
        prepared, entries = [], []
        for index, choice in enumerate(data.files):
            file = files[choice.id]
            prepared.append(materialize(file, work / str(index)))
            entries.append(UploadEntry(dataset_name=file["dataset_name"], contract=choice.contract,
                                       contract_mode=choice.mode) if file["format"] == "csv" else UploadEntry(dataset_name=file["dataset_name"]))
        results = preload(engine, version_id, prepared, entries, root, work)["results"]
        for choice, entry, result in zip(data.files, entries, results):
            connection.execute(db.preparation_files.update().where(db.preparation_files.c.id == choice.id).values(
                contract_mode=entry.contract_mode, contract_ref=entry.contract,
                loaded_yaml=result["contract_yaml"] or "", saved_yaml=None, summary=None,
                report=None, table_specs=None, types_catalog=None,
            ))
            record(connection, version_id, "bronze_contract_loaded", {"filename": result["filename"], "mode": entry.contract_mode})
        connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version_id).values(identities_reviewed=False))
    return {"loaded": True}


def save_contracts(engine, version_id, data, root):
    with engine.begin() as connection, tempfile.TemporaryDirectory(prefix="indusense-identities-") as folder:
        editable(connection, version_id)
        files = exact_files(connection, version_id, data.files)
        for index, entry in enumerate(data.files):
            file = files[entry.id]
            if file["loaded_yaml"] is None:
                raise HTTPException(409, "Charge tous les contrats avant de les sauvegarder.")
            if entry.revision != file["revision"]:
                raise HTTPException(409, "Un contrat a été modifié dans un autre onglet. Recharge la préparation.")
            if file["format"] == "csv" and not entry.yaml:
                raise HTTPException(422, f"Contrat YAML requis pour {file['filename']}")
            if file["format"] == "sql" and entry.yaml:
                raise HTTPException(422, "Le SQL utilise son schéma extrait, sans contrat CSV.")
            work = Path(folder) / str(index)
            source = materialize(file, work)
            contract = UploadEntry(dataset_name=file["dataset_name"], contract_yaml=entry.yaml if file["format"] == "csv" else None)
            analysis = analyze(source, contract, root, work)
            connection.execute(db.preparation_files.update().where(db.preparation_files.c.id == entry.id).values(
                saved_yaml=entry.yaml or "", loaded_yaml=entry.yaml or "", revision=file["revision"] + 1,
                summary=analysis["summary"], report=analysis["report"], table_specs=analysis["table_specs"],
                types_catalog=analysis["types_catalog"],
            ))
            record(connection, version_id, "bronze_contract_saved", {"filename": file["filename"], "revision": file["revision"] + 1})
        connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version_id).values(identities_reviewed=False))
    return {"saved": True}


def clone_draft(connection, parent_id, version_id):
    files = files_for(connection, parent_id)
    if not files:
        # Les anciennes versions stockaient seulement des snapshots dans le catalogue.
        old = connection.execute(select(db.dataset_versions, db.datasets.c.name.label("dataset_name"), db.sources.c.content, db.sources.c.sha256)
                                 .select_from(db.bindings.join(db.datasets, db.bindings.c.dataset_id == db.datasets.c.id)
                                              .join(db.dataset_versions, db.bindings.c.dataset_version_id == db.dataset_versions.c.id)
                                              .join(db.sources, db.dataset_versions.c.source_id == db.sources.c.id))
                                 .where(db.bindings.c.model_version_id == parent_id)).mappings().all()
        files = [{"id": uuid4(), "dataset_name": item["dataset_name"], "filename": item["filename"],
                  "format": item["format"], "sha256": item["sha256"], "content": item["content"],
                  "contract_mode": "existing", "contract_ref": f"snapshot:{item['id']}" if item["format"] == "csv" else None}
                 for item in old]
    if not files:
        return
    connection.execute(db.preparations.insert().values(model_version_id=version_id))
    for file in files:
        values = {key: value for key, value in file.items() if key not in ("id", "model_version_id", "created_at")}
        # Copier les octets, jamais des contrats v1 ou des décisions humaines dans le nouveau parcours.
        for key in ("loaded_yaml", "saved_yaml", "summary", "report", "table_specs", "types_catalog"):
            values[key] = None
        values.update(contract_mode="generate", contract_ref=None, revision=0, technical_columns=[])
        values['sql_choices'] = None
        connection.execute(db.preparation_files.insert().values(**values, id=uuid4(), model_version_id=version_id))


def confirm_identities(engine, version_id):
    with engine.begin() as connection:
        editable(connection, version_id)
        files = files_for(connection, version_id)
        if not files or any(file["saved_yaml"] is None for file in files):
            raise HTTPException(409, "Sauvegarde les contrats avant de valider les cartes d’identité.")
        if any(not file['report'] or not (file['summary'] or {}).get('identity_path') for file in files):
            raise HTTPException(409, 'Génère les cartes d’identité avant de les valider.')
        connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version_id).values(identities_reviewed=True))
        record(connection, version_id, "bronze_identities_reviewed", {"files": len(files)})
    return {"reviewed": True}

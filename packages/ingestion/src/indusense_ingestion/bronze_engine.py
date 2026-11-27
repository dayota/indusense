"""Chargement Bronze hybride, migrations Alembic et sceau transactionnel par configuration."""
import hashlib
import json
import io
import math
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from itertools import islice
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic.autogenerate import render_python_code
from alembic.migration import MigrationContext
from alembic.operations import Operations, ops
from sqlalchemy.dialects.postgresql import JSONB, insert

from .bronze_sources import source_spec
from .bronze_contracts import DEFAULT_MAX_CAST_ERROR_RATIO

TYPES = {"IDENTIFIER": sa.Text, "TEXT": sa.Text, "NUMBER": sa.Double, "INTEGER": sa.BigInteger,
         "DECIMAL": sa.Numeric, "BINARY": sa.SmallInteger, "BOOLEAN": sa.Boolean,
         "DATE": sa.Date, "TIME": sa.Time, "TIMESTAMP": sa.DateTime,
         "TIMESTAMPTZ": lambda: sa.DateTime(timezone=True)}


def data_table(config, schema="bronze"):
    columns = []
    for item in config["columns"]:
        name = item["target_name"]
        # nullable exprime une attente Silver, jamais une contrainte Bronze.
        columns.extend([sa.Column(name + "_raw", sa.Text, quote=True), sa.Column(name, TYPES[item["type"]](), quote=True)])
    columns.extend([
        sa.Column("_batch_id", sa.Uuid, nullable=False), sa.Column("_source_file", sa.Text, nullable=False),
        sa.Column("_source_hash", sa.String(64), primary_key=True), sa.Column("_row_number", sa.BigInteger, primary_key=True),
        sa.Column("_ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("_cast_errors", JSONB, nullable=False), sa.Column("_row_checksum", sa.String(64), nullable=False),
    ])
    return sa.Table(config["target"]["table"], sa.MetaData(schema=schema), *columns, quote=True)


receipts = sa.Table("_ingestion_receipts", sa.MetaData(schema="bronze"),
    sa.Column("target", sa.Text, primary_key=True), sa.Column("source_hash", sa.String(64), primary_key=True),
    sa.Column("config_hash", sa.String(64), nullable=False), sa.Column("report", JSONB, nullable=False),
    sa.Column("dictionary", JSONB, nullable=False))


def receipts_table(schema="bronze"):
    return receipts.to_metadata(sa.MetaData(), schema=schema)


def error_table(schema):
    return sa.Table("_ingestion_errors", sa.MetaData(schema=schema),
        sa.Column("id", sa.Uuid, primary_key=True), sa.Column("batch_id", sa.Uuid, nullable=False),
        sa.Column("target_table", sa.Text, nullable=False), sa.Column("source_file", sa.Text, nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False), sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("row_number", sa.BigInteger, nullable=False),
        # TEXT preserves even escaped NUL values which PostgreSQL JSONB cannot represent.
        sa.Column("raw_data", sa.Text, nullable=False), sa.Column("errors", JSONB, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def migration_operations(configs, schema="bronze", tracking_tables=()):
    schemas = list(dict.fromkeys([table.schema for table in tracking_tables] + [schema]))
    from sqlalchemy.dialects.postgresql import dialect
    quote = dialect().identifier_preparer.quote_schema
    operations = [ops.ExecuteSQLOp(f"CREATE SCHEMA IF NOT EXISTS {quote(name)}") for name in schemas]
    for table in tracking_tables:
        operation = ops.CreateTableOp.from_table(table)
        operation.if_not_exists = True
        operations.append(operation)
    tables = [receipts_table(schema)] + ([error_table(schema)] if schema != "bronze" else []) + [data_table(config, schema) for config in configs]
    return ops.UpgradeOps(operations + [ops.CreateTableOp.from_table(table) for table in tables])


def migration_script(configs, schema="bronze", tracking_tables=()):
    rendered = render_python_code(migration_operations(configs, schema, tracking_tables))
    return "\"\"\"Migration Bronze générée : revue humaine requise avant application.\"\"\"\nfrom alembic import op\nimport sqlalchemy as sa\nfrom sqlalchemy.dialects import postgresql\n\nrevision = 'bronze_v2_initial'\ndown_revision = None\nbranch_labels = None\ndepends_on = None\n\ndef upgrade():\n" + rendered + "\n\ndef downgrade():\n    raise RuntimeError('Aucune suppression automatique des données Bronze')\n"


def migration_sql(configs, schema="bronze", tracking_tables=()):
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    operations = Operations(context)
    for operation in migration_operations(configs, schema, tracking_tables).ops:
        operations.invoke(operation)
    return output.getvalue()


def apply_migration(connection, configs, schema="bronze", tracking_tables=()):
    inspector = sa.inspect(connection)
    context = MigrationContext.configure(connection, opts={"version_table_schema": "public" if schema == "bronze" else schema})
    if context.get_current_revision() == "bronze_v2_initial":
        # Comparer le schéma réel, y compris la PK d'idempotence, avant un rejeu.
        inspector = sa.inspect(connection)
        expected = [data_table(config, schema) for config in configs] + [receipts_table(schema)]
        if schema != "bronze": expected += [error_table(schema)] + list(tracking_tables)
        for table in expected:
            actual = inspector.get_columns(table.name, schema=table.schema)
            if [(item["name"], str(item["type"].compile(dialect=connection.dialect))) for item in actual] != [(column.name, str(column.type.compile(dialect=connection.dialect))) for column in table.columns]:
                raise ValueError("Le schéma réel diffère de la migration approuvée")
            if set(inspector.get_pk_constraint(table.name, schema=table.schema)["constrained_columns"]) != set(table.primary_key.columns.keys()):
                raise ValueError("Clé d'idempotence absente ou différente")
        return
    if context.get_current_revision() is not None:
        raise ValueError("Révision Alembic inattendue dans la base de version")
    operations = Operations(context)
    # A shared tracking table may already exist for an earlier version. Never accept a different layout.
    for table in tracking_tables:
        if inspector.has_table(table.name, schema=table.schema):
            actual = inspector.get_columns(table.name, schema=table.schema)
            if [(item["name"], str(item["type"].compile(dialect=connection.dialect))) for item in actual] != [(column.name, str(column.type.compile(dialect=connection.dialect))) for column in table.c]:
                raise ValueError("Le schéma versionning existant diffère de la migration approuvée")
    for operation in migration_operations(configs, schema, tracking_tables).ops:
        operations.invoke(operation)
    # La révision est écrite dans la même transaction que le DDL revu.
    context.stamp(safer_script_directory(), "bronze_v2_initial")


def safer_script_directory():
    # Révision statique sans import ni exécution de code fourni par l'utilisateur.
    from alembic.script import ScriptDirectory, Script
    from types import SimpleNamespace
    directory = ScriptDirectory(".")
    script = Script(SimpleNamespace(revision="bronze_v2_initial", down_revision=None, branch_labels=None, depends_on=None),
                    "bronze_v2_initial", "generated")
    directory.revision_map.add_revision(script)
    return directory


def cast(value, kind):
    if value is None or value == "":
        return None
    text = str(value)
    if "\x00" in text:
        raise ValueError("Caractère NUL non représentable dans PostgreSQL TEXT")
    if kind in ("TEXT", "IDENTIFIER"):
        return text
    if kind in ("NUMBER", "DECIMAL", "INTEGER", "BINARY"):
        number = Decimal(text)
        if not number.is_finite(): raise ValueError("Nombre non fini")
        if kind in ("INTEGER", "BINARY"):
            if number != number.to_integral_value(): raise ValueError("Entier attendu")
            integer = int(number)
            if not -(2 ** 63) <= integer < 2 ** 63: raise ValueError("Entier hors BIGINT")
            if kind == "BINARY" and integer not in (0, 1): raise ValueError("Valeur binaire 0 ou 1 attendue")
            return integer
        if kind == "DECIMAL": return number
        result = float(number)
        if not math.isfinite(result): raise ValueError("Nombre hors DOUBLE PRECISION")
        return result
    if kind == "BOOLEAN":
        if text.lower() not in ("true", "false", "0", "1"): raise ValueError("Booléen attendu")
        return text.lower() in ("true", "1")
    if kind == "DATE": return date.fromisoformat(text)
    if kind == "TIME": return time.fromisoformat(text)
    value = datetime.fromisoformat(text)
    if kind == "TIMESTAMPTZ":
        if value.tzinfo is not None and value.utcoffset().total_seconds() != 0:
            raise ValueError("Horloge UTC déclarée : décalage non UTC refusé, aucune conversion")
        return value.replace(tzinfo=timezone.utc)
    if value.tzinfo is not None: raise ValueError("TIMESTAMP sans fuseau attendu")
    return value


def json_value(value):
    if isinstance(value, (date, time, datetime)): return value.isoformat()
    if isinstance(value, Decimal): return str(value)
    return value


def fingerprint(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_configuration(engine, inspector, config, recipe_hash, batch_id=None, *, schema="bronze"):
    """Une transaction par configuration ; le registre des tentatives appartient à l'appelant."""
    batch_id = batch_id or uuid4()
    source = source_spec(config)
    source_hash = fingerprint(inspector.path(source))
    table = data_table(config, schema)
    receipts = receipts_table(schema)
    metrics = [{**item, "raw_column": item["target_name"] + "_raw", "cast_failures": 0, "nulls": 0, "min": None, "max": None}
               for item in config["columns"]]
    report = {"batch_id": str(batch_id), "target": table.name, "source_file": source.path,
              "source_hash": source_hash, "config_hash": recipe_hash, "records_read": 0, "records_inserted": 0,
              "cast_error_rows": 0, "records_rejected": 0, "status": "FAILED",
              "max_cast_error_ratio": config.get("max_cast_error_ratio", DEFAULT_MAX_CAST_ERROR_RATIO),
              "derived_columns": config.get("derived_columns", []),
              "transformations": [{"code": "CAST", "detail": "Miroirs bruts préservés ; typage au mieux ; horloge UTC étiquetée sans conversion"}]}
    dictionary = {"target": table.name, "columns": metrics, "derived_columns": config.get("derived_columns", []),
                  "transformations": report["transformations"], "anomalies": []}
    try:
        with engine.begin() as connection:
            # Sérialiser aussi les processus CLI/API concurrents et les rejeux après interruption.
            connection.execute(sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                               {"key": table.name + ":" + source_hash})
            existing = connection.execute(sa.select(receipts).where(receipts.c.target == table.name, receipts.c.source_hash == source_hash)).mappings().first()
            if existing:
                if existing["config_hash"] != recipe_hash:
                    raise ValueError("Cette source est déjà scellée avec une autre configuration : crée une nouvelle version")
                return {**existing["report"], "batch_id": str(batch_id), "status": "SKIPPED", "records_inserted": 0,
                        "replayed_batch_id": existing["report"]["batch_id"]}, existing["dictionary"]
            iterator = iter(inspector.rows(source))
            while rows := list(islice(iterator, 5000)):
                prepared = []
                for raw in rows:
                    report["records_read"] += 1
                    output, errors = {}, {}
                    for metric in metrics:
                        name = metric["target_name"]
                        original = raw.get(metric["source_name"])
                        if isinstance(original, str) and "\x00" in original:
                            raise ValueError(f"Ligne {report['records_read']}: NUL non représentable ; source archivée, lot annulé")
                        output[name + "_raw"] = original
                        try:
                            value = cast(original, metric["type"])
                        except (ValueError, InvalidOperation, OverflowError) as error:
                            value = None
                            errors[name] = f"{type(error).__name__}: {error}"
                            metric["cast_failures"] += 1
                        output[name] = value
                        if value is None:
                            metric["nulls"] += 1
                        elif metric["type"] not in ("TEXT", "IDENTIFIER"):
                            metric["min"] = value if metric["min"] is None else min(value, metric["min"])
                            metric["max"] = value if metric["max"] is None else max(value, metric["max"])
                    if errors: report["cast_error_rows"] += 1
                    checksum = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                    output.update(_batch_id=batch_id, _source_file=source.path, _source_hash=source_hash,
                                  _row_number=report["records_read"], _ingested_at=datetime.now(timezone.utc),
                                  _cast_errors=errors, _row_checksum=checksum)
                    prepared.append(output)
                inserted = connection.execute(insert(table).on_conflict_do_nothing(
                    index_elements=["_source_hash", "_row_number"]).returning(table.c._row_number), prepared)
                # psycopg peut retourner rowcount=-1 pour executemany : compter les lignes réellement retournées.
                report["records_inserted"] += len(inserted.fetchall())
            if not report["records_read"]:
                raise ValueError("Aucune ligne à ingérer")
            ratio = report["cast_error_rows"] / report["records_read"]
            if ratio > config.get("max_cast_error_ratio", DEFAULT_MAX_CAST_ERROR_RATIO):
                raise ValueError(f"Seuil d'erreurs de cast dépassé : {ratio:.6f}")
            report["status"] = "PARTIAL" if report["cast_error_rows"] else "SUCCESS"
            duplicates = connection.scalar(sa.select(sa.func.count()).select_from(sa.select(table.c._row_checksum)
                .where(table.c._source_hash == source_hash).group_by(table.c._row_checksum).having(sa.func.count() > 1).subquery()))
            report["duplicate_groups"] = duplicates
            if duplicates:
                dictionary["anomalies"].append({"kind": "strict_duplicates", "groups": duplicates, "layer": "silver", "action": "conserved"})
            dictionary["anomalies"].extend({"column": metric["target_name"], "cast_failures": metric["cast_failures"], "layer": "silver"}
                                        for metric in metrics if metric["cast_failures"])
            for metric in metrics:
                metric["null_rate"] = metric.pop("nulls") / report["records_read"]
                metric["min"], metric["max"] = json_value(metric["min"]), json_value(metric["max"])
            connection.execute(receipts.insert().values(target=table.name, source_hash=source_hash, config_hash=recipe_hash,
                               report=report, dictionary=dictionary))
        return report, dictionary
    except Exception as error:
        report.update(status="FAILED", records_inserted=0, records_rejected=report["records_read"], error=str(error))
        for metric in metrics:
            metric["min"], metric["max"] = json_value(metric["min"]), json_value(metric["max"])
            metric["null_rate"] = metric.pop("nulls", 0) / report["records_read"] if report["records_read"] else 0
        if schema != "bronze":
            rejected = persist_failed_rows(engine, inspector, config, recipe_hash, batch_id, source_hash, str(error), schema)
            report["records_rejected"] = rejected
            report["records_read"] = max(report["records_read"], rejected)
        raise IngestionFailure(report, dictionary) from error


def persist_failed_rows(engine, inspector, config, recipe_hash, batch_id, source_hash, reason, schema):
    """Independent transaction after rollback: every cancelled row retains its exact source values."""
    table = error_table(schema)
    # Re-read the archived source in a stream: rows not reached before an SQL error are also accounted for.
    iterator = enumerate(inspector.rows(source_spec(config)), 1)
    count = 0
    with engine.begin() as connection:
        while chunk := list(islice(iterator, 5000)):
            logs = []
            for number, raw in chunk:
                errors = {}
                for column in config["columns"]:
                    try:
                        cast(raw.get(column["source_name"]), column["type"])
                    except (ValueError, InvalidOperation, OverflowError) as error:
                        errors[column["target_name"]] = str(error).replace("\x00", "\\u0000")
                logs.append({"id": uuid4(), "batch_id": batch_id, "target_table": config["target"]["table"],
                    "source_file": config["source"]["path"], "source_hash": source_hash, "config_hash": recipe_hash,
                    "row_number": number, "raw_data": json.dumps(raw, ensure_ascii=True), "errors": errors,
                    "reason": reason.replace("\x00", "\\u0000")})
            connection.execute(table.insert(), logs)
            count += len(logs)
    return count


class IngestionFailure(ValueError):
    def __init__(self, report, dictionary):
        self.report, self.dictionary = report, dictionary
        super().__init__(report["error"])


def write_artifacts(root, report, dictionary):
    directory = Path(root) / "artifacts/bronze" / report["batch_id"]
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in (("ingestion-report.json", report), ("data-dictionary.json", dictionary)):
        path = directory / name
        text = json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        # L'identifiant de tentative est unique ; publier chaque artefact par renommage atomique.
        temporary = path.with_suffix(".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    return str(directory.relative_to(root))

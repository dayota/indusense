"""Model-local versionning schema. All DDL is included in the reviewed Bronze migration."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, insert

from .. import catalog as db
from . import bronze_storage as storage

metadata = sa.MetaData(schema="versionning")
versions = sa.Table("model_versions", metadata,
    sa.Column("id", sa.Uuid, primary_key=True), sa.Column("model_id", sa.Uuid, nullable=False),
    sa.Column("number", sa.Integer, nullable=False, unique=True), sa.Column("status", sa.String(32), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("metrics", JSONB, nullable=False, server_default="{}"))
transitions = sa.Table("version_events", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True), sa.Column("model_version_id", sa.Uuid, nullable=False),
    sa.Column("action", sa.Text, nullable=False), sa.Column("details", JSONB, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
batches = db.ingestion_batches_log.to_metadata(metadata, schema="versionning")
# References belong to the control catalogue; local version IDs are still explicitly preserved.
for constraint in list(batches.foreign_key_constraints):
    batches.constraints.remove(constraint)
    for element in constraint.elements:
        batches.foreign_keys.discard(element)
executions = db.bronze_executions.to_metadata(metadata, schema="versionning")
for constraint in list(executions.foreign_key_constraints):
    executions.constraints.remove(constraint)
    for element in constraint.elements:
        executions.foreign_keys.discard(element)
TRACKING_TABLES = (versions, transitions, batches, executions)


def schema_for(preparation, number):
    # Historical dedicated databases keep their original layout and remain readable.
    return (preparation.get("migration") or {}).get("schema", "bronze") if preparation.get("database_name") else f"{number}-bronze"


def synchronize(engine, version_id):
    """Reconcile the durable control catalogue into the model database, preserving stable IDs."""
    with engine.connect() as connection:
        version = connection.execute(sa.select(db.model_versions).where(db.model_versions.c.id == version_id)).mappings().one()
        name = connection.scalar(sa.select(db.models.c.database_name).where(db.models.c.id == version["model_id"]))
        if not name: return
    target = storage.version_engine(engine, name)
    try:
        with target.begin() as connection:
            connection.execute(sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 0))"), {"id": "history:" + str(version["model_id"])})
            if not sa.inspect(connection).has_table("model_versions", schema="versionning"): return
            # Read only after acquiring the destination lock: an older snapshot must never
            # overwrite a newer status during concurrent validation and job finalization.
            with engine.connect() as source:
                model_versions = [dict(row) for row in source.execute(sa.select(db.model_versions).where(db.model_versions.c.model_id == version["model_id"])).mappings()]
                ids = [row["id"] for row in model_versions]
                events = [dict(row) for row in source.execute(sa.select(db.history).where(db.history.c.model_version_id.in_(ids))).mappings()]
                logs = [dict(row) for row in source.execute(sa.select(db.ingestion_batches_log).where(db.ingestion_batches_log.c.model_version_id.in_(ids))).mappings()]
                runs = [dict(row) for row in source.execute(sa.select(db.bronze_executions).where(db.bronze_executions.c.model_version_id.in_(ids))).mappings()]
            for table, records in ((versions, model_versions), (transitions, events), (batches, logs), (executions, runs)):
                for row in records:
                    values = {key: value for key, value in row.items() if key in table.c}
                    if table is versions:
                        own = [item for item in logs if item["model_version_id"] == row["id"]]
                        latest = {}
                        for batch in sorted(own, key=lambda item: item["started_at"]):
                            latest[(batch["target_table"], batch["source_hash"])] = batch
                        values["metrics"] = {"records_read": sum(item["records_read"] for item in latest.values()),
                            "records_inserted": sum((item["report"] or {}).get("records_read", 0) for item in latest.values() if item["status"] in ("SUCCESS", "PARTIAL", "SKIPPED")),
                            "records_rejected": sum(item["records_rejected"] for item in latest.values()), "attempts": len(own)}
                    statement = insert(table).values(**values)
                    keys = list(table.primary_key.columns.keys())
                    connection.execute(statement.on_conflict_do_update(index_elements=keys,
                        set_={key: statement.excluded[key] for key in values if key not in keys}))
    finally:
        target.dispose()

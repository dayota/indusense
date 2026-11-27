"""Catalogue et données brutes ; toutes les versions de données sont immuables."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from .version_status import ModelVersionStatus

metadata = MetaData(schema="bronze")


def identifier():
    return Column("id", Uuid, primary_key=True)


def timestamp():
    return Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    )


models = Table(
    "models",
    metadata,
    identifier(),
    Column("name", String(120), nullable=False, unique=True),
    Column("description", Text, nullable=False),
    Column("database_name", String(63), unique=True),
    timestamp(),
)
model_versions = Table(
    "model_versions",
    metadata,
    identifier(),
    Column("model_id", Uuid, ForeignKey("bronze.models.id"), nullable=False),
    Column("number", Integer, nullable=False),
    Column("read_only", Boolean, nullable=False, server_default="false"),
    Column(
        "status",
        String(32),
        nullable=False,
        server_default=ModelVersionStatus.INGESTION_BRONZE.value,
    ),
    timestamp(),
    UniqueConstraint("model_id", "number"),
    CheckConstraint(
        "status IN ('ingestion-bronze', 'ingestion-silver', 'ingestion-gold', 'training', 'challenger', 'champion')",
        name="ck_model_versions_status",
    ),
)
for exclusive_status in (ModelVersionStatus.CHAMPION, ModelVersionStatus.CHALLENGER):
    Index(
        f"uq_model_versions_{exclusive_status.value}",
        model_versions.c.model_id,
        unique=True,
        postgresql_where=model_versions.c.status == exclusive_status.value,
    )
datasets = Table(
    "datasets",
    metadata,
    identifier(),
    Column("model_id", Uuid, ForeignKey("bronze.models.id"), nullable=False),
    Column("name", String(120), nullable=False),
    timestamp(),
    UniqueConstraint("model_id", "name"),
)
sources = Table(
    "sources",
    metadata,
    identifier(),
    Column("sha256", String(64), nullable=False, unique=True),
    Column("size_bytes", BigInteger, nullable=False),
    Column("content", LargeBinary, nullable=False),
    timestamp(),
)
dataset_versions = Table(
    "dataset_versions",
    metadata,
    identifier(),
    Column("dataset_id", Uuid, ForeignKey("bronze.datasets.id"), nullable=False),
    Column("source_id", Uuid, ForeignKey("bronze.sources.id"), nullable=False),
    Column("number", Integer, nullable=False),
    Column("filename", String(255), nullable=False),
    Column("format", String(3), nullable=False),
    Column("contract_name", String(120)),
    Column("contract", JSONB),
    Column("types_catalog", JSONB, nullable=False),
    Column("summary", JSONB, nullable=False),
    Column("report", Text, nullable=False),
    timestamp(),
    UniqueConstraint("dataset_id", "number"),
    UniqueConstraint("dataset_id", "source_id"),
)
bindings = Table(
    "model_datasets",
    metadata,
    Column(
        "model_version_id",
        Uuid,
        ForeignKey("bronze.model_versions.id"),
        primary_key=True,
    ),
    Column("dataset_id", Uuid, ForeignKey("bronze.datasets.id"), primary_key=True),
    Column(
        "dataset_version_id",
        Uuid,
        ForeignKey("bronze.dataset_versions.id"),
        nullable=False,
    ),
)
rows = Table(
    "rows",
    metadata,
    Column(
        "dataset_version_id",
        Uuid,
        ForeignKey("bronze.dataset_versions.id"),
        primary_key=True,
    ),
    Column("table_name", Text, primary_key=True),
    Column("row_number", Integer, primary_key=True),
    Column("data", JSONB, nullable=False),
)
history = Table(
    "history",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "model_version_id", Uuid, ForeignKey("bronze.model_versions.id"), nullable=False
    ),
    Column("dataset_version_id", Uuid, ForeignKey("bronze.dataset_versions.id")),
    Column("action", String(40), nullable=False),
    Column("details", JSONB, nullable=False),
    timestamp(),
)

# Contrats et traitements silver : chaque exécution conserve son contrat et sa source.
silver_contracts = Table(
    "contracts", metadata,
    identifier(),
    Column("model_version_id", Uuid, ForeignKey("bronze.model_versions.id"), nullable=False),
    Column("dataset_version_id", Uuid, ForeignKey("bronze.dataset_versions.id"), nullable=False),
    Column("table_name", Text, nullable=False),
    Column("number", Integer, nullable=False),
    Column("yaml", Text, nullable=False),
    Column("config", JSONB, nullable=False),
    Column("columns", JSONB, nullable=False),
    Column("types_catalog", JSONB, nullable=False),
    timestamp(),
    UniqueConstraint("model_version_id", "dataset_version_id", "table_name", "number"),
    schema="silver",
)
silver_runs = Table(
    "runs", metadata,
    identifier(),
    Column("model_version_id", Uuid, ForeignKey("bronze.model_versions.id"), nullable=False),
    Column("dataset_version_id", Uuid, ForeignKey("bronze.dataset_versions.id"), nullable=False),
    Column("table_name", Text, nullable=False),
    Column("contract_id", Uuid, ForeignKey("silver.contracts.id"), nullable=False, unique=True),
    Column("columns", JSONB, nullable=False),
    Column("source_rows", Integer, nullable=False),
    timestamp(),
    schema="silver",
)
silver_rows = Table(
    "rows", metadata,
    Column("run_id", Uuid, ForeignKey("silver.runs.id"), primary_key=True),
    Column("row_number", Integer, primary_key=True),
    Column("data", JSONB, nullable=False),
    schema="silver",
)
quarantine = Table(
    "quarantine", metadata,
    identifier(),
    Column("run_id", Uuid, ForeignKey("silver.runs.id"), nullable=False),
    Column("row_number", Integer, nullable=False),
    Column("source", JSONB, nullable=False),
    Column("candidate", JSONB, nullable=False),
    Column("errors", JSONB, nullable=False),
    Column("state", String(16), nullable=False, server_default="pending"),
    Column("reason", Text),
    Column("resolved_at", DateTime(timezone=True)),
    timestamp(),
    UniqueConstraint("run_id", "row_number"),
    CheckConstraint("state IN ('pending', 'reintegrated', 'discarded')", name="ck_quarantine_state"),
    schema="silver",
)
Index("ix_silver_runs_version", silver_runs.c.model_version_id)
Index("ix_quarantine_pending", quarantine.c.run_id, postgresql_where=quarantine.c.state == "pending")

# Brouillons du formulaire Bronze ; les bases de données de version contiennent les datasets typés.
preparations = Table(
    "preparations", metadata,
    Column("model_version_id", Uuid, ForeignKey("bronze.model_versions.id"), primary_key=True),
    Column("database_name", String(63)),
    Column("state", String(16), nullable=False, server_default="draft"),
    Column("identities_reviewed", Boolean, nullable=False, server_default="false"),
    Column("protocol", Integer, nullable=False, server_default="2"),
    Column("migration", JSONB),
    Column("approved_hash", String(64)),
    Column("archive_directory", Text, unique=True),
    timestamp(),
    CheckConstraint("state IN ('draft', 'created', 'complete')", name="ck_preparation_state"),
)
preparation_files = Table(
    "preparation_files", metadata,
    identifier(),
    Column("model_version_id", Uuid, ForeignKey("bronze.preparations.model_version_id"), nullable=False),
    Column("dataset_name", String(120), nullable=False),
    Column("filename", String(255), nullable=False),
    Column("format", String(3), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("contract_mode", String(16), nullable=False, server_default="generate"),
    Column("contract_ref", String(120)),
    Column("loaded_yaml", Text),
    Column("saved_yaml", Text),
    Column("sql_choices", JSONB),
    Column("revision", Integer, nullable=False, server_default="0"),
    Column("summary", JSONB),
    Column("report", Text),
    Column("table_specs", JSONB),
    Column("types_catalog", JSONB),
    Column("technical_columns", JSONB, nullable=False, server_default="[]"),
    timestamp(),
    UniqueConstraint("model_version_id", "sha256"),
    UniqueConstraint("model_version_id", "dataset_name"),
    CheckConstraint("contract_mode IN ('existing', 'generate')", name="ck_preparation_contract_mode"),
)

source_archives = Table(
    "source_archives", metadata,
    identifier(),
    Column("model_version_id", Uuid, ForeignKey("bronze.model_versions.id"), nullable=False),
    Column("filename", String(255), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("path", Text, nullable=False, unique=True),
    timestamp(),
    UniqueConstraint("model_version_id", "filename"),
    UniqueConstraint("model_version_id", "sha256"),
)

ingestion_batches_log = Table(
    "ingestion_batches_log", metadata,
    Column("batch_id", Uuid, primary_key=True),
    Column("model_version_id", Uuid, ForeignKey("bronze.model_versions.id")),
    Column("source_name", Text, nullable=False), Column("source_format", String(20), nullable=False),
    Column("target_table", Text, nullable=False), Column("source_hash", String(64), nullable=False),
    Column("config_hash", String(64), nullable=False),
    Column("records_read", BigInteger, nullable=False, server_default="0"),
    Column("records_inserted", BigInteger, nullable=False, server_default="0"),
    Column("records_rejected", BigInteger, nullable=False, server_default="0"),
    Column("status", String(20), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("completed_at", DateTime(timezone=True)),
    Column("report", JSONB), Column("dictionary", JSONB), Column("artifact_path", Text),
    CheckConstraint("status IN ('RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED', 'SKIPPED')", name="ck_ingestion_batches_status"),
)

# Durable control-plane queue, including failures occurring before the model database exists.
bronze_executions = Table("bronze_executions", metadata,
    identifier(), Column("model_version_id", Uuid, ForeignKey("bronze.model_versions.id"), nullable=False),
    Column("status", String(16), nullable=False), Column("phase", Text, nullable=False),
    Column("body", JSONB, nullable=False), Column("error", Text),
    timestamp(), Column("completed_at", DateTime(timezone=True)),
    CheckConstraint("status IN ('QUEUED','RUNNING','SUCCESS','FAILED')", name="ck_bronze_execution_status"))
Index("uq_bronze_active_execution", bronze_executions.c.model_version_id, unique=True,
      postgresql_where=bronze_executions.c.status.in_(["QUEUED", "RUNNING"]))

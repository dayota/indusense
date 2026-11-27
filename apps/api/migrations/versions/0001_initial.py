"""Schéma initial consolidé du catalogue InduSense.

Capture autonome de l'état du schéma ; ne dépend pas des modèles applicatifs futurs.
Remplace les migrations 0001 à 0008 pour les nouvelles installations.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE SCHEMA IF NOT EXISTS bronze')
    op.execute('CREATE SCHEMA IF NOT EXISTS silver')
    op.execute('CREATE SCHEMA IF NOT EXISTS gold')
    op.create_table('models',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('database_name', sa.String(length=63), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('database_name'),
    sa.UniqueConstraint('name'),
    schema='bronze'
    )
    op.create_table('sources',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sha256'),
    schema='bronze'
    )
    op.create_table('datasets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('model_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['model_id'], ['bronze.models.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('model_id', 'name'),
    schema='bronze'
    )
    op.create_table('model_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('model_id', sa.Uuid(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('read_only', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('status', sa.String(length=32), server_default='ingestion-bronze', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('ingestion-bronze', 'ingestion-silver', 'ingestion-gold', 'training', 'challenger', 'champion')", name='ck_model_versions_status'),
    sa.ForeignKeyConstraint(['model_id'], ['bronze.models.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('model_id', 'number'),
    schema='bronze'
    )
    op.create_index('uq_model_versions_challenger', 'model_versions', ['model_id'], unique=True, schema='bronze', postgresql_where=sa.text("status = 'challenger'"))
    op.create_index('uq_model_versions_champion', 'model_versions', ['model_id'], unique=True, schema='bronze', postgresql_where=sa.text("status = 'champion'"))
    op.create_table('bronze_executions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('model_version_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('phase', sa.Text(), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=Text()), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('QUEUED','RUNNING','SUCCESS','FAILED')", name='ck_bronze_execution_status'),
    sa.ForeignKeyConstraint(['model_version_id'], ['bronze.model_versions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='bronze'
    )
    op.create_index('uq_bronze_active_execution', 'bronze_executions', ['model_version_id'], unique=True, schema='bronze', postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"))
    op.create_table('dataset_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('dataset_id', sa.Uuid(), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('format', sa.String(length=3), nullable=False),
    sa.Column('contract_name', sa.String(length=120), nullable=True),
    sa.Column('contract', postgresql.JSONB(astext_type=Text()), nullable=True),
    sa.Column('types_catalog', postgresql.JSONB(astext_type=Text()), nullable=False),
    sa.Column('summary', postgresql.JSONB(astext_type=Text()), nullable=False),
    sa.Column('report', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['bronze.datasets.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['bronze.sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dataset_id', 'number'),
    sa.UniqueConstraint('dataset_id', 'source_id'),
    schema='bronze'
    )
    op.create_table('ingestion_batches_log',
    sa.Column('batch_id', sa.Uuid(), nullable=False),
    sa.Column('model_version_id', sa.Uuid(), nullable=True),
    sa.Column('source_name', sa.Text(), nullable=False),
    sa.Column('source_format', sa.String(length=20), nullable=False),
    sa.Column('target_table', sa.Text(), nullable=False),
    sa.Column('source_hash', sa.String(length=64), nullable=False),
    sa.Column('config_hash', sa.String(length=64), nullable=False),
    sa.Column('records_read', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('records_inserted', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('records_rejected', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('report', postgresql.JSONB(astext_type=Text()), nullable=True),
    sa.Column('dictionary', postgresql.JSONB(astext_type=Text()), nullable=True),
    sa.Column('artifact_path', sa.Text(), nullable=True),
    sa.CheckConstraint("status IN ('RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED', 'SKIPPED')", name='ck_ingestion_batches_status'),
    sa.ForeignKeyConstraint(['model_version_id'], ['bronze.model_versions.id'], ),
    sa.PrimaryKeyConstraint('batch_id'),
    schema='bronze'
    )
    op.create_table('preparations',
    sa.Column('model_version_id', sa.Uuid(), nullable=False),
    sa.Column('database_name', sa.String(length=63), nullable=True),
    sa.Column('state', sa.String(length=16), server_default='draft', nullable=False),
    sa.Column('identities_reviewed', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('protocol', sa.Integer(), server_default='2', nullable=False),
    sa.Column('migration', postgresql.JSONB(astext_type=Text()), nullable=True),
    sa.Column('approved_hash', sa.String(length=64), nullable=True),
    sa.Column('archive_directory', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("state IN ('draft', 'created', 'complete')", name='ck_preparation_state'),
    sa.ForeignKeyConstraint(['model_version_id'], ['bronze.model_versions.id'], ),
    sa.PrimaryKeyConstraint('model_version_id'),
    sa.UniqueConstraint('archive_directory'),
    schema='bronze'
    )
    op.create_table('source_archives',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('model_version_id', sa.Uuid(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['model_version_id'], ['bronze.model_versions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('model_version_id', 'filename'),
    sa.UniqueConstraint('model_version_id', 'sha256'),
    sa.UniqueConstraint('path'),
    schema='bronze'
    )
    op.create_table('history',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('model_version_id', sa.Uuid(), nullable=False),
    sa.Column('dataset_version_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['dataset_version_id'], ['bronze.dataset_versions.id'], ),
    sa.ForeignKeyConstraint(['model_version_id'], ['bronze.model_versions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='bronze'
    )
    op.create_table('model_datasets',
    sa.Column('model_version_id', sa.Uuid(), nullable=False),
    sa.Column('dataset_id', sa.Uuid(), nullable=False),
    sa.Column('dataset_version_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['bronze.datasets.id'], ),
    sa.ForeignKeyConstraint(['dataset_version_id'], ['bronze.dataset_versions.id'], ),
    sa.ForeignKeyConstraint(['model_version_id'], ['bronze.model_versions.id'], ),
    sa.PrimaryKeyConstraint('model_version_id', 'dataset_id'),
    schema='bronze'
    )
    op.create_table('preparation_files',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('model_version_id', sa.Uuid(), nullable=False),
    sa.Column('dataset_name', sa.String(length=120), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('format', sa.String(length=3), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=False),
    sa.Column('contract_mode', sa.String(length=16), server_default='generate', nullable=False),
    sa.Column('contract_ref', sa.String(length=120), nullable=True),
    sa.Column('loaded_yaml', sa.Text(), nullable=True),
    sa.Column('saved_yaml', sa.Text(), nullable=True),
    sa.Column('sql_choices', postgresql.JSONB(astext_type=Text()), nullable=True),
    sa.Column('revision', sa.Integer(), server_default='0', nullable=False),
    sa.Column('summary', postgresql.JSONB(astext_type=Text()), nullable=True),
    sa.Column('report', sa.Text(), nullable=True),
    sa.Column('table_specs', postgresql.JSONB(astext_type=Text()), nullable=True),
    sa.Column('types_catalog', postgresql.JSONB(astext_type=Text()), nullable=True),
    sa.Column('technical_columns', postgresql.JSONB(astext_type=Text()), server_default='[]', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("contract_mode IN ('existing', 'generate')", name='ck_preparation_contract_mode'),
    sa.ForeignKeyConstraint(['model_version_id'], ['bronze.preparations.model_version_id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('model_version_id', 'dataset_name'),
    sa.UniqueConstraint('model_version_id', 'sha256'),
    schema='bronze'
    )
    op.create_table('rows',
    sa.Column('dataset_version_id', sa.Uuid(), nullable=False),
    sa.Column('table_name', sa.Text(), nullable=False),
    sa.Column('row_number', sa.Integer(), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=Text()), nullable=False),
    sa.ForeignKeyConstraint(['dataset_version_id'], ['bronze.dataset_versions.id'], ),
    sa.PrimaryKeyConstraint('dataset_version_id', 'table_name', 'row_number'),
    schema='bronze'
    )
    op.create_table('contracts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('model_version_id', sa.Uuid(), nullable=False),
    sa.Column('dataset_version_id', sa.Uuid(), nullable=False),
    sa.Column('table_name', sa.Text(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('yaml', sa.Text(), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=Text()), nullable=False),
    sa.Column('columns', postgresql.JSONB(astext_type=Text()), nullable=False),
    sa.Column('types_catalog', postgresql.JSONB(astext_type=Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['dataset_version_id'], ['bronze.dataset_versions.id'], ),
    sa.ForeignKeyConstraint(['model_version_id'], ['bronze.model_versions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('model_version_id', 'dataset_version_id', 'table_name', 'number'),
    schema='silver'
    )
    op.create_table('runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('model_version_id', sa.Uuid(), nullable=False),
    sa.Column('dataset_version_id', sa.Uuid(), nullable=False),
    sa.Column('table_name', sa.Text(), nullable=False),
    sa.Column('contract_id', sa.Uuid(), nullable=False),
    sa.Column('columns', postgresql.JSONB(astext_type=Text()), nullable=False),
    sa.Column('source_rows', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['contract_id'], ['silver.contracts.id'], ),
    sa.ForeignKeyConstraint(['dataset_version_id'], ['bronze.dataset_versions.id'], ),
    sa.ForeignKeyConstraint(['model_version_id'], ['bronze.model_versions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('contract_id'),
    schema='silver'
    )
    op.create_index('ix_silver_runs_version', 'runs', ['model_version_id'], unique=False, schema='silver')
    op.create_table('quarantine',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('row_number', sa.Integer(), nullable=False),
    sa.Column('source', postgresql.JSONB(astext_type=Text()), nullable=False),
    sa.Column('candidate', postgresql.JSONB(astext_type=Text()), nullable=False),
    sa.Column('errors', postgresql.JSONB(astext_type=Text()), nullable=False),
    sa.Column('state', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("state IN ('pending', 'reintegrated', 'discarded')", name='ck_quarantine_state'),
    sa.ForeignKeyConstraint(['run_id'], ['silver.runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'row_number'),
    schema='silver'
    )
    op.create_index('ix_quarantine_pending', 'quarantine', ['run_id'], unique=False, schema='silver', postgresql_where=sa.text("state = 'pending'"))
    op.create_table('rows',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('row_number', sa.Integer(), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=Text()), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['silver.runs.id'], ),
    sa.PrimaryKeyConstraint('run_id', 'row_number'),
    schema='silver'
    )

def downgrade():
    raise RuntimeError("Le catalogue et ses historiques ne sont pas supprimés automatiquement")

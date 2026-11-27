from alembic import context
from indusense_api.catalog import metadata
from indusense_api.database import create_database_engine, database_url

if context.is_offline_mode():
    context.configure(
        url=database_url(),
        target_metadata=metadata,
        literal_binds=True,
        version_table_schema="bronze",
        include_schemas=True,
    )
    with context.begin_transaction():
        context.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        context.run_migrations()
else:
    engine = create_database_engine()
    with engine.begin() as connection:
        # Le verrou sérialise les migrations de plusieurs démarrages simultanés.
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(741953280)")
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS bronze")
        context.configure(
            connection=connection,
            target_metadata=metadata,
            version_table_schema="bronze",
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()

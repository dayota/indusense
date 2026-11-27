"""Adaptateur CLI et composition des ports Bronze v2."""
import hashlib
import json
import os
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import sqlalchemy as sa
import typer

app = typer.Typer(no_args_is_help=True)
bronze = typer.Typer(no_args_is_help=True)
app.add_typer(bronze, name="bronze")


def configuration(root, files):
    from .bronze_contracts import parse_contracts, validate_or_raise
    from .bronze_sources import FilesystemSourceInspector
    paths = files or sorted((root / "config/bronze").glob("*.yml"))
    if not paths: raise ValueError("Aucun contrat Bronze v2 trouvé")
    configs, recipes = [], []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        values = parse_contracts(text)
        configs.extend(values)
        recipes.extend([hashlib.sha256(text.encode()).hexdigest()] * len(values))
    inspector = FilesystemSourceInspector(root)
    validate_or_raise(configs, root, inspector)
    return configs, recipes, inspector


@bronze.command("validate")
def validate(root: Path = Path("."), files: Annotated[list[Path] | None, typer.Argument()] = None):
    try:
        configs, _, _ = configuration(root.resolve(), files)
        typer.echo(f"{len(configs)} configurations Bronze v2 valides")
    except (ValueError, OSError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None


@bronze.command("plan")
def plan(root: Path = Path("."), files: Annotated[list[Path] | None, typer.Argument()] = None):
    from .bronze_engine import migration_script
    try:
        root = root.resolve()
        configs, recipes, _ = configuration(root, files)
        script = migration_script(configs)
        digest = hashlib.sha256(json.dumps({"recipes": recipes, "script": script}, sort_keys=True).encode()).hexdigest()
        directory = root / "artifacts/bronze/migrations"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (digest + ".py")
        path.write_text(script, encoding="utf-8")
        typer.echo(f"Migration à relire : {path}\nSHA-256 de revue : {digest}")
    except (ValueError, OSError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None


@bronze.command("load")
def load(database: Annotated[str, typer.Option(help="Base de destination dédiée, existante et vide à la première exécution")],
         approved_plan_sha256: Annotated[str, typer.Option(help="Empreinte du plan relu et approuvé")],
         root: Path = Path("."), files: Annotated[list[Path] | None, typer.Argument()] = None):
    from .bronze_engine import migration_script, apply_migration, load_configuration, write_artifacts, IngestionFailure
    engines = []
    try:
        root = root.resolve()
        configs, recipes, inspector = configuration(root, files)
        script = migration_script(configs)
        digest = hashlib.sha256(json.dumps({"recipes": recipes, "script": script}, sort_keys=True).encode()).hexdigest()
        reviewed = root / "artifacts/bronze/migrations" / (digest + ".py")
        if approved_plan_sha256 != digest or not reviewed.is_file() or reviewed.read_text() != script:
            raise ValueError("Génère le plan et fournis son empreinte après revue humaine")
        url = sa.URL.create("postgresql+psycopg", username=os.getenv("DB_USER", "indusense_user"),
            password=os.getenv("DB_PASSWORD", "dbpassword"), host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "5432")), database=os.getenv("DB_NAME", "indusense_db"))
        catalog = sa.create_engine(url)
        target = sa.create_engine(url.set(database=database))
        engines = [catalog, target]
        # Registre existant créé par les migrations du catalogue, jamais de DDL implicite.
        journal = sa.Table("ingestion_batches_log", sa.MetaData(schema="bronze"), autoload_with=catalog)
        with target.begin() as connection:
            apply_migration(connection, configs)
        failed = False
        for config, recipe in zip(configs, recipes):
            from .bronze_engine import fingerprint
            from .bronze_sources import source_spec
            batch_id = uuid4()
            with catalog.begin() as connection:
                connection.execute(journal.insert().values(batch_id=batch_id, source_name=config["source"]["path"],
                    source_format=config["source"]["format"], target_table=config["target"]["table"],
                    source_hash=fingerprint(inspector.path(source_spec(config))), config_hash=recipe, status="RUNNING"))
            try:
                report, dictionary = load_configuration(target, inspector, config, recipe, batch_id)
            except IngestionFailure as error:
                report, dictionary, failed = error.report, error.dictionary, True
            with catalog.begin() as connection:
                connection.execute(journal.update().where(journal.c.batch_id == batch_id).values(status=report["status"],
                    records_read=report["records_read"], records_inserted=report["records_inserted"],
                    records_rejected=report["records_rejected"], report=report, dictionary=dictionary, completed_at=sa.func.now()))
            path = write_artifacts(root, report, dictionary)
            with catalog.begin() as connection:
                connection.execute(journal.update().where(journal.c.batch_id == batch_id).values(artifact_path=path))
            typer.echo(f"{config['target']['table']}: {report['status']} ({report['records_read']} lues, {report['records_inserted']} insérées)")
        if failed: raise typer.Exit(1)
    except (ValueError, OSError, sa.exc.SQLAlchemyError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None
    finally:
        for engine in engines: engine.dispose()


if __name__ == "__main__":
    app()

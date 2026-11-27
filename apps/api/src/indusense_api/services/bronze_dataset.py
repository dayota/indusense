"""Création du Bronze dédié, résolution des erreurs et ouverture automatique de Silver."""
import tempfile
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from indusense_ingestion.bronze import validate_plan

from .. import catalog as db
from ..schemas import UploadEntry
from . import bronze_storage as storage
from .analysis import analyze
from .preparation import editable, exact_files, files_for, materialize, public_file
from .workflow import locked_version, record


def finish(connection, version_id):
    preparation = connection.execute(select(db.preparations).where(db.preparations.c.model_version_id == version_id)).mappings().one()
    if preparation["state"] == "complete": return
    connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version_id).values(state="complete"))
    version = connection.execute(select(db.model_versions).where(db.model_versions.c.id == version_id)).mappings().one()
    if version["status"] == "ingestion-bronze":
        connection.execute(db.model_versions.update().where(db.model_versions.c.id == version_id).values(status="ingestion-silver"))
        record(connection, version_id, "stage_validated", {"stage": "bronze"})
        record(connection, version_id, "status_changed", {"from_status": "ingestion-bronze", "to_status": "ingestion-silver"})


def workspace(engine, version_id):
    with engine.connect() as connection:
        version = connection.execute(select(db.model_versions).where(db.model_versions.c.id == version_id)).mappings().first()
        if version is None: raise HTTPException(404, "Version du modèle introuvable")
        preparation = connection.execute(select(db.preparations).where(db.preparations.c.model_version_id == version_id)).mappings().first()
        files = files_for(connection, version_id, include_content=False)
    state = dict(preparation) if preparation else {"state": "draft", "database_name": None, "identities_reviewed": False}
    result = {**state, "files": [public_file(file) for file in files],
              "readonly": state["state"] != "draft" or version["status"] != "ingestion-bronze",
              "dataset": None, "status": version["status"]}
    if state["database_name"]:
        target = storage.version_engine(engine, state["database_name"])
        try:
            with target.connect() as connection:
                result["dataset"] = storage.summary(connection)
            # Réconcilier un commit des données réussi suivi d’une interruption du catalogue.
            if state["state"] == "created" and result["dataset"]["pending"] == 0 and not version["read_only"]:
                with engine.begin() as connection:
                    locked_version(connection, version_id)
                    finish(connection, version_id)
                result["state"], result["status"] = "complete", "ingestion-silver"
        finally:
            target.dispose()
    return result


def create(engine, version_id, data, root):
    with engine.begin() as connection, tempfile.TemporaryDirectory(prefix="indusense-bronze-") as folder:
        version = editable(connection, version_id)
        preparation = connection.execute(select(db.preparations).where(db.preparations.c.model_version_id == version_id)).mappings().one()
        if not preparation["identities_reviewed"]:
            raise HTTPException(409, "Valide les cartes d’identité avec Suivant avant de créer le Bronze.")
        files = exact_files(connection, version_id, data.files)
        model = connection.execute(select(db.models).where(db.models.c.id == version["model_id"])).mappings().one()
        name = storage.database_name(model["name"], version["number"])
        batches, targets = [], set()
        for index, requested in enumerate(data.files):
            file = files[requested.id]
            if file["saved_yaml"] is None or requested.revision != file["revision"]:
                raise HTTPException(409, "Les contrats sauvegardés ont changé. Recharge la préparation.")
            work = Path(folder) / str(index)
            source = materialize(file, work)
            entry = UploadEntry(dataset_name=file["dataset_name"], contract_yaml=file["saved_yaml"] if file["format"] == "csv" else None)
            analysis = analyze(source, entry, root, work)
            if analysis["types_catalog"] != file["types_catalog"]:
                raise HTTPException(409, "Le catalogue des types a changé. Recharge et sauvegarde les contrats.")
            technical = [column.model_dump() for column in requested.technical_columns]
            if any(column["table"] not in file["table_specs"] for column in technical):
                raise HTTPException(422, "Une colonne technique référence une table source inconnue.")
            plans = []
            for table, columns in file["table_specs"].items():
                chosen = [column for column in technical if column["table"] == table]
                _, output = validate_plan(columns, chosen, file["types_catalog"]["types"])
                target_name = storage.normalized_name(file["dataset_name"] if file["format"] == "csv" else f"{file['dataset_name']}_{table}")
                if target_name in targets:
                    raise HTTPException(422, "Deux fichiers produisent le même nom de table Bronze. Choisis des noms de datasets distincts.")
                targets.add(target_name)
                plans.append({"source": table, "target": target_name, "columns": columns, "technical": chosen, "output": output})
            batches.append((file, plans, analysis["tables"], technical))
        # Aucune création de base avant la fin des contrôles de tous les fichiers.
        storage.create_database(engine, name)
        target = storage.version_engine(engine, name)
        try:
            try:
                with target.begin() as destination:
                    destination.exec_driver_sql("CREATE SCHEMA bronze")
                    storage.storage.create_all(destination)
                    for file, plans, tables, technical in batches:
                        destination.execute(storage.files_table.insert().values(id=file["id"], filename=file["filename"], sha256=file["sha256"],
                                            plans=plans, types_catalog=file["types_catalog"]))
                        for plan in plans:
                            storage.insert_records(destination, file, plan, tables[plan["source"]])
                    result = storage.summary(destination)
            except SQLAlchemyError:
                # CREATE DATABASE ne peut pas appartenir à la transaction du catalogue.
                # La base n’est jamais supprimée ou remplacée en cas d’interruption.
                raise HTTPException(503, f"La base « {name} » a été créée mais le traitement a échoué. Crée une nouvelle version du modèle avant de recommencer.") from None
        finally:
            target.dispose()
        connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version_id).values(database_name=name, state="created"))
        for file, plans, tables, technical in batches:
            connection.execute(db.preparation_files.update().where(db.preparation_files.c.id == file["id"]).values(technical_columns=technical))
        record(connection, version_id, "bronze_dataset_created", {"database": name, "valid_rows": result["valid"], "pending_rows": result["pending"]})
        if result["pending"] == 0:
            finish(connection, version_id)
    return workspace(engine, version_id)


def destination_name(connection, version_id):
    preparation = connection.execute(select(db.preparations).where(db.preparations.c.model_version_id == version_id)).mappings().first()
    if preparation is None or not preparation["database_name"]:
        raise HTTPException(409, "Crée le Bronze dataset avant de consulter ses données ou ses erreurs.")
    return preparation


def errors(engine, version_id, state, offset, limit):
    with engine.connect() as connection:
        preparation = destination_name(connection, version_id)
    target = storage.version_engine(engine, preparation["database_name"])
    try:
        with target.connect() as connection:
            conditions = [] if state == "all" else [storage.quarantine.c.state == state]
            total = connection.scalar(select(func.count()).select_from(storage.quarantine).where(*conditions))
            rows = connection.execute(select(storage.quarantine, storage.files_table.c.filename)
                                      .select_from(storage.quarantine.join(storage.files_table, storage.quarantine.c.file_id == storage.files_table.c.id))
                                      .where(*conditions).order_by(storage.files_table.c.filename, storage.quarantine.c.source_table,
                                                                  storage.quarantine.c.row_number, storage.quarantine.c.id)
                                      .offset(offset).limit(limit)).mappings().all()
        return {"rows": [dict(row) for row in rows], "total": total}
    finally:
        target.dispose()


def resolve(engine, version_id, issue_id, data):
    with engine.begin() as connection:
        version = locked_version(connection, version_id)
        preparation = destination_name(connection, version_id)
        if preparation["state"] != "created" or version["status"] != "ingestion-bronze":
            raise HTTPException(409, "La table tampon est résolue et cette version est en consultation seule.")
        target = storage.version_engine(engine, preparation["database_name"])
        try:
            with target.begin() as destination:
                result = storage.resolve_row(destination, issue_id, data)
                pending = destination.scalar(select(func.count()).select_from(storage.quarantine).where(storage.quarantine.c.state == "pending"))
        finally:
            target.dispose()
        if result["resolved"]:
            record(connection, version_id, "bronze_row_resolved", {"issue_id": str(issue_id), "row_number": result["row_number"],
                    "table": result["source_table"], "decision": result["state"], "reason": data.reason})
            if pending == 0:
                finish(connection, version_id)
    return result


def preview(engine, version_id, table, offset, limit):
    with engine.connect() as connection:
        preparation = destination_name(connection, version_id)
    target = storage.version_engine(engine, preparation["database_name"])
    try:
        with target.connect() as connection:
            definitions = connection.execute(select(storage.files_table.c.plans)).scalars().all()
            if not any(plan["target"] == table for plans in definitions for plan in plans):
                raise HTTPException(404, "Table Bronze introuvable")
            rows = connection.execute(select(storage.lineage.c.row_number, storage.lineage.c.data)
                                      .where(storage.lineage.c.target_table == table, storage.lineage.c.state == "valid")
                                      .order_by(storage.lineage.c.file_id, storage.lineage.c.source_table, storage.lineage.c.row_number)
                                      .offset(offset).limit(limit)).mappings().all()
        return {"rows": [dict(row) for row in rows]}
    finally:
        target.dispose()

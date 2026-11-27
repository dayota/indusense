"""Durable execution queue; PostgreSQL guards serialize workers and make restart replay safe."""
from uuid import uuid4
import logging

import sqlalchemy as sa
from fastapi import HTTPException

from .. import catalog as db
from ..schemas import PreparationCreate
from . import bronze_v2, model_database
from .preparation import exact_files
from .workflow import locked_version

logger = logging.getLogger(__name__)


def current(engine, version_id):
    with engine.connect() as connection:
        row = connection.execute(sa.select(db.bronze_executions).where(db.bronze_executions.c.model_version_id == version_id)
            .order_by(db.bronze_executions.c.created_at.desc()).limit(1)).mappings().first()
        return {key: value for key, value in row.items() if key != "body"} if row else None


def enqueue(engine, version_id, data):
    with engine.begin() as connection:
        version = locked_version(connection, version_id)
        if version["status"] != "ingestion-bronze": raise HTTPException(409, "Bronze est déjà validé")
        active = connection.execute(sa.select(db.bronze_executions).where(db.bronze_executions.c.model_version_id == version_id,
            db.bronze_executions.c.status.in_(["QUEUED", "RUNNING"]))).mappings().first()
        if active: return active["id"]
        prep = connection.execute(sa.select(db.preparations).where(db.preparations.c.model_version_id == version_id)).mappings().one()
        if prep["protocol"] != 2 or not prep["migration"] or prep["approved_hash"] != prep["migration"]["hash"]:
            raise HTTPException(409, "Une migration approuvée est requise")
        files = exact_files(connection, version_id, data.files)
        if any(files[item.id]["revision"] != item.revision for item in data.files):
            raise HTTPException(409, "Les contrats ont changé")
        execution_id = uuid4()
        connection.execute(db.bronze_executions.insert().values(id=execution_id, model_version_id=version_id,
            status="QUEUED", phase="En attente du chargement", body=data.model_dump(mode="json")))
        return execution_id


def run(engine, root, execution_id):
    with engine.connect() as guard:
        acquired = guard.scalar(sa.text("SELECT pg_try_advisory_lock(hashtextextended(:id, 0))"), {"id": "execution:" + str(execution_id)})
        guard.commit()
        if not acquired: return
        try:
            with engine.connect() as connection:
                row = connection.execute(sa.select(db.bronze_executions).where(db.bronze_executions.c.id == execution_id)).mappings().one()
            if row["status"] not in ("QUEUED", "RUNNING"): return
            version_id = row["model_version_id"]

            def update(phase, status="RUNNING", error=None):
                values = {"phase": phase, "status": status, "error": error}
                if status in ("SUCCESS", "FAILED"): values["completed_at"] = sa.func.now()
                with engine.begin() as connection:
                    connection.execute(db.bronze_executions.update().where(db.bronze_executions.c.id == execution_id).values(**values))

            try:
                update("Vérification de la préparation")
                state = bronze_v2.create(engine, version_id, PreparationCreate.model_validate(row["body"]), root, update)
                failed = not state["data_ready"]
                update("Ingestion terminée avec des erreurs" if failed else "Ingestion et rapports terminés",
                       "FAILED" if failed else "SUCCESS", "Un ou plusieurs lots ou rapports sont incomplets" if failed else None)
            except Exception as error:
                logger.exception("Bronze execution %s failed", execution_id)
                message = error.detail if isinstance(error, HTTPException) else str(error)
                update("Échec du traitement", "FAILED", str(message))
            finally:
                try: model_database.synchronize(engine, version_id)
                except Exception:
                    logger.exception("Model history synchronization failed; control journal retained")
                    update("Échec de la synchronisation de l'historique", "FAILED", "Les données sont conservées ; rejoue pour synchroniser l'historique du modèle")
        finally:
            guard.execute(sa.text("SELECT pg_advisory_unlock(hashtextextended(:id, 0))"), {"id": "execution:" + str(execution_id)})
            guard.commit()


def resume(engine, root, executor):
    with engine.connect() as connection:
        pending = connection.scalars(sa.select(db.bronze_executions.c.id).where(db.bronze_executions.c.status.in_(["QUEUED", "RUNNING"]))).all()
    for execution_id in pending:
        executor.submit(run, engine, root, execution_id)

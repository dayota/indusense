from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from .. import catalog as db
from ..schemas import SilverContractInput, SilverPrepareInput, SilverResolutionInput
from ..services import silver

router = APIRouter(prefix="/api/model-versions/{version_id}/silver", tags=["silver"])


@router.get("")
def workspace(version_id: UUID, request: Request):
    return silver.workspace(request.app.state.engine, version_id)


@router.get("/contracts/{snapshot_id}")
def contract(version_id: UUID, snapshot_id: UUID, request: Request, table: str = "data"):
    return silver.contract_editor(request.app.state.engine, version_id, snapshot_id, table)


@router.post("/contracts/{snapshot_id}/validate")
def validate_contract(version_id: UUID, snapshot_id: UUID, data: SilverContractInput, request: Request, table: str = "data"):
    return silver.save_contract(request.app.state.engine, version_id, snapshot_id, table, data, save=False)


@router.post("/contracts/{snapshot_id}", status_code=201)
def save_contract(version_id: UUID, snapshot_id: UUID, data: SilverContractInput, request: Request, table: str = "data"):
    return silver.save_contract(request.app.state.engine, version_id, snapshot_id, table, data, save=True)


@router.post("/prepare/{snapshot_id}")
def prepare(version_id: UUID, snapshot_id: UUID, data: SilverPrepareInput, request: Request, table: str = "data"):
    return silver.prepare(request.app.state.engine, version_id, snapshot_id, table, data.contract_id)


@router.get("/runs/{run_id}/rows")
def rows(version_id: UUID, run_id: UUID, request: Request,
         offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    with request.app.state.engine.connect() as connection:
        if not connection.scalar(select(db.silver_runs.c.id).where(db.silver_runs.c.id == run_id, db.silver_runs.c.model_version_id == version_id)):
            raise HTTPException(404, "Exécution silver introuvable pour cette version")
        records = connection.execute(select(db.silver_rows.c.row_number, db.silver_rows.c.data)
                                     .where(db.silver_rows.c.run_id == run_id).order_by(db.silver_rows.c.row_number)
                                     .offset(offset).limit(limit)).mappings().all()
    return {"rows": [dict(row) for row in records], "offset": offset}


@router.get("/quarantine")
def quarantine(version_id: UUID, request: Request, state: Literal["pending", "reintegrated", "discarded", "all"] = "pending",
               offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    with request.app.state.engine.connect() as connection:
        if not connection.scalar(select(db.model_versions.c.id).where(db.model_versions.c.id == version_id)):
            raise HTTPException(404, "Version introuvable")
        condition = [db.silver_runs.c.model_version_id == version_id]
        if state != "all":
            condition.append(db.quarantine.c.state == state)
        joined = db.quarantine.join(db.silver_runs).join(db.dataset_versions, db.silver_runs.c.dataset_version_id == db.dataset_versions.c.id)
        total = connection.scalar(select(func.count()).select_from(joined).where(*condition))
        records = connection.execute(select(db.quarantine, db.silver_runs.c.table_name, db.dataset_versions.c.filename)
                                     .select_from(joined).where(*condition)
                                     .order_by(db.quarantine.c.created_at, db.quarantine.c.id).offset(offset).limit(limit)).mappings().all()
    return {"rows": [dict(row) for row in records], "total": total, "offset": offset}


@router.post("/quarantine/{issue_id}/resolve")
def resolve(version_id: UUID, issue_id: UUID, data: SilverResolutionInput, request: Request):
    return silver.resolve(request.app.state.engine, version_id, issue_id, data)

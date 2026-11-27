import csv
import tempfile
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from sqlglot.errors import SqlglotError
from yaml import YAMLError

from ..schemas import PreparationContractLoad, PreparationContractSave, PreparationCreate, SilverResolutionInput, MigrationApproval, SqlInspectionInput
from ..services import preparation, bronze_dataset, bronze_v2, source_archive, bronze_execution
from .. import catalog as db
from sqlalchemy import select
from ..services.analysis import MAX_BODY_BYTES, MAX_FILES, MAX_MANIFEST_BYTES
from .workflow import receive_batch, upload_entries
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/model-versions/{version_id}/bronze", tags=["préparation bronze"])


def invalid(error):
    return HTTPException(422, f"Préparation refusée : {error}")


@router.get("")
def workspace(version_id: UUID, request: Request):
    engine = request.app.state.engine
    with engine.connect() as connection:
        protocol = connection.scalar(select(db.preparations.c.protocol).where(db.preparations.c.model_version_id == version_id))
    if protocol == 1:
        result = bronze_dataset.workspace(engine, version_id)
        return {**result, "protocol": 1, "readonly": True}
    return bronze_v2.workspace(engine, version_id)


@router.get("/contracts/catalogue")
def contract_catalogue(version_id: UUID, request: Request):
    return bronze_v2.contract_catalog(request.app.state.engine, request.app.state.resource_root, version_id)


@router.post("/contracts/editor")
def contract_editor(version_id: UUID, data: PreparationContractLoad, request: Request):
    try:
        return bronze_v2.contract_editor(request.app.state.engine, version_id, data, request.app.state.resource_root)
    except (ValueError, TypeError, LookupError, SqlglotError, YAMLError, csv.Error) as error:
        raise invalid(error) from None
    except OSError:
        raise HTTPException(503, "Lecture des contrats locaux impossible") from None


@router.get("/contracts/schema")
def contract_schema(version_id: UUID, request: Request):
    try:
        return bronze_v2.contract_schema(request.app.state.resource_root)
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Schéma de contrat Bronze absent ou invalide") from None


@router.post("/files", max_body_size=MAX_BODY_BYTES,
             form_limits={"max_files": MAX_FILES, "max_fields": 1, "max_part_size": MAX_MANIFEST_BYTES})
def upload(version_id: UUID, request: Request, files: Annotated[list[UploadFile], File()], manifest: Annotated[str, Form()]):
    entries = upload_entries(files, manifest)
    try:
        with tempfile.TemporaryDirectory(prefix="indusense-stage-") as directory:
            prepared = receive_batch(files, entries, Path(directory))
            return preparation.upload(request.app.state.engine, version_id, prepared, entries, request.app.state.resource_root)
    except (ValueError, TypeError, csv.Error) as error:
        raise invalid(error) from None
    except OSError:
        raise HTTPException(503, "Archivage impossible dans datas/ingestion. Vérifie le montage et les droits du dossier puis réessaie.") from None


@router.post("/files/archive")
def archive_files(version_id: UUID, request: Request):
    try:
        return preparation.archive_files(request.app.state.engine, version_id, request.app.state.resource_root)
    except OSError:
        raise HTTPException(503, "Archivage impossible dans datas/ingestion. Vérifie les droits du dossier.") from None


@router.get("/files/{file_id}/preview")
def file_preview(version_id: UUID, file_id: UUID, request: Request,
                 encoding: Literal["utf-8", "cp1252", "latin-1"] = "utf-8"):
    return source_archive.preview(request.app.state.engine, version_id, file_id, request.app.state.resource_root, encoding)


@router.get("/files/{file_id}/download")
def file_download(version_id: UUID, file_id: UUID, request: Request):
    from urllib.parse import quote
    archive = source_archive.get(request.app.state.engine, version_id, file_id)
    stream = source_archive.open_original(request.app.state.resource_root, archive)
    def chunks():
        try:
            while content := stream.read(256 * 1024): yield content
        finally:
            stream.close()
    return StreamingResponse(chunks(), media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(archive["filename"], safe=""),
                 "Content-Length": str(archive["size_bytes"])})


@router.delete("/files/{file_id}")
def remove_file(version_id: UUID, file_id: UUID, request: Request):
    return preparation.remove_file(request.app.state.engine, version_id, file_id)


@router.post("/files/{file_id}/inspect-sql")
def inspect_sql(version_id: UUID, file_id: UUID, data: SqlInspectionInput, request: Request):
    try:
        return bronze_v2.inspect_sql(request.app.state.engine, version_id, file_id, data.encoding, request.app.state.resource_root)
    except (ValueError, TypeError, LookupError, SqlglotError, UnicodeError) as error:
        raise invalid(error) from None


@router.post("/contracts/load")
def load_contracts(version_id: UUID, data: PreparationContractLoad, request: Request):
    try:
        return bronze_v2.load_contracts(request.app.state.engine, version_id, data, request.app.state.resource_root)
    except (ValueError, TypeError, SqlglotError, YAMLError, csv.Error) as error:
        raise invalid(error) from None


@router.post("/contracts/save", max_body_size=MAX_MANIFEST_BYTES * 6)
def save_contracts(version_id: UUID, data: PreparationContractSave, request: Request):
    try:
        return bronze_v2.save_contracts(request.app.state.engine, version_id, data, request.app.state.resource_root)
    except (ValueError, TypeError, SqlglotError, YAMLError, csv.Error) as error:
        raise invalid(error) from None
    except OSError:
        raise HTTPException(503, "Écriture des contrats impossible dans _contracts. Vérifie les droits puis réessaie.") from None


@router.post('/identities/generate')
def generate_identities(version_id: UUID, request: Request):
    try:
        return bronze_v2.generate_identities(request.app.state.engine, version_id, request.app.state.resource_root)
    except (ValueError, TypeError, LookupError, SqlglotError, YAMLError, csv.Error) as error:
        raise invalid(error) from None
    except OSError:
        raise HTTPException(503, 'Génération ou écriture des cartes d’identité impossible') from None


@router.post("/identities/confirm")
def confirm_identities(version_id: UUID, request: Request):
    return preparation.confirm_identities(request.app.state.engine, version_id)


@router.post("/create", max_body_size=MAX_MANIFEST_BYTES * 6)
def create(version_id: UUID, data: PreparationCreate, request: Request):
    execution = bronze_execution.current(request.app.state.engine, version_id)
    if execution and execution['status'] in ('QUEUED', 'RUNNING'):
        raise HTTPException(409, "Un chargement est déjà en cours : consulte son suivi")
    try:
        return bronze_v2.create(request.app.state.engine, version_id, data, request.app.state.resource_root)
    except (ValueError, TypeError, SqlglotError, YAMLError, csv.Error) as error:
        raise invalid(error) from None
    except OSError:
        raise HTTPException(503, "Publication des rapports impossible. Les données et journaux sont conservés ; vérifie le stockage puis rejoue l'ingestion.") from None


@router.post("/executions", status_code=202)
def start_execution(version_id: UUID, data: PreparationCreate, request: Request):
    execution_id = bronze_execution.enqueue(request.app.state.engine, version_id, data)
    request.app.state.bronze_executor.submit(bronze_execution.run, request.app.state.engine, request.app.state.resource_root, execution_id)
    return {"id": execution_id}


@router.get("/executions/current")
def current_execution(version_id: UUID, request: Request):
    return bronze_execution.current(request.app.state.engine, version_id)


@router.get("/errors")
def errors(version_id: UUID, request: Request, state: Literal["pending", "reintegrated", "discarded", "all"] = "pending",
           offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    with request.app.state.engine.connect() as connection:
        protocol = connection.scalar(select(db.preparations.c.protocol).where(db.preparations.c.model_version_id == version_id))
    if protocol == 2:
        return {"rows": [], "total": 0}
    return bronze_dataset.errors(request.app.state.engine, version_id, state, offset, limit)


@router.post("/errors/{issue_id}/resolve")
def resolve(version_id: UUID, issue_id: UUID, data: SilverResolutionInput, request: Request):
    raise HTTPException(409, "Bronze est immuable : les corrections sont réalisées en Silver. Les anciennes versions restent en consultation.")


@router.get("/rows")
def preview(version_id: UUID, request: Request, table: str,
            offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    with request.app.state.engine.connect() as connection:
        protocol = connection.scalar(select(db.preparations.c.protocol).where(db.preparations.c.model_version_id == version_id))
    if protocol == 1:
        return bronze_dataset.preview(request.app.state.engine, version_id, table, offset, limit)
    return bronze_v2.preview(request.app.state.engine, version_id, table, offset, limit)


@router.post("/migrations/generate")
def generate_migration(version_id: UUID, request: Request):
    try:
        return bronze_v2.generate_migration(request.app.state.engine, version_id, request.app.state.resource_root)
    except (ValueError, TypeError, SqlglotError, YAMLError, csv.Error) as error:
        raise invalid(error) from None


@router.get("/schema")
def review_schema(version_id: UUID, request: Request):
    return bronze_v2.review_schema(request.app.state.engine, version_id)


@router.get("/schema/rows")
def review_schema_rows(version_id: UUID, request: Request, table: str,
                       offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    return bronze_v2.review_schema(request.app.state.engine, version_id, table, offset, limit)


@router.post("/migrations/approve")
def approve_migration(version_id: UUID, data: MigrationApproval, request: Request):
    try:
        return bronze_v2.approve_migration(request.app.state.engine, version_id, data.hash, request.app.state.resource_root)
    except (ValueError, TypeError, SqlglotError, YAMLError, csv.Error) as error:
        raise invalid(error) from None


@router.post("/validate")
def validate(version_id: UUID, request: Request):
    return bronze_v2.validate(request.app.state.engine, version_id)


@router.get("/export")
def export(version_id: UUID, request: Request):
    archive = bronze_v2.export(request.app.state.engine, version_id, request.app.state.resource_root)
    def chunks():
        try:
            while data := archive.read(256 * 1024): yield data
        finally:
            archive.close()
    return StreamingResponse(chunks(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="bronze-{version_id}.zip"'})

import csv
import tempfile
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlglot.errors import SqlglotError
from yaml import YAMLError
from indusense_ingestion.converter_catalog import build_converter_catalog
from indusense_ingestion.contracts import read_config
from indusense_ingestion.operations import operation_catalog

from .. import catalog as db
from ..schemas import ModelInput, UploadEntry, VersionInput, StageValidationInput
from ..services import workflow, preload as preloading
from ..services.analysis import MAX_BODY_BYTES, MAX_FILES, MAX_MANIFEST_BYTES, contract_paths, receive

router = APIRouter(prefix="/api", tags=["workflow"])


@router.get("/operations")
def operations(request: Request):
    try:
        return operation_catalog(request.app.state.resource_root)
    except (OSError, ValueError, KeyError, TypeError, YAMLError):
        raise HTTPException(503, 'Catalogue des opérations absent ou invalide') from None


@router.get("/converters")
def converters(request: Request):
    root = request.app.state.resource_root
    try:
        catalogue = read_config(root / "config/converters.yaml")
        expected = build_converter_catalog(root / "config/types.yaml")
    except (OSError, ValueError, TypeError, YAMLError):
        raise HTTPException(503, "Catalogue des convertisseurs invalide ou absent : exécute packages/ingestion/scripts/update_converters.py.") from None
    if catalogue != expected:
        raise HTTPException(503, "Catalogue des convertisseurs obsolète : exécute packages/ingestion/scripts/update_converters.py.")
    return catalogue


@router.get("/models")
def list_models(request: Request):
    with request.app.state.engine.connect() as connection:
        models = [
            dict(row)
            for row in connection.execute(
                select(db.models).order_by(db.models.c.created_at.desc())
            ).mappings()
        ]
        versions = (
            connection.execute(
                select(db.model_versions).order_by(db.model_versions.c.number.desc())
            )
            .mappings()
            .all()
        )
        for model in models:
            model["versions"] = [
                dict(row) for row in versions if row["model_id"] == model["id"]
            ]
    return models


@router.post("/models", status_code=201)
def create_model(data: ModelInput, request: Request):
    return workflow.create_model(request.app.state.engine, data)


@router.post("/models/{model_id}/versions", status_code=201)
def create_version(model_id: UUID, data: VersionInput, request: Request):
    return workflow.create_version(request.app.state.engine, model_id, data)


@router.get("/model-versions/{version_id}")
def version_detail(version_id: UUID, request: Request):
    with request.app.state.engine.connect() as connection:
        version = (
            connection.execute(
                select(db.model_versions).where(db.model_versions.c.id == version_id)
            )
            .mappings()
            .first()
        )
        if version is None:
            raise HTTPException(404, "Version du modèle introuvable")
        datasets = (
            connection.execute(
                select(
                    db.datasets.c.id,
                    db.datasets.c.name,
                    db.dataset_versions.c.id.label("snapshot_id"),
                    db.dataset_versions.c.number,
                    db.dataset_versions.c.filename,
                    db.dataset_versions.c.summary,
                    db.dataset_versions.c.created_at,
                    db.sources.c.sha256,
                )
                .select_from(
                    db.bindings.join(
                        db.datasets, db.bindings.c.dataset_id == db.datasets.c.id
                    )
                    .join(
                        db.dataset_versions,
                        db.bindings.c.dataset_version_id == db.dataset_versions.c.id,
                    )
                    .join(
                        db.sources, db.dataset_versions.c.source_id == db.sources.c.id
                    )
                )
                .where(
                    db.bindings.c.model_version_id == version_id,
                )
                .order_by(db.datasets.c.name)
            )
            .mappings()
            .all()
        )
        events = (
            connection.execute(
                select(db.history)
                .where(db.history.c.model_version_id == version_id)
                .order_by(db.history.c.id.desc())
                .limit(200)
            )
            .mappings()
            .all()
        )
        preparation = connection.execute(select(db.preparations).where(db.preparations.c.model_version_id == version_id)).mappings().first()
        preparation_summary = None
        if preparation:
            staged = connection.execute(select(db.preparation_files.c.summary).where(db.preparation_files.c.model_version_id == version_id)).scalars().all()
            preparation_summary = {"state": preparation["state"], "database_name": preparation["database_name"],
                                   "files": len(staged), "rows": sum(item["rows"] for item in staged if item)}
    return {
        **dict(version),
        "datasets": [dict(row) for row in datasets],
        "history": [dict(row) for row in events],
        "preparation": preparation_summary,
    }


@router.patch("/model-versions/{version_id}/status", include_in_schema=False)
def change_version_status(version_id: UUID):
    raise HTTPException(405, "Le statut ne peut pas être modifié manuellement. Valide l’étape dans l’espace de préparation.")


@router.post("/model-versions/{version_id}/validate-stage")
def validate_stage(version_id: UUID, data: StageValidationInput, request: Request):
    return workflow.validate_stage(request.app.state.engine, version_id, data.stage)


@router.get("/contracts")
def contracts(request: Request):
    return list(contract_paths(request.app.state.resource_root))


@router.get("/contracts/catalogue")
def contract_catalogue(request: Request):
    return preloading.contract_catalog(request.app.state.engine, request.app.state.resource_root)


def upload_entries(files, manifest):
    try:
        entries = TypeAdapter(list[UploadEntry]).validate_json(manifest)
    except ValidationError:
        raise HTTPException(422, "Manifeste JSON invalide") from None
    if not files or len(files) > MAX_FILES or len(entries) != len(files):
        raise HTTPException(422, "Fournir un manifeste par fichier, avec au maximum 10 fichiers")
    return entries


def receive_batch(files, entries, workspace):
    prepared = []
    for index, (file, entry) in enumerate(zip(files, entries)):
        folder = workspace / str(index)
        folder.mkdir()
        prepared.append(receive(file, folder, entry.sha256))
    return prepared


@router.post(
    "/model-versions/{version_id}/preload",
    max_body_size=MAX_BODY_BYTES,
    form_limits={"max_files": MAX_FILES, "max_fields": 1, "max_part_size": MAX_MANIFEST_BYTES},
)
def preload(
    version_id: UUID,
    request: Request,
    files: Annotated[list[UploadFile], File()],
    manifest: Annotated[str, Form(description="Liste JSON : dataset_name, contract_mode=existing|generate, contract, sha256 optionnel")],
):
    entries = upload_entries(files, manifest)
    try:
        with tempfile.TemporaryDirectory(prefix="indusense-preload-") as directory:
            workspace = Path(directory)
            prepared = receive_batch(files, entries, workspace)
            return preloading.preload(request.app.state.engine, version_id, prepared, entries,
                                      request.app.state.resource_root, workspace)
    except (ValueError, TypeError, SqlglotError, YAMLError, csv.Error) as error:
        raise HTTPException(422, f"Préchargement refusé : {error}. Aucun dataset bronze n’a été créé.") from None


@router.post(
    "/model-versions/{version_id}/uploads",
    max_body_size=MAX_BODY_BYTES,
    form_limits={"max_files": MAX_FILES, "max_fields": 1, "max_part_size": MAX_MANIFEST_BYTES},
)
def upload(
    version_id: UUID,
    request: Request,
    files: Annotated[list[UploadFile], File()],
    manifest: Annotated[
        str,
        Form(
            description="Liste JSON : dataset_name, contract CSV ou null, contract_yaml édité, sha256 optionnel, mode=snapshot"
        ),
    ],
):
    entries = upload_entries(files, manifest)
    try:
        with tempfile.TemporaryDirectory(prefix="indusense-upload-") as directory:
            workspace = Path(directory)
            # Finir les contrôles de taille et d’empreinte avant toute écriture en base.
            prepared = receive_batch(files, entries, workspace)
            return workflow.ingest(
                request.app.state.engine,
                version_id,
                prepared,
                entries,
                request.app.state.resource_root,
                workspace,
            )
    except (ValueError, TypeError, SqlglotError, YAMLError, csv.Error) as error:
        rejection = HTTPException(
            422, f"Lot refusé : {error}. Aucun fichier du lot n’a été importé."
        )
    except HTTPException as error:
        if error.status_code not in (409, 413, 422):
            raise
        rejection = error
    try:
        workflow.audit_rejection(
            request.app.state.engine, version_id, str(rejection.detail)
        )
    except SQLAlchemyError, HTTPException:
        pass
    raise rejection


@router.get("/datasets/{dataset_id}")
def dataset_history(dataset_id: UUID, request: Request):
    with request.app.state.engine.connect() as connection:
        dataset = (
            connection.execute(
                select(db.datasets).where(db.datasets.c.id == dataset_id)
            )
            .mappings()
            .first()
        )
        if dataset is None:
            raise HTTPException(404, "Dataset introuvable")
        versions = (
            connection.execute(
                select(
                    db.dataset_versions.c.id,
                    db.dataset_versions.c.number,
                    db.dataset_versions.c.filename,
                    db.dataset_versions.c.summary,
                    db.dataset_versions.c.created_at,
                    db.sources.c.sha256,
                )
                .join(db.sources)
                .where(db.dataset_versions.c.dataset_id == dataset_id)
                .order_by(db.dataset_versions.c.number.desc())
            )
            .mappings()
            .all()
        )
    return {**dict(dataset), "versions": [dict(row) for row in versions]}


@router.get("/dataset-versions/{snapshot_id}/report")
def report(snapshot_id: UUID, request: Request):
    with request.app.state.engine.connect() as connection:
        content = connection.scalar(
            select(db.dataset_versions.c.report).where(
                db.dataset_versions.c.id == snapshot_id
            )
        )
    if content is None:
        raise HTTPException(404, "Carte d’identité introuvable")
    return Response(
        content,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="identity-{snapshot_id}.md"'
        },
    )


@router.get("/dataset-versions/{snapshot_id}/rows")
def preview(
    snapshot_id: UUID,
    request: Request,
    table: str = "data",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    with request.app.state.engine.connect() as connection:
        snapshot = connection.execute(
            select(db.dataset_versions.c.summary).where(
                db.dataset_versions.c.id == snapshot_id
            )
        ).first()
        if snapshot is None:
            raise HTTPException(404, "Version du dataset introuvable")
        if table not in [entry["name"] for entry in snapshot.summary["tables"]]:
            raise HTTPException(404, "Table introuvable dans cette version")
        records = (
            connection.execute(
                select(db.rows.c.row_number, db.rows.c.data)
                .where(
                    db.rows.c.dataset_version_id == snapshot_id,
                    db.rows.c.table_name == table,
                )
                .order_by(db.rows.c.row_number)
                .offset(offset)
                .limit(limit)
            )
            .mappings()
            .all()
        )
    return {"table": table, "rows": [dict(row) for row in records], "offset": offset}

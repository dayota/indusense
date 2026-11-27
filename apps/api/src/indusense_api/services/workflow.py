from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from .. import catalog as db
from ..version_status import ModelVersionStatus
from .analysis import analyze
from .preload import resolve_contract


def record(connection, version_id, action, details, snapshot_id=None):
    connection.execute(
        db.history.insert().values(
            model_version_id=version_id,
            action=action,
            details=details,
            dataset_version_id=snapshot_id,
        )
    )


def locked_version(connection, version_id):
    version = (
        connection.execute(
            select(db.model_versions).where(db.model_versions.c.id == version_id)
        )
        .mappings()
        .first()
    )
    if version is None:
        raise HTTPException(404, "Version du modèle introuvable")
    if version["read_only"]:
        raise HTTPException(409, "Version antérieure à Bronze v2 : consultation seule. Crée une nouvelle version.")
    # Tous les chemins d’écriture prennent le même verrou, y compris la création d’une version.
    connection.execute(
        select(db.models.c.id)
        .where(db.models.c.id == version["model_id"])
        .with_for_update()
    ).one()
    # Relire après l’attente du verrou pour observer le dernier statut validé.
    return (
        connection.execute(
            select(db.model_versions).where(db.model_versions.c.id == version_id)
        )
        .mappings()
        .one()
    )


def create_model(engine, data):
    model_id, version_id = uuid4(), uuid4()
    with engine.begin() as connection:
        created = connection.execute(
            insert(db.models)
            .values(
                id=model_id,
                name=data.name,
                description=data.description,
            )
            .on_conflict_do_nothing(index_elements=[db.models.c.name])
            .returning(db.models.c.id)
        ).scalar_one_or_none()
        if created is None:
            raise HTTPException(409, "Un modèle porte déjà ce nom")
        connection.execute(
            db.model_versions.insert().values(
                id=version_id, model_id=model_id, number=1
            )
        )
        record(connection, version_id, "model_created", {"name": data.name})
        connection.execute(db.preparations.insert().values(model_version_id=version_id))
    return {
        "id": model_id,
        "version_id": version_id,
        "number": 1,
        "status": ModelVersionStatus.INGESTION_BRONZE.value,
    }


def create_version(engine, model_id, data):
    with engine.begin() as connection:
        model = connection.execute(
            select(db.models).where(db.models.c.id == model_id).with_for_update()
        ).first()
        if model is None:
            raise HTTPException(404, "Modèle introuvable")
        inherited = []
        if data.from_version_id:
            parent = connection.execute(
                select(db.model_versions).where(
                    db.model_versions.c.id == data.from_version_id,
                    db.model_versions.c.model_id == model_id,
                )
            ).first()
            if parent is None:
                raise HTTPException(
                    422, "La version de départ doit appartenir au même modèle"
                )
            inherited = (
                connection.execute(
                    select(db.bindings).where(
                        db.bindings.c.model_version_id == data.from_version_id
                    )
                )
                .mappings()
                .all()
            )
        number = (
            connection.scalar(
                select(func.max(db.model_versions.c.number)).where(
                    db.model_versions.c.model_id == model_id
                )
            )
            + 1
        )
        version_id = uuid4()
        connection.execute(
            db.model_versions.insert().values(
                id=version_id, model_id=model_id, number=number
            )
        )
        record(
            connection,
            version_id,
            "version_created",
            {
                "number": number,
                "from_version_id": str(data.from_version_id)
                if data.from_version_id
                else None,
            },
        )
        for binding in inherited:
            connection.execute(
                db.bindings.insert().values(
                    **{**binding, "model_version_id": version_id}
                )
            )
            record(
                connection,
                version_id,
                "dataset_reused",
                {"from_version_id": str(data.from_version_id)},
                binding["dataset_version_id"],
            )
        if data.from_version_id and data.preparation:
            from .preparation import clone_draft
            clone_draft(connection, data.from_version_id, version_id)
        if not connection.scalar(select(db.preparations.c.model_version_id).where(db.preparations.c.model_version_id == version_id)):
            connection.execute(db.preparations.insert().values(model_version_id=version_id))
    from .model_database import synchronize
    synchronize(engine, version_id)
    return {
        "id": version_id,
        "number": number,
        "model_id": model_id,
        "status": ModelVersionStatus.INGESTION_BRONZE.value,
    }


def validate_stage(engine, version_id, stage):
    from .silver import progression_blocker

    transitions = {"bronze": ("ingestion-bronze", "ingestion-silver"),
                   "silver": ("ingestion-silver", "ingestion-gold")}
    source, target = transitions[stage]
    with engine.begin() as connection:
        version = locked_version(connection, version_id)
        if version["status"] != source:
            raise HTTPException(409, "Cette étape n’est plus l’étape active. Recharge la version du modèle.")
        if connection.scalar(select(db.preparations.c.model_version_id).where(db.preparations.c.model_version_id == version_id)):
            raise HTTPException(409, "Valide le formulaire Bronze et résous sa table tampon pour accéder à Silver. Les étapes Silver de ce parcours seront définies séparément.")
        if not connection.scalar(select(func.count()).select_from(db.bindings).where(db.bindings.c.model_version_id == version_id)):
            raise HTTPException(409, "Charge au moins un dataset bronze avant de valider cette étape.")
        if stage == "silver":
            reason = progression_blocker(connection, version_id)
            if reason:
                raise HTTPException(409, reason)
        updated = connection.execute(db.model_versions.update().where(db.model_versions.c.id == version_id)
                                     .values(status=target).returning(db.model_versions)).mappings().one()
        record(connection, version_id, "stage_validated", {"stage": stage})
        record(connection, version_id, "status_changed", {"from_status": source, "to_status": target})
        return dict(updated)


def attach(connection, version_id, dataset_id, snapshot, filename, created=False):
    old = connection.scalar(
        select(db.bindings.c.dataset_version_id).where(
            db.bindings.c.model_version_id == version_id,
            db.bindings.c.dataset_id == dataset_id,
        )
    )
    if old == snapshot["id"]:
        status, action = "duplicate", "upload_duplicate"
    else:
        connection.execute(
            insert(db.bindings)
            .values(
                model_version_id=version_id,
                dataset_id=dataset_id,
                dataset_version_id=snapshot["id"],
            )
            .on_conflict_do_update(
                index_elements=[
                    db.bindings.c.model_version_id,
                    db.bindings.c.dataset_id,
                ],
                set_={"dataset_version_id": snapshot["id"]},
            )
        )
        status, action = (
            ("created", "dataset_uploaded") if created else ("reused", "dataset_reused")
        )
    record(
        connection,
        version_id,
        action,
        {"filename": filename, "previous_snapshot_id": str(old) if old else None},
        snapshot["id"],
    )
    return status


def ingest(engine, version_id, prepared, entries, root, workspace):
    results = []
    # Un lot est atomique : un fichier invalide annule toutes les écritures du lot.
    with engine.begin() as connection:
        version = locked_version(connection, version_id)
        if version["status"] != "ingestion-bronze":
            raise HTTPException(409, "L’étape bronze est validée. Crée une nouvelle version du modèle pour changer ses sources.")
        if connection.scalar(select(db.preparations.c.state).where(db.preparations.c.model_version_id == version_id)) is not None:
            raise HTTPException(409, "Cette version utilise le formulaire Bronze. Téléverse et valide ses sources dans ce formulaire.")
        for index, (source, entry) in enumerate(zip(prepared, entries)):
            contract = resolve_contract(connection, entry, root) if source["format"] == "csv" else None
            if source["format"] == "sql" and (entry.contract is not None or entry.contract_yaml is not None or entry.contract_mode != "existing"):
                raise HTTPException(422, "Le SQL utilise son schéma CREATE TABLE, sans contrat CSV")
            dataset = (
                connection.execute(
                    select(db.datasets).where(
                        db.datasets.c.model_id == version["model_id"],
                        db.datasets.c.name == entry.dataset_name,
                    )
                )
                .mappings()
                .first()
            )
            if dataset is None:
                dataset = (
                    connection.execute(
                        db.datasets.insert()
                        .values(
                            id=uuid4(),
                            model_id=version["model_id"],
                            name=entry.dataset_name,
                        )
                        .returning(db.datasets)
                    )
                    .mappings()
                    .one()
                )
            existing = (
                connection.execute(
                    select(db.dataset_versions)
                    .join(db.sources)
                    .where(
                        db.dataset_versions.c.dataset_id == dataset["id"],
                        db.sources.c.sha256 == source["sha256"],
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if (
                    existing["format"] != source["format"]
                    or existing["contract"] != contract
                ):
                    raise HTTPException(
                        409,
                        f"{source['filename']} : contenu déjà importé avec un autre format ou contrat",
                    )
                snapshot = existing
                created = False
            else:
                analysis_dir = workspace / f"analysis-{index}"
                analysis_dir.mkdir()
                analysis = analyze(source, entry, root, analysis_dir, csv_contract=contract)
                source_id = connection.execute(
                    insert(db.sources)
                    .values(
                        id=uuid4(),
                        sha256=source["sha256"],
                        size_bytes=source["size_bytes"],
                        content=source["path"].read_bytes(),
                    )
                    .on_conflict_do_nothing(index_elements=[db.sources.c.sha256])
                    .returning(db.sources.c.id)
                ).scalar_one_or_none()
                if source_id is None:
                    source_id = connection.scalar(
                        select(db.sources.c.id).where(
                            db.sources.c.sha256 == source["sha256"]
                        )
                    )
                number = (
                    connection.scalar(
                        select(func.max(db.dataset_versions.c.number)).where(
                            db.dataset_versions.c.dataset_id == dataset["id"]
                        )
                    )
                    or 0
                ) + 1
                snapshot = (
                    connection.execute(
                        db.dataset_versions.insert()
                        .values(
                            id=uuid4(),
                            dataset_id=dataset["id"],
                            source_id=source_id,
                            number=number,
                            filename=source["filename"],
                            format=source["format"],
                            contract_name=entry.contract or (contract["dataset"][:120] if contract else None),
                            contract=analysis["contract"],
                            types_catalog=analysis["types_catalog"],
                            summary=analysis["summary"],
                            report=analysis["report"],
                        )
                        .returning(db.dataset_versions)
                    )
                    .mappings()
                    .one()
                )
                for table_name, values in analysis["tables"].items():
                    for start in range(0, len(values), 1000):
                        connection.execute(
                            db.rows.insert(),
                            [
                                {
                                    "dataset_version_id": snapshot["id"],
                                    "table_name": table_name,
                                    "row_number": start + offset + 1,
                                    "data": row,
                                }
                                for offset, row in enumerate(
                                    values[start : start + 1000]
                                )
                            ],
                        )
                created = True
            status = attach(
                connection,
                version_id,
                dataset["id"],
                snapshot,
                source["filename"],
                created,
            )
            results.append(
                {
                    "filename": source["filename"],
                    "dataset_id": dataset["id"],
                    "snapshot_id": snapshot["id"],
                    "number": snapshot["number"],
                    "status": status,
                    "sha256": source["sha256"],
                    "summary": snapshot["summary"],
                }
            )
    return {"results": results}


def audit_rejection(engine, version_id, reason):
    with engine.begin() as connection:
        locked_version(connection, version_id)
        record(connection, version_id, "upload_rejected", {"reason": reason})

"""Préchargement sans écriture : associer un contrat éditable à chaque CSV."""

import json
from uuid import UUID

import yaml
from fastapi import HTTPException
from sqlalchemy import select
from indusense_ingestion.contracts import read_config, validate_configuration
from indusense_ingestion.ingestion import propose_contract

from .. import catalog as db
from .analysis import analyze, contract_paths, parse_csv_contract, raw_csv


def contract_catalog(engine, root):
    options = [{"value": name, "label": name} for name in contract_paths(root)]
    with engine.connect() as connection:
        snapshots = connection.execute(select(db.dataset_versions.c.id, db.dataset_versions.c.contract,
                                               db.dataset_versions.c.filename, db.dataset_versions.c.created_at)
                                       .where(db.dataset_versions.c.format == "csv")
                                       .order_by(db.dataset_versions.c.created_at.desc())).mappings().all()
        staged = connection.execute(select(db.preparation_files.c.id, db.preparation_files.c.dataset_name,
                                            db.preparation_files.c.filename, db.preparation_files.c.saved_yaml,
                                            db.preparation_files.c.revision)
                                    .where(db.preparation_files.c.format == "csv", db.preparation_files.c.saved_yaml.is_not(None))
                                    .order_by(db.preparation_files.c.created_at.desc())).mappings().all()
    # Une proposition devient réutilisable uniquement après son chargement en bronze.
    seen = set()
    for snapshot in snapshots:
        if snapshot["contract"] is None:
            continue
        canonical = json.dumps(snapshot["contract"], sort_keys=True)
        if canonical in seen:
            continue
        seen.add(canonical)
        options.append({"value": f"snapshot:{snapshot['id']}",
                        "label": f"{snapshot['contract']['dataset']} · {snapshot['filename']} · {snapshot['created_at']:%d/%m/%Y %H:%M}"})
    types = read_config(root / "config/types.yaml")["types"]
    for file in staged:
        try:
            contract = parse_csv_contract(file["saved_yaml"], types)
        except (ValueError, TypeError, yaml.YAMLError):
            continue
        canonical = json.dumps(contract, sort_keys=True)
        if canonical in seen:
            continue
        seen.add(canonical)
        options.append({"value": f"preparation:{file['id']}", "label": f"{file['dataset_name']} · {file['filename']} · r{file['revision']}"})
    return options


def resolve_contract(connection, entry, root):
    types = read_config(root / "config/types.yaml")["types"]
    if entry.contract_yaml is not None:
        return parse_csv_contract(entry.contract_yaml, types)
    if entry.contract_mode == "generate":
        raise HTTPException(422, "Précharge le CSV pour générer puis vérifier son contrat avant de charger en bronze")
    if entry.contract and entry.contract.startswith("preparation:"):
        try:
            file_id = UUID(entry.contract.removeprefix("preparation:"))
        except ValueError:
            raise HTTPException(422, "Référence de contrat invalide") from None
        text = connection.scalar(select(db.preparation_files.c.saved_yaml).where(db.preparation_files.c.id == file_id,
                                  db.preparation_files.c.format == "csv"))
        if not text:
            raise HTTPException(422, "Contrat sauvegardé introuvable")
        return parse_csv_contract(text, types)
    if entry.contract and entry.contract.startswith("snapshot:"):
        try:
            snapshot_id = UUID(entry.contract.removeprefix("snapshot:"))
        except ValueError:
            raise HTTPException(422, "Référence de contrat invalide") from None
        contract = connection.scalar(select(db.dataset_versions.c.contract).where(
            db.dataset_versions.c.id == snapshot_id, db.dataset_versions.c.format == "csv"))
        if contract is None:
            raise HTTPException(422, "Contrat enregistré introuvable")
    else:
        selected = contract_paths(root).get(entry.contract)
        if selected is None:
            raise HTTPException(422, "Choisir un contrat existant ou demander la génération d’un contrat")
        contract = read_config(selected)
    validate_configuration(contract, types)
    return contract


def preload(engine, version_id, prepared, entries, root, workspace):
    results = []
    with engine.connect() as connection:
        if connection.scalar(select(db.model_versions.c.id).where(db.model_versions.c.id == version_id)) is None:
            raise HTTPException(404, "Version du modèle introuvable")
        for index, (source, entry) in enumerate(zip(prepared, entries)):
            work = workspace / f"analysis-{index}"
            work.mkdir()
            contract = None
            contract_yaml = None
            if source["format"] == "csv":
                # Vérifier les en-têtes avant pandas, qui renommerait un doublon.
                raw_csv(source["path"])
                if entry.contract_mode == "generate":
                    contract = propose_contract(source["path"], entry.dataset_name, types_path=root / "config/types.yaml")
                    contract_yaml = yaml.safe_dump(contract, allow_unicode=True, sort_keys=False)
                else:
                    contract = resolve_contract(connection, entry, root)
                    selected = contract_paths(root).get(entry.contract)
                    # Conserver le YAML sélectionné, ses commentaires et ses règles sans expansion.
                    contract_yaml = (entry.contract_yaml if entry.contract_yaml is not None else
                                     selected.read_text(encoding="utf-8") if selected else
                                     yaml.safe_dump(contract, allow_unicode=True, sort_keys=False))
            analysis = analyze(source, entry, root, work, csv_contract=contract)
            if contract_yaml and len(contract_yaml) > 200000:
                raise ValueError(f"{source['filename']} : contrat trop volumineux (limite de 200 000 caractères)")
            results.append({"filename": source["filename"], "sha256": source["sha256"], "format": source["format"],
                            "contract_yaml": contract_yaml,
                            "contract_mode": entry.contract_mode if contract else None,
                            "contract_name": entry.contract if contract and entry.contract_mode == "existing" else None,
                            "summary": analysis["summary"]})
    return {"results": results}

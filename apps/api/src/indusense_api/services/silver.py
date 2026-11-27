"""Préparation silver et arbitrage humain, sous le verrou de la version."""

from uuid import uuid4

import yaml
import re
from fastapi import HTTPException
from sqlalchemy import func, select
from indusense_ingestion.silver import parse_contract, source_hash, transform

from .. import catalog as db
from .workflow import locked_version, record


def require_editable(version):
    if version["status"] not in ("ingestion-bronze", "ingestion-silver"):
        raise HTTPException(409, "L’étape silver est validée. Crée une nouvelle version du modèle pour modifier sa préparation.")


def source_table(connection, version_id, snapshot_id, table_name):
    snapshot = connection.execute(
        select(db.dataset_versions).join(db.bindings, db.bindings.c.dataset_version_id == db.dataset_versions.c.id)
        .where(db.bindings.c.model_version_id == version_id, db.dataset_versions.c.id == snapshot_id)
    ).mappings().first()
    if snapshot is None:
        raise HTTPException(404, "Snapshot non associé à cette version du modèle")
    table = next((table for table in snapshot["summary"]["tables"] if table["name"] == table_name), None)
    if table is None:
        raise HTTPException(404, "Table source introuvable")
    return snapshot, table


def latest_contract(connection, version_id, snapshot_id, table_name):
    return connection.execute(select(db.silver_contracts).where(
        db.silver_contracts.c.model_version_id == version_id,
        db.silver_contracts.c.dataset_version_id == snapshot_id,
        db.silver_contracts.c.table_name == table_name,
    ).order_by(db.silver_contracts.c.number.desc()).limit(1)).mappings().first()


def draft_contract(snapshot, table):
    original = snapshot["contract"] or {}
    columns = {}
    for column in table["columns"]:
        # Les types inférés en bronze deviennent des déclarations explicites révisables.
        spec = original.get("columns", {}).get(column["name"])
        if spec is None:
            spec = next(({key: value for key, value in rule.items() if key != "pattern"}
                         for rule in original.get("column_rules", []) if re.search(rule["pattern"], column["name"])),
                        {"type": column["type"]})
        columns[column["name"]] = spec
    return yaml.safe_dump({"version": 1, "dataset": original.get("dataset", table["name"]),
                           "extra_columns": "error", "columns": columns}, allow_unicode=True, sort_keys=False)


def contract_editor(engine, version_id, snapshot_id, table_name):
    with engine.connect() as connection:
        snapshot, table = source_table(connection, version_id, snapshot_id, table_name)
        revisions = connection.execute(select(db.silver_contracts).where(
            db.silver_contracts.c.model_version_id == version_id,
            db.silver_contracts.c.dataset_version_id == snapshot_id,
            db.silver_contracts.c.table_name == table_name,
        ).order_by(db.silver_contracts.c.number.desc())).mappings().all()
        return {"yaml": revisions[0]["yaml"] if revisions else draft_contract(snapshot, table),
                "revisions": [dict(revision) for revision in revisions],
                "types": snapshot["types_catalog"]["types"]}


def validate_text(snapshot, table, text):
    try:
        return parse_contract(text, snapshot["types_catalog"]["types"], [col["name"] for col in table["columns"]])
    except (ValueError, TypeError, KeyError, yaml.YAMLError) as error:
        raise HTTPException(422, f"Contrat invalide : {error}") from None


def save_contract(engine, version_id, snapshot_id, table_name, data, *, save):
    with engine.begin() as connection:
        version = locked_version(connection, version_id)
        require_editable(version)
        snapshot, table = source_table(connection, version_id, snapshot_id, table_name)
        config, specs, output = validate_text(snapshot, table, data.yaml)
        if not save:
            return {"valid": True, "columns": output}
        latest = latest_contract(connection, version_id, snapshot_id, table_name)
        if latest and latest["yaml"] == data.yaml:
            return dict(latest)
        # Contrôle optimiste : ne pas écraser silencieusement une révision d’un autre onglet.
        if data.base_revision != (latest["number"] if latest else 0):
            raise HTTPException(409, "Le contrat a changé. Recharge sa dernière révision avant d’enregistrer.")
        result = connection.execute(db.silver_contracts.insert().values(
            id=uuid4(), model_version_id=version_id, dataset_version_id=snapshot_id,
            table_name=table_name, number=(latest["number"] + 1 if latest else 1),
            yaml=data.yaml, config=config, columns=specs, types_catalog=snapshot["types_catalog"],
        ).returning(db.silver_contracts)).mappings().one()
        record(connection, version_id, "silver_contract_saved", {"table": table_name, "revision": result["number"]}, snapshot_id)
        return dict(result)


def pending_count(connection, version_id, run_id=None):
    query = select(func.count()).select_from(db.quarantine.join(db.silver_runs)).where(
        db.silver_runs.c.model_version_id == version_id, db.quarantine.c.state == "pending")
    if run_id:
        query = query.where(db.silver_runs.c.id == run_id)
    return connection.scalar(query)


def prepare(engine, version_id, snapshot_id, table_name, contract_id):
    with engine.begin() as connection:
        version = locked_version(connection, version_id)
        require_editable(version)
        if version["status"] != "ingestion-silver":
            raise HTTPException(409, "Valide l’étape bronze avant de préparer les données silver.")
        snapshot, table = source_table(connection, version_id, snapshot_id, table_name)
        contract = latest_contract(connection, version_id, snapshot_id, table_name)
        if contract is None or contract["id"] != contract_id:
            raise HTTPException(409, "Enregistre et sélectionne la dernière révision validée du contrat")
        existing = connection.execute(select(db.silver_runs).where(db.silver_runs.c.contract_id == contract_id)).mappings().first()
        if existing:
            return dict(existing)
        unresolved = connection.scalar(select(func.count()).select_from(db.quarantine.join(db.silver_runs)).where(
            db.silver_runs.c.model_version_id == version_id, db.silver_runs.c.dataset_version_id == snapshot_id,
            db.silver_runs.c.table_name == table_name, db.quarantine.c.state == "pending"))
        if unresolved:
            raise HTTPException(409, "Résous la table tampon précédente avant une nouvelle exécution de cette table")
        raw = connection.execute(select(db.rows.c.row_number, db.rows.c.data).where(
            db.rows.c.dataset_version_id == snapshot_id, db.rows.c.table_name == table_name,
        ).order_by(db.rows.c.row_number)).mappings().all()
        _, specs, columns = parse_contract(contract["yaml"], contract["types_catalog"]["types"], [column["name"] for column in table["columns"]])
        run = connection.execute(db.silver_runs.insert().values(
            id=uuid4(), model_version_id=version_id, dataset_version_id=snapshot_id,
            table_name=table_name, contract_id=contract_id, columns=columns, source_rows=len(raw),
        ).returning(db.silver_runs)).mappings().one()
        decisions = connection.execute(select(db.quarantine, db.silver_contracts.c.number.label("revision"))
                                       .select_from(db.quarantine.join(db.silver_runs).join(db.silver_contracts))
                                       .where(db.silver_runs.c.model_version_id == version_id,
                                              db.silver_runs.c.dataset_version_id == snapshot_id,
                                              db.silver_runs.c.table_name == table_name,
                                              db.quarantine.c.state != "pending")
                                       .order_by(db.silver_contracts.c.number)).mappings().all()
        previous = {row["row_number"]: row for row in decisions}
        valid, invalid = 0, 0
        for start in range(0, len(raw), 1000):
            batch = raw[start:start + 1000]
            candidates = [previous[row["row_number"]]["candidate"] if row["row_number"] in previous else row["data"] for row in batch]
            outputs, issues = transform(candidates, specs, contract["types_catalog"]["types"])
            accepted, rejected = [], []
            for row, candidate, output, errors in zip(batch, candidates, outputs, issues):
                decision = previous.get(row["row_number"])
                output["hash"] = source_hash(row["data"])
                if decision and decision["state"] == "discarded":
                    rejected.append({"id": uuid4(), "run_id": run["id"], "row_number": row["row_number"],
                                     "source": row["data"], "candidate": candidate, "errors": [], "state": "discarded",
                                     "reason": decision["reason"], "resolved_at": decision["resolved_at"]})
                    continue
                if errors:
                    rejected.append({"id": uuid4(), "run_id": run["id"], "row_number": row["row_number"],
                                     "source": row["data"], "candidate": candidate, "errors": errors,
                                     "state": "pending", "reason": None, "resolved_at": None})
                else:
                    accepted.append({"run_id": run["id"], "row_number": row["row_number"], "data": output})
            if accepted:
                connection.execute(db.silver_rows.insert(), accepted)
            if rejected:
                connection.execute(db.quarantine.insert(), rejected)
            valid += len(accepted)
            invalid += sum(row["state"] == "pending" for row in rejected)
        record(connection, version_id, "silver_prepared", {"run_id": str(run["id"]), "table": table_name,
                                                         "valid_rows": valid, "pending_rows": invalid}, snapshot_id)
        return dict(run)


def workspace(engine, version_id):
    with engine.connect() as connection:
        if not connection.scalar(select(db.model_versions.c.id).where(db.model_versions.c.id == version_id)):
            raise HTTPException(404, "Version introuvable")
        runs = connection.execute(select(db.silver_runs, db.silver_contracts.c.number.label("contract_revision"))
                                 .select_from(db.silver_runs.join(db.silver_contracts)).where(db.silver_runs.c.model_version_id == version_id)
                                 .order_by(db.silver_runs.c.created_at.desc())).mappings().all()
        counts = connection.execute(select(db.quarantine.c.run_id, db.quarantine.c.state, func.count().label("total"))
                                    .select_from(db.quarantine.join(db.silver_runs))
                                    .where(db.silver_runs.c.model_version_id == version_id)
                                    .group_by(db.quarantine.c.run_id, db.quarantine.c.state)).mappings().all()
        valid = dict(connection.execute(select(db.silver_rows.c.run_id, func.count())
                                        .select_from(db.silver_rows.join(db.silver_runs))
                                        .where(db.silver_runs.c.model_version_id == version_id)
                                        .group_by(db.silver_rows.c.run_id)).all())
        blocker = progression_blocker(connection, version_id)
        return {"pending": sum(row["total"] for row in counts if row["state"] == "pending"),
                "can_advance": blocker is None, "blocking_reason": blocker,
                "runs": [{**dict(run), "valid_rows": valid.get(run["id"], 0),
                          **{state: sum(row["total"] for row in counts if row["run_id"] == run["id"] and row["state"] == state)
                             for state in ("pending", "discarded", "reintegrated")}} for run in runs]}


def resolve(engine, version_id, issue_id, data):
    with engine.begin() as connection:
        version = locked_version(connection, version_id)
        require_editable(version)
        issue = connection.execute(select(db.quarantine).join(db.silver_runs)
                                   .where(db.quarantine.c.id == issue_id, db.silver_runs.c.model_version_id == version_id)).mappings().first()
        if issue is None:
            raise HTTPException(404, "Ligne tampon introuvable pour cette version")
        if issue["state"] != "pending":
            raise HTTPException(409, "Cette ligne a déjà été résolue")
        candidate = issue["candidate"]
        if data.action == "reintegrate":
            run = connection.execute(select(db.silver_runs).where(db.silver_runs.c.id == issue["run_id"])).mappings().one()
            contract = connection.execute(select(db.silver_contracts).where(db.silver_contracts.c.id == run["contract_id"])).mappings().one()
            if data.values is None or data.values.keys() - contract["columns"].keys():
                raise HTTPException(422, "Fournir des corrections pour les colonnes sources du contrat uniquement")
            candidate = {**issue["candidate"], **data.values}
            outputs, errors = transform([candidate], contract["columns"], contract["types_catalog"]["types"])
            if errors[0]:
                connection.execute(db.quarantine.update().where(db.quarantine.c.id == issue_id)
                                   .values(candidate=candidate, errors=errors[0]))
                return {"resolved": False, "errors": errors[0]}
            # Le hash désigne toujours la ligne source bronze ; la correction est tracée à part.
            outputs[0]["hash"] = source_hash(issue["source"])
            connection.execute(db.silver_rows.insert().values(run_id=run["id"], row_number=issue["row_number"], data=outputs[0]))
        state = "reintegrated" if data.action == "reintegrate" else "discarded"
        connection.execute(db.quarantine.update().where(db.quarantine.c.id == issue_id).values(
            state=state, candidate=candidate, reason=data.reason, resolved_at=func.now()))
        record(connection, version_id, "silver_row_resolved", {"issue_id": str(issue_id), "run_id": str(issue["run_id"]),
                                                               "row_number": issue["row_number"], "decision": state, "reason": data.reason})
        return {"resolved": True, "state": state}


def progression_blocker(connection, version_id):
    pending = pending_count(connection, version_id)
    if pending:
        return f"Progression bloquée : {pending} ligne(s) restent à résoudre dans la table tampon de cette version"
    # Toutes les tables doivent être traitées, même si aucun contrat n’a encore été créé.
    snapshots = connection.execute(select(db.dataset_versions).join(db.bindings, db.bindings.c.dataset_version_id == db.dataset_versions.c.id)
                                   .where(db.bindings.c.model_version_id == version_id)).mappings().all()
    if not snapshots:
        return "Progression bloquée : aucun dataset bronze associé à cette version"
    for snapshot in snapshots:
        for table in snapshot["summary"]["tables"]:
            contract = latest_contract(connection, version_id, snapshot["id"], table["name"])
            if contract is None or not connection.scalar(select(db.silver_runs.c.id).where(db.silver_runs.c.contract_id == contract["id"])):
                return "Progression bloquée : prépare toutes les tables des snapshots actuels avec leur dernier contrat validé"
    return None

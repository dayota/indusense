"""Bases PostgreSQL dédiées aux versions ; SQL reçu analysé, jamais exécuté."""
import base64
import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid5

import psycopg
from psycopg import sql
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError
from fastapi import HTTPException

from indusense_ingestion.bronze import transform_bronze, validate_plan

storage = sa.MetaData(schema="bronze")
files_table = sa.Table("_files", storage,
    sa.Column("id", sa.Uuid, primary_key=True), sa.Column("filename", sa.Text, nullable=False),
    sa.Column("sha256", sa.String(64), nullable=False), sa.Column("plans", JSONB, nullable=False),
    sa.Column("types_catalog", JSONB, nullable=False),
)
lineage = sa.Table("_row_sources", storage,
    sa.Column("id", sa.Uuid, primary_key=True), sa.Column("file_id", sa.Uuid, nullable=False),
    sa.Column("source_table", sa.Text, nullable=False), sa.Column("target_table", sa.Text, nullable=False),
    sa.Column("row_number", sa.BigInteger, nullable=False), sa.Column("state", sa.String(16), nullable=False),
    sa.Column("hash", sa.String(64), nullable=False), sa.Column("data", JSONB),
    sa.UniqueConstraint("file_id", "source_table", "row_number"),
)
quarantine = sa.Table("_quarantine", storage,
    sa.Column("id", sa.Uuid, sa.ForeignKey("bronze._row_sources.id"), primary_key=True),
    sa.Column("file_id", sa.Uuid, nullable=False), sa.Column("source_table", sa.Text, nullable=False),
    sa.Column("target_table", sa.Text, nullable=False), sa.Column("row_number", sa.BigInteger, nullable=False),
    sa.Column("source", JSONB, nullable=False), sa.Column("candidate", JSONB, nullable=False),
    sa.Column("errors", JSONB, nullable=False), sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("reason", sa.Text), sa.Column("resolved_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint("state IN ('pending', 'reintegrated', 'discarded')"),
)
sa.Index("ix_bronze_quarantine_state", quarantine.c.state)
sa.Index("ix_bronze_row_sources_table", lineage.c.target_table, lineage.c.row_number)


def normalized_name(value, max_length=63):
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"[^a-z0-9]+", "_", ascii_name).strip("_") or "dataset"
    if len(name) > max_length:
        name = name[:max_length - 9] + "_" + hashlib.sha256(value.encode()).hexdigest()[:8]
    return name


def database_name(model_name, number):
    suffix = f"-{number}"
    return normalized_name(model_name, 63 - len(suffix)) + suffix


def version_engine(engine, name):
    return sa.create_engine(engine.url.set(database=name), pool_pre_ping=True,
                            connect_args={"connect_timeout": 3}, poolclass=sa.pool.NullPool)


def create_database(engine, name):
    url = engine.url
    try:
        with psycopg.connect(host=url.host, port=url.port, user=url.username, password=url.password,
                             dbname="postgres", autocommit=True, connect_timeout=3) as admin:
            if admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
                raise HTTPException(409, f"La base « {name} » existe déjà. Crée une nouvelle version du modèle ; cette base ne sera pas remplacée.")
            try:
                admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
            except psycopg.errors.DuplicateDatabase:
                raise HTTPException(409, f"La base « {name} » existe déjà. Crée une nouvelle version du modèle.") from None
            admin.execute(sql.SQL("ALTER DATABASE {} SET search_path TO bronze, public").format(sql.Identifier(name)))
    except psycopg.Error as error:
        raise HTTPException(503, f"Création de la base impossible ({error.sqlstate or 'connexion'}). Vérifie PostgreSQL et les droits de création de base.") from None


def ensure_model_database(engine, name, model_id):
    """Reuse only a database carrying this model's ownership marker; never adopt an unrelated DB."""
    url = engine.url
    marker = f"indusense:model:{model_id}"
    with psycopg.connect(host=url.host, port=url.port, user=url.username, password=url.password,
                         dbname="postgres", autocommit=True, connect_timeout=3) as admin:
        admin.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", ("database:" + name,))
        existing = admin.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if existing:
            if existing[0] != marker:
                raise HTTPException(409, f"La base « {name} » n'appartient pas à ce modèle. Aucune donnée n'a été remplacée.")
        else:
            admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
            admin.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(sql.Identifier(name), sql.Literal(marker)))
        admin.execute(sql.SQL("ALTER DATABASE {} SET search_path TO versionning, public").format(sql.Identifier(name)))


def sql_type(spec, types):
    kind = spec["type"]
    converter = types[kind]["converter"]
    if converter == "string": return sa.Text()
    if converter == "integer": return sa.BigInteger()
    if converter == "number": return sa.Double()
    if converter == "decimal": return sa.Numeric()
    if converter == "boolean": return sa.Boolean()
    if converter == "datetime_utc": return sa.DateTime(timezone=True)
    if converter == "datetime":
        return sa.Date() if kind == "DATE" else sa.Time() if kind == "TIME" else sa.DateTime()
    raise ValueError(f"Convertisseur SQL indisponible : {converter}")


def data_table(plan, types):
    generated, _ = validate_plan(plan["columns"], plan["technical"], types)
    columns = []
    for item in plan["columns"] + generated:
        columns.append(sa.Column(item["name"], sql_type(item["spec"], types), nullable=item["spec"].get("nullable", True), quote=True))
        columns.append(sa.Column(item["name"] + "-type", sa.Text, nullable=False, quote=True))
    columns.append(sa.Column("hash", sa.String(64), nullable=False))
    return sa.Table(plan["target"], sa.MetaData(schema="bronze"), *columns, quote=True)


def native_values(output, plan, types):
    result = dict(output)
    generated, _ = validate_plan(plan["columns"], plan["technical"], types)
    for column in plan["columns"] + generated:
        name, spec = column["name"], column["spec"]
        if result[name] is None: continue
        options = {**types[spec["type"]], **spec}
        converter = options["converter"]
        if converter == "decimal": result[name] = Decimal(result[name])
        elif converter in ("datetime", "datetime_utc"):
            value = datetime.strptime(result[name], options["format"])
            if converter == "datetime_utc" and value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            result[name] = value.date() if spec["type"] == "DATE" else value.time() if spec["type"] == "TIME" else value
    return result


def json_safe(value):
    # PostgreSQL JSONB refuse U+0000 ; conserver les octets de cette cellule sans les perdre.
    if isinstance(value, str) and "\x00" in value:
        return {"raw_utf8_base64": base64.b64encode(value.encode()).decode(), "error": "Caractère NUL interdit par PostgreSQL"}
    if isinstance(value, dict): return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list): return [json_safe(item) for item in value]
    return value


def storage_error(error):
    state = getattr(error.orig, "sqlstate", None)
    if state is None or not state.startswith(("22", "23")):
        raise error
    message = getattr(getattr(error.orig, "diag", None), "message_primary", None) or "Insertion PostgreSQL refusée"
    return [{"column": "", "message": message, "sqlstate": state}]


def store_batch(connection, target, items, file_id, plan):
    """Insérer en lot ; isoler par dichotomie les lignes rejetées par PostgreSQL."""
    if not items: return
    try:
        with connection.begin_nested():
            connection.execute(target.insert(), [item["native"] for item in items])
    except DBAPIError as error:
        errors = storage_error(error)
        if len(items) > 1:
            half = len(items) // 2
            store_batch(connection, target, items[:half], file_id, plan)
            store_batch(connection, target, items[half:], file_id, plan)
            return
        store_rejection(connection, file_id, plan, items[0], errors)
        return
    connection.execute(lineage.insert(), [{"id": item["id"], "file_id": file_id, "source_table": plan["source"],
        "target_table": plan["target"], "row_number": item["number"], "state": "valid", "hash": item["output"]["hash"],
        "data": item["output"]} for item in items])


def store_rejection(connection, file_id, plan, item, errors):
    connection.execute(lineage.insert().values(id=item["id"], file_id=file_id, source_table=plan["source"],
        target_table=plan["target"], row_number=item["number"], state="pending", hash=item["output"]["hash"]))
    connection.execute(quarantine.insert().values(id=item["id"], file_id=file_id, source_table=plan["source"],
        target_table=plan["target"], row_number=item["number"], source=json_safe(item["raw"]),
        candidate=json_safe(item["raw"]), errors=errors))


def insert_records(connection, file, plan, records):
    types = file["types_catalog"]["types"]
    target = data_table(plan, types)
    target.create(connection)
    for start in range(0, len(records), 1000):
        batch = records[start:start + 1000]
        outputs, errors, _ = transform_bronze(batch, plan["columns"], plan["technical"], types)
        accepted = []
        for offset, (raw, output, issues) in enumerate(zip(batch, outputs, errors)):
            number = start + offset + 1
            item = {"id": uuid5(file["id"], f"{plan['source']}:{number}"), "number": number, "raw": raw, "output": output}
            # Ces valeurs ne peuvent pas être encodées dans une insertion PostgreSQL.
            for name, value in output.items():
                if isinstance(value, str) and "\x00" in value:
                    issues.append({"column": name, "message": "Caractère NUL interdit par PostgreSQL"})
            if issues:
                store_rejection(connection, file["id"], plan, item, issues)
            else:
                item["native"] = native_values(output, plan, types)
                accepted.append(item)
        store_batch(connection, target, accepted, file["id"], plan)


def summary(connection):
    states = dict(connection.execute(sa.select(lineage.c.state, sa.func.count()).group_by(lineage.c.state)).all())
    pending = connection.scalar(sa.select(sa.func.count()).select_from(quarantine).where(quarantine.c.state == "pending"))
    tables = connection.execute(sa.select(lineage.c.target_table, sa.func.count().label("rows"))
                                .where(lineage.c.state == "valid").group_by(lineage.c.target_table)).mappings().all()
    counts = {row["target_table"]: row["rows"] for row in tables}
    definitions = connection.execute(sa.select(files_table)).mappings().all()
    return {"pending": pending, "valid": states.get("valid", 0), "excluded": states.get("discarded", 0),
            "tables": [{"name": plan["target"], "file_id": str(file["id"]), "filename": file["filename"],
                        "source": plan["source"], "columns": plan["output"], "rows": counts.get(plan["target"], 0)}
                       for file in definitions for plan in file["plans"]]}


def resolve_row(connection, issue_id, data):
    issue = connection.execute(sa.select(quarantine).where(quarantine.c.id == issue_id).with_for_update()).mappings().first()
    if issue is None: raise HTTPException(404, "Ligne en erreur introuvable")
    if issue["state"] != "pending": raise HTTPException(409, "Cette ligne est déjà résolue")
    original_hash = connection.scalar(sa.select(lineage.c.hash).where(lineage.c.id == issue_id))
    if data.action == "reintegrate":
        definition = connection.execute(sa.select(files_table).where(files_table.c.id == issue["file_id"])).mappings().one()
        plan = next(plan for plan in definition["plans"] if plan["target"] == issue["target_table"])
        names = {column["name"] for column in plan["columns"]}
        if data.values is None or data.values.keys() - names:
            raise HTTPException(422, "Modifie uniquement les colonnes sources de la ligne")
        candidate = {**issue["candidate"], **data.values}
        outputs, errors, _ = transform_bronze([candidate], plan["columns"], plan["technical"], definition["types_catalog"]["types"])
        output = outputs[0]
        output["hash"] = original_hash
        for name, value in output.items():
            if isinstance(value, str) and "\x00" in value:
                errors[0].append({"column": name, "message": "Caractère NUL interdit par PostgreSQL"})
        if not errors[0]:
            try:
                with connection.begin_nested():
                    connection.execute(data_table(plan, definition["types_catalog"]["types"]).insert(),
                                       native_values(output, plan, definition["types_catalog"]["types"]))
            except DBAPIError as error:
                errors[0] = storage_error(error)
        if errors[0]:
            connection.execute(quarantine.update().where(quarantine.c.id == issue_id).values(candidate=json_safe(candidate), errors=errors[0]))
            return {"resolved": False, "errors": errors[0]}
        connection.execute(lineage.update().where(lineage.c.id == issue_id).values(state="valid", data=output))
        connection.execute(quarantine.update().where(quarantine.c.id == issue_id).values(candidate=json_safe(candidate)))
        state = "reintegrated"
    else:
        state = "discarded"
        connection.execute(lineage.update().where(lineage.c.id == issue_id).values(state=state))
    connection.execute(quarantine.update().where(quarantine.c.id == issue_id).values(state=state, reason=data.reason, resolved_at=sa.func.now()))
    return {"resolved": True, "state": state, "row_number": issue["row_number"], "source_table": issue["source_table"]}

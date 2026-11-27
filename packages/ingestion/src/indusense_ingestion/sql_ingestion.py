"""Analyse statique de scripts PostgreSQL CREATE TABLE / INSERT VALUES.

Les nœuds SQL sont inspectés ; aucune instruction ni expression SQL n’est exécutée.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

from .paths import project_root, types_catalog
from .contracts import load_type_catalog
from .ingestion import PARIS, compute_statistics, infer_columns, read_text_source


@dataclass(frozen=True)
class Unevaluated:
    sql: str


def sql_text(node):
    return node.sql(dialect="postgres")


def literal_value(node):
    if isinstance(node, exp.Null):
        return None
    if isinstance(node, exp.Boolean):
        return "true" if node.this else "false"
    if isinstance(node, exp.Literal):
        return node.this
    if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal) and not node.this.is_string:
        return "-" + node.this.this
    return Unevaluated(sql_text(node))


def logical_type(column, identifier):
    kind = column.args["kind"].this.value
    if identifier:
        return "IDENTITY"
    mapping = {
        "VARCHAR": "TEXT", "CHAR": "TEXT", "TEXT": "TEXT",
        "SMALLINT": "INTEGER", "TINYINT": "INTEGER", "INT": "INTEGER", "BIGINT": "INTEGER",
        "DECIMAL": "DECIMAL", "FLOAT": "FLOAT", "DOUBLE": "FLOAT", "REAL": "FLOAT",
        "DATE": "DATE", "TIME": "TIME", "TIMESTAMP": "DATETIME",
        "TIMESTAMPTZ": "DATETIME_UTC", "BOOLEAN": "BOOLEAN",
    }
    if kind not in mapping:
        raise ValueError(f"Type SQL hors périmètre : {kind} ({column.name})")
    return mapping[kind]


def extract_schema(statement):
    schema = statement.this
    if not isinstance(schema, exp.Schema) or not isinstance(schema.this, exp.Table):
        raise ValueError("CREATE TABLE exige un schéma explicite ; CREATE AS hors périmètre")
    name = sql_text(schema.this)
    primary = set()
    references = set()
    for key in schema.find_all(exp.PrimaryKey):
        primary.update(item.name for item in key.expressions)
    for key in schema.find_all(exp.ForeignKey):
        references.update(item.name for item in key.expressions)
    columns = {}
    constraints = []
    for item in schema.expressions:
        if not isinstance(item, exp.ColumnDef):
            if isinstance(item, (exp.PrimaryKey, exp.ForeignKey, exp.CheckColumnConstraint, exp.UniqueColumnConstraint, exp.Constraint)):
                constraints.append(sql_text(item))
                continue
            raise ValueError(f"Définition de table hors périmètre : {sql_text(item)}")
        if item.name in columns:
            raise ValueError(f"Colonne dupliquée : {name}.{item.name}")
        kinds = [constraint.args["kind"] for constraint in item.args.get("constraints", [])]
        is_primary = item.name in primary or any(isinstance(c, exp.PrimaryKeyColumnConstraint) for c in kinds)
        identifier = is_primary or item.name in references or any(isinstance(c, exp.Reference) for c in kinds) or item.name.lower().endswith(("_id", "_code", "_badge"))
        defaults = [sql_text(c.this) for c in kinds if isinstance(c, exp.DefaultColumnConstraint)]
        columns[item.name] = {
            "sql_type": sql_text(item.args["kind"]), "type": logical_type(item, identifier),
            "nullable": not is_primary and not any(isinstance(c, exp.NotNullColumnConstraint) and not c.args.get("allow_null") for c in kinds),
            "default": defaults[0] if defaults else None,
            "constraints": [sql_text(c) for c in kinds],
        }
    if not columns:
        raise ValueError(f"Table sans colonnes exploitables : {name}")
    return name, {"schema": columns, "rows": [], "insert_columns": [], "constraints": constraints, "notes": []}


def extract_insert(statement, tables):
    target = statement.this
    if isinstance(target, exp.Schema):
        table = target.this
        names = [item.name for item in target.expressions]
    elif isinstance(target, exp.Table):
        table, names = target, None
    else:
        raise ValueError("Cible INSERT hors périmètre")
    name = sql_text(table)
    if name not in tables:
        raise ValueError(f"INSERT sans CREATE TABLE précédent : {name}")
    result = tables[name]
    names = names if names is not None else list(result["schema"])
    if len(set(names)) != len(names) or set(names) - result["schema"].keys():
        raise ValueError(f"Liste de colonnes INSERT invalide pour {name}")
    values = statement.expression
    if not isinstance(values, exp.Values):
        raise ValueError(f"Seul INSERT VALUES est pris en charge : {name}")
    if statement.args.get("returning") or statement.args.get("overwrite"):
        raise ValueError("INSERT RETURNING/OVERWRITE hors périmètre")
    result["insert_columns"].append(names)
    for row in values.expressions:
        if not isinstance(row, exp.Tuple) or len(row.expressions) != len(names):
            raise ValueError(f"Nombre de valeurs INSERT incorrect pour {name}")
        result["rows"].append(dict(zip(names, map(literal_value, row.expressions))))
    if statement.args.get("conflict"):
        result["notes"].append("ON CONFLICT décrit mais non appliqué : " + sql_text(statement.args["conflict"]))


def parse_sql_source(text):
    nodes = [node for node in sqlglot.parse(text, read="postgres", error_level=ErrorLevel.RAISE) if node is not None]
    if not nodes:
        raise ValueError("Aucune instruction SQL exploitable")
    tables, inventory = {}, Counter()
    for raw in nodes:
        node = normalize_identifiers(raw, dialect="postgres")
        if isinstance(node, exp.Create) and node.kind == "TABLE":
            name, table = extract_schema(node)
            if name in tables or node.expression is not None or node.args.get("replace"):
                raise ValueError(f"Redéfinition ou CREATE TABLE AS hors périmètre : {name}")
            tables[name] = table
            inventory["CREATE TABLE"] += 1
        elif isinstance(node, exp.Insert):
            extract_insert(node, tables)
            inventory["INSERT VALUES"] += 1
        elif isinstance(node, exp.Create) and node.kind == "INDEX":
            inventory["CREATE INDEX"] += 1
        elif isinstance(node, (exp.Transaction, exp.Commit)):
            inventory[type(node).__name__] += 1
        else:
            raise ValueError(f"Instruction hors périmètre : {sql_text(node)}")
    if not tables:
        raise ValueError("Aucune table déclarée dans le script")
    return tables, dict(inventory)


def analyze_table(table, types, *, column_analysis=None):
    schema, rows = table["schema"], table["rows"]
    frame = pd.DataFrame({
        name: [None if isinstance(row.get(name), Unevaluated) else row.get(name) for row in rows]
        for name in schema
    }, dtype="string")
    # Le schéma fait autorité ; les omissions sont décrites, jamais comblées par des défauts.
    contract = {"columns": {name: {"type": info["type"]} for name, info in schema.items()}, "extra_columns": "error"}
    columns, issues = infer_columns(frame, contract, types) if column_analysis is None else column_analysis(frame, table)
    counts = {}
    notes = list(table["notes"]) + issues
    for name, spec in schema.items():
        expressions = Counter(row[name].sql for row in rows if isinstance(row.get(name), Unevaluated))
        counts[name] = {
            "omitted": sum(name not in row for row in rows),
            "null": sum(name in row and row[name] is None for row in rows),
            "unevaluated": sum(expressions.values()),
            "valid": int(columns[name]["values"].notna().sum()),
        }
        if expressions:
            notes.append(f"{name} : expressions non évaluées exclues des statistiques : " + ", ".join(f"{value} ({count})" for value, count in expressions.items()))
        if counts[name]["omitted"]:
            notes.append(f"{name} : {counts[name]['omitted']} valeur(s) omise(s) ; défaut {spec['default'] or 'absent'} non appliqué.")
        if counts[name]["null"] and not spec["nullable"]:
            notes.append(f"{name} : NULL explicite incompatible avec NOT NULL, sans exécution SQL.")
    return {**table, "columns": columns, "counts": counts, "statistics": compute_statistics(columns), "notes": notes}


def render_sql_markdown(metadata, tables, inventory, begin, end):
    def escape(value):
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    def format_value(value, kind):
        if value is None or pd.isna(value):
            return "N/A"
        if kind == "DATE":
            return value.strftime("%Y-%m-%d")
        if kind in ("DATETIME", "DATETIME_UTC", "TIMESTAMP", "TIMESTAMPTZ", "TIME"):
            return value.isoformat() if kind != "TIME" else value.strftime("%H:%M")
        return str(value)

    size = float(metadata["size"])
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if size < 1024 or unit == "To":
            break
        size /= 1024
    lines = [f"# Carte d’identité SQL — {escape(metadata['source'].name)}", "",
             f"- Source: {metadata['source']}", f"- Filsize: {size:.2f} {unit}",
             f"- Charset: {metadata['charset']}", f"- ProcessBeginAt: {begin:%H:%M:%S}",
             f"- ProcessEndAt: {end:%H:%M:%S}", f"- Date: {begin:%Y-%m-%d} (Europe/Paris)",
             "- Dialect: PostgreSQL", f"- Tables Number: {len(tables)}",
             f"- Statements Number: {sum(inventory.values())}", "", "## Instructions", ""]
    lines.extend(f"- {kind}: {count}" for kind, count in inventory.items())
    lines += ["", "Analyse statique uniquement : les lignes comptées sont les tuples présents dans les INSERT, pas les lignes garanties en base. ON CONFLICT n’est pas appliqué. Les défauts (dont NOW()/CURRENT_TIMESTAMP) ne sont pas évalués.",
              ("Les types suivent les contrats Bronze v2 ; les colonnes omises sont décrites par le DDL. Les horloges déclarées sont conservées sans conversion. Les contraintes SQL sont décrites, sans exécution."
               if metadata.get('contract_based') else "Les types et contraintes SQL sont présentés sous leur forme normalisée par SQLGlot (par exemple NUMERIC devient DECIMAL). Les horodatages avec fuseau sont rendus en UTC. Les contraintes sont décrites, sans validation PostgreSQL complète."),
              "Les statistiques excluent les identifiants, les NULL, les valeurs omises, invalides ou non évaluées. N/A indique une statistique non applicable ou sans valeur exploitable. Les décimaux sont calculés sans conversion en float, avec une précision décimale d’au moins 28 chiffres pour les moyennes."]
    for name, table in tables.items():
        lines += ["", f"## Table {escape(name)}", "", f"- Rows Number: {len(table['rows'])}",
                  f"- Cols Number: {len(table['schema'])}",
                  "- Colonnes fournies par INSERT : " + "; ".join(str(len(names)) for names in table["insert_columns"]), "",
                  "### Column list", "", "| Colname | SQL Type | Infered Type | Nullable | Default | Constraints |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for col, spec in table["schema"].items():
            cells = [col, spec["sql_type"], spec["type"], "oui" if spec["nullable"] else "non", spec["default"] or "N/A", "; ".join(spec["constraints"]) or "N/A"]
            lines.append("| " + " | ".join(map(escape, cells)) + " |")
        if table["constraints"]:
            lines += ["", "Contraintes de table : " + "; ".join(map(escape, table["constraints"]))]
        lines += ["", "### Présence des valeurs", "", "| Colname | Valeurs valides | NULL explicites | Omises | Expressions non évaluées |",
                  "| --- | --- | --- | --- | --- |"]
        for col, counts in table["counts"].items():
            lines.append(f"| {escape(col)} | {counts['valid']} | {counts['null']} | {counts['omitted']} | {counts['unevaluated']} |")
        lines += ["", "### Statistiques", "", "| Col name | Min value | Max value | Mean value | Median value |", "| --- | --- | --- | --- | --- |"]
        for row in table["statistics"]:
            cells = [row["name"]] + [format_value(row[key], row["type"]) for key in ("min", "max", "mean", "median")]
            lines.append("| " + " | ".join(map(escape, cells)) + " |")
        lines += ["", "### Observations", ""] + ["- " + escape(note) for note in table["notes"] or ["Aucune anomalie de conversion détectée."]]
    if metadata["notes"]:
        lines += ["", "## Observations du fichier", ""] + ["- " + escape(note) for note in metadata["notes"]]
    return "\n".join(lines) + "\n"


def generate_sql_identity(source, output_stem=None, *, root=None, types_path=None):
    begin = datetime.now(PARIS)
    text, metadata = read_text_source(source)
    tables, inventory = parse_sql_source(text)
    types = load_type_catalog(types_catalog(types_path))
    tables = {name: analyze_table(table, types) for name, table in tables.items()}
    stem = output_stem or metadata["source"].stem
    if not stem or stem in (".", "..") or "/" in stem or "\\" in stem:
        raise ValueError("Nom de sortie invalide")
    end = datetime.now(PARIS)
    report = render_sql_markdown(metadata, tables, inventory, begin, end)
    output = project_root(root) / "artifacts" / "ingestion" / "identities" / begin.strftime("%Y%m%d") / f"{stem}_{begin:%H%M%S}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(report)
    return {"path": output, "tables": tables, "inventory": inventory, "begin": begin, "end": end,
            "notes": metadata["notes"] + [f"{name} : {note}" for name, table in tables.items() for note in table["notes"]]}

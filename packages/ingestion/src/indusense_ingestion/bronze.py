"""Préparer les colonnes Bronze à partir des contrats et des convertisseurs autorisés."""
import re

from .contracts import CONVERTERS, validate_options
from .silver import convert_column, source_hash


def resolve_specs(contract, columns):
    """Matérialiser les types pour le traitement, sans réécrire le YAML choisi."""
    result = []
    for column in columns:
        name = column["name"]
        spec = (contract or {}).get("columns", {}).get(name)
        if spec is None:
            spec = next(({key: value for key, value in rule.items() if key != "pattern"}
                         for rule in (contract or {}).get("column_rules", []) if re.search(rule["pattern"], name)),
                        {"type": column["type"]})
        result.append({"name": name, "spec": dict(spec)})
    return result


def validate_plan(columns, technical, types):
    names = [column["name"] for column in columns]
    generated = []
    for item in technical:
        if item["converter"] not in CONVERTERS or item["type"] not in types:
            raise ValueError("Convertisseur ou type de colonne technique inconnu")
        if types[item["type"]]["converter"] != item["converter"]:
            raise ValueError("Le type technique doit correspondre au convertisseur choisi")
        if item["source"] not in names:
            raise ValueError(f"Colonne source technique inconnue : {item['source']}")
        spec = {"type": item["type"], "nullable": item.get("nullable", True)}
        for key in ("format", "pattern"):
            if item.get(key) is not None:
                spec[key] = item[key]
        validate_options(spec)
        generated.append({"name": item["name"], "source": item["source"], "spec": spec})
    output = [value for name in names + [item["name"] for item in generated] for value in (name, name + "-type")] + ["hash"]
    if len(output) != len(set(output)) or "_row_id" in output:
        raise ValueError("Collision de noms entre les colonnes sources, techniques, hash ou les colonnes -type")
    if any(not name.strip() or "\x00" in name or len(name.encode("utf-8")) > 63 for name in output):
        raise ValueError("Chaque nom de colonne Bronze doit contenir entre 1 et 63 octets UTF-8, suffixe -type compris")
    return generated, output


def transform_bronze(records, columns, technical, types):
    generated, output_columns = validate_plan(columns, technical, types)
    outputs = [dict() for _ in records]
    errors = [[] for _ in records]
    specs = [{**column, "source": column["name"]} for column in columns] + generated
    for column in specs:
        name, spec = column["name"], column["spec"]
        values, issues = convert_column([row.get(column["source"]) for row in records], spec, types)
        for index, (value, issue) in enumerate(zip(values, issues)):
            outputs[index][name] = value
            outputs[index][name + "-type"] = spec["type"]
            if issue:
                errors[index].append({"column": name, "source_column": column["source"], "message": issue})
    for row, original in zip(outputs, records):
        row["hash"] = source_hash(original)
    return outputs, errors, output_columns

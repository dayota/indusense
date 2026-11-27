"""Contrats silver et transformation déterministe, sans écriture ni SQL dynamique."""

import hashlib
import json
import re
from decimal import Decimal

import pandas as pd
import yaml

from .contracts import CONVERTERS, UniqueKeyLoader, validate_configuration


def source_hash(data):
    # Clés absentes, NULL, nombres et chaînes restent distincts ; ordre des clés indépendant.
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(("indusense-row-v1\n" + canonical).encode("utf-8")).hexdigest()


def parse_contract(text, types, source_columns):
    config = yaml.load(text, Loader=UniqueKeyLoader)
    if not isinstance(config, dict):
        raise ValueError("Le contrat doit être un mapping YAML")
    try:
        json.dumps(config, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("Utiliser des valeurs YAML simples et finies ; entourer les dates de guillemets") from None
    base = {key: value for key, value in config.items() if key != "silver"}
    validate_configuration(base, types)
    resolved = {}
    for name in source_columns:
        spec = base["columns"].get(name)
        if spec is None:
            spec = next(({key: value for key, value in rule.items() if key != "pattern"}
                         for rule in base.get("column_rules", []) if re.search(rule["pattern"], name)), None)
        if spec is None:
            raise ValueError(f"Définir explicitement le type de {name} dans le contrat silver")
        resolved[name] = dict(spec)
    unknown = set(base["columns"]) - set(source_columns)
    if unknown:
        raise ValueError(f"Colonnes sources inconnues : {sorted(unknown)}")
    names = list(source_columns)
    output = [item for name in names for item in (name, name + "__type")] + ["hash"]
    if len(output) != len(set(output)):
        raise ValueError("Un nom source entre en collision avec hash ou une colonne __type")
    silver = config.get("silver", {})
    if not isinstance(silver, dict) or silver.keys() - {"anonymize", "technical_columns"}:
        raise ValueError("Options silver inconnues")
    # Les méthodes sont volontairement enregistrées ici, sans expression exécutable.
    anonymize = silver.get("anonymize", {})
    technical = silver.get("technical_columns", {})
    if not isinstance(anonymize, dict) or not isinstance(technical, dict):
        raise ValueError("anonymize et technical_columns doivent être des mappings")
    if anonymize or technical:
        raise ValueError("Méthodes d’anonymisation et colonnes techniques en cours de configuration")
    return config, resolved, output


def convert_column(values, spec, types):
    kind = spec["type"]
    options = {**types[kind], **spec}
    if "format" in spec and "pattern" not in spec:
        options.pop("pattern", None)
    expressions = [isinstance(value, (dict, list)) for value in values]
    normalized = [None if expression or value is None or (isinstance(value, str) and not value.strip())
                  else str(value) for value, expression in zip(values, expressions)]
    series = pd.Series(normalized, dtype="string")
    converter = options["converter"]
    if converter == "integer":
        # Éviter l’arrondi par float pour les grands identifiants numériques.
        converted = CONVERTERS["decimal"](series, options)
        converted = converted.map(lambda value: value if value is not None and value == value.to_integral_value() else None)
    else:
        converted = CONVERTERS[converter](series, options)
    if "allowed" in spec:
        converted = converted.where(converted.isin(spec["allowed"]))
    if "min" in spec:
        converted = converted.where(converted.ge(spec["min"]))
    if "max" in spec:
        converted = converted.where(converted.le(spec["max"]))
    result, errors = [], []
    for index, value in enumerate(converted):
        missing = pd.isna(value)
        error = ("Expression SQL non évaluée : fournir une valeur littérale" if expressions[index]
                 else f"Valeur incompatible avec {kind} ou ses contraintes" if normalized[index] is not None and missing
                 else "Valeur manquante interdite" if missing and not spec.get("nullable", True)
                 else None)
        errors.append(error)
        if missing:
            result.append(None)
        elif converter == "integer":
            result.append(int(value))
        elif converter == "number":
            result.append(float(value))
        elif converter == "boolean":
            result.append(bool(value))
        elif converter in ("datetime", "datetime_utc"):
            result.append(value.strftime(options["format"]))
        else:
            result.append(str(value) if isinstance(value, Decimal) else str(value))
    return result, errors


def transform(records, specs, types):
    """Produire les lignes valides et les erreurs de cellule sans altérer les sources."""
    transformed = [dict() for _ in records]
    issues = [[] for _ in records]
    for name, spec in specs.items():
        values, errors = convert_column([record.get(name) for record in records], spec, types)
        for index, (value, error) in enumerate(zip(values, errors)):
            transformed[index][name] = value
            transformed[index][name + "__type"] = spec["type"]
            if error:
                issues[index].append({"column": name, "message": error})
    for index, record in enumerate(records):
        transformed[index]["hash"] = source_hash(record)
    return transformed, issues

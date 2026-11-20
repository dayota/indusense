"""Configuration YAML et convertisseurs explicitement autorisés."""

import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import yaml


def string_values(series, options):
    return series.astype("string")


def number_values(series, options):
    values = pd.to_numeric(series, errors="coerce")
    return values.mask(values.isin([math.inf, -math.inf]))


def integer_values(series, options):
    values = number_values(series, options)
    return values.mask(values.mod(1).ne(0).fillna(False))


def datetime_values(series, options):
    values = pd.to_datetime(series, format=options["format"], errors="coerce", exact=True)
    if options.get("pattern"):
        values = values.where(series.str.fullmatch(options["pattern"]).fillna(False))
    return values


def decimal_values(series, options):
    def parse(value):
        if pd.isna(value):
            return None
        try:
            number = Decimal(str(value))
            return number if number.is_finite() else None
        except InvalidOperation:
            return None
    return series.map(parse).astype(object)


def utc_values(series, options):
    # Ne pas supposer le fuseau des valeurs naïves.
    explicit = series.where(series.str.contains(r"[T ]\d{2}:\d{2}.*(?:Z|[+-]\d{2}(?::?\d{2})?)$", regex=True).fillna(False))
    return pd.to_datetime(explicit, format="ISO8601", errors="coerce", utc=True)


def boolean_values(series, options):
    return series.str.lower().map({"true": True, "false": False}).astype("boolean")


CONVERTERS = {
    "string": string_values,
    "integer": integer_values,
    "number": number_values,
    "datetime": datetime_values,
    "decimal": decimal_values,
    "datetime_utc": utc_values,
    "boolean": boolean_values,
}


class UniqueKeyLoader(yaml.SafeLoader):
    """Refuser les clés dupliquées plutôt que masquer un contrat précédent."""


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError(f"Clé YAML dupliquée : {key}")
        result[key] = loader.construct_object(value_node)
    return result


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
)


def read_config(path):
    with Path(path).open(encoding="utf-8") as stream:
        config = yaml.load(stream, Loader=UniqueKeyLoader)
    if not isinstance(config, dict) or type(config.get("version")) is not int or config["version"] != 1:
        raise ValueError(f"Configuration {path} : version 1 requise")
    return config


def validate_options(options, *, type_definition=False):
    if not isinstance(options, dict):
        raise ValueError("Les options d’un type ou d’une colonne doivent être un mapping")
    allowed_keys = {"converter", "statistics", "format", "pattern"} if type_definition else {
        "type", "nullable", "required", "format", "pattern", "min", "max", "allowed"
    }
    if options.keys() - allowed_keys:
        raise ValueError(f"Options inconnues : {options.keys() - allowed_keys}")
    for flag in ("nullable", "required"):
        if flag in options and not isinstance(options[flag], bool):
            raise ValueError(f"{flag} doit être un booléen")
    if "allowed" in options and not isinstance(options["allowed"], list):
        raise ValueError("allowed doit être une liste")
    if "pattern" in options:
        if not isinstance(options["pattern"], str):
            raise ValueError("pattern doit être une chaîne")
        re.compile(options["pattern"])
    if "format" in options and (not isinstance(options["format"], str) or not options["format"]):
        raise ValueError("format doit être une chaîne non vide")
    for bound in ("min", "max"):
        if bound in options and (type(options[bound]) not in (int, float) or not math.isfinite(options[bound])):
            raise ValueError(f"{bound} doit être un nombre fini")
    if "min" in options and "max" in options and options["min"] > options["max"]:
        raise ValueError("min doit être inférieur ou égal à max")


def load_type_catalog(types_path):
    catalog = read_config(types_path)
    if catalog.keys() - {"version", "types"}:
        raise ValueError("Champs inconnus dans le catalogue")
    types = catalog.get("types")
    if not isinstance(types, dict):
        raise ValueError("Le catalogue doit définir types")
    for name, options in types.items():
        validate_options(options, type_definition=True)
        if options.get("converter") not in CONVERTERS:
            raise ValueError(f"Convertisseur inconnu pour {name}")
        statistics = options.get("statistics", [])
        if not isinstance(statistics, list) or any(s not in ("min", "max", "mean", "median") for s in statistics):
            raise ValueError(f"Statistiques inconnues pour {name}")
        if options["converter"] in ("string", "boolean") and statistics:
            raise ValueError("Les chaînes ne prennent pas de statistiques")
        if options["converter"] in ("datetime", "datetime_utc"):
            if not options.get("format") or any(s in statistics for s in ("mean", "median")):
                raise ValueError("Un type temporel exige un format et accepte seulement min/max")
    if not {"TEXT", "IDENTITY", "INTEGER", "FLOAT", "DATE", "TIME", "DATETIME"} <= types.keys():
        raise ValueError("Le catalogue doit conserver les types de base pour l’inférence")
    return types


def load_configuration(contract_path, types_path):
    types = load_type_catalog(types_path)
    contract = read_config(contract_path)
    if contract.keys() - {"version", "dataset", "columns", "column_rules", "extra_columns"}:
        raise ValueError("Champs inconnus dans le contrat")
    if not isinstance(contract.get("dataset"), str) or not contract["dataset"]:
        raise ValueError("Le contrat doit nommer son dataset")
    if contract.get("extra_columns", "infer") not in ("infer", "error"):
        raise ValueError("extra_columns doit valoir infer ou error")
    if not isinstance(contract.get("columns"), dict):
        raise ValueError("Le contrat doit définir columns")
    rules = contract.get("column_rules", [])
    if not isinstance(rules, list):
        raise ValueError("column_rules doit être une liste")
    for name in contract["columns"]:
        if not isinstance(name, str):
            raise ValueError("Les noms de colonnes doivent être des chaînes")
    for options in list(contract["columns"].values()) + rules:
        validate_options(options)
        kind = options.get("type")
        if kind not in types:
            raise ValueError(f"Type inconnu : {kind}")
        if any(bound in options for bound in ("min", "max")) and types[kind]["converter"] not in ("integer", "number", "decimal"):
            raise ValueError("Les bornes min/max sont réservées aux nombres")
    if any("pattern" not in rule for rule in rules):
        raise ValueError("Chaque règle de colonne exige un pattern")
    return contract, types

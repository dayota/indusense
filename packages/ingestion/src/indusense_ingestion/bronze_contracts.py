"""Validation v2 : erreurs agrégées, inspection injectable, aucun accès à la base."""
import difflib
import hashlib
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from .bronze_domain import SourceInspectionError, ValidationIssue
from .contracts import UniqueKeyLoader
from .bronze_sources import source_spec

COMPATIBILITY = {
    "IDENTIFIER": {"TEXT", "VARCHAR"}, "TEXT": {"TEXT", "VARCHAR"},
    "NUMBER": {"DOUBLE PRECISION", "REAL", "NUMERIC", "INTEGER", "BIGINT"},
    "INTEGER": {"INTEGER", "BIGINT", "SMALLINT"}, "DECIMAL": {"NUMERIC", "DECIMAL"},
    "BINARY": {"BOOLEAN", "SMALLINT", "INTEGER"}, "BOOLEAN": {"BOOLEAN"},
    "DATE": {"DATE"}, "TIME": {"TIME"}, "TIMESTAMP": {"TIMESTAMP"}, "TIMESTAMPTZ": {"TIMESTAMPTZ"},
}
METADATA_COLUMNS = {"_batch_id", "_source_file", "_source_hash", "_row_number", "_ingested_at", "_cast_errors", "_row_checksum"}
DEFAULT_MAX_CAST_ERROR_RATIO = 0.0


def parse_contracts(text):
    try:
        value = yaml.load(text, Loader=UniqueKeyLoader)
        configs = value if isinstance(value, list) else [value]
        if not configs or any(not isinstance(item, dict) for item in configs):
            raise ValueError("Un contrat ou une liste de contrats v2 est requis")
        json.dumps(configs, allow_nan=False)
        return configs
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        where = f"ligne {mark.line + 1}, colonne {mark.column + 1}: " if mark else ""
        raise ValueError(where + str(error)) from None


def config_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ValidateConfigService:
    def __init__(self, schema_path, inspector):
        self.validator = Draft202012Validator(json.loads(Path(schema_path).read_text()))
        self.inspector = inspector

    def validate(self, configs):
        issues, targets = [], set()
        for index, config in enumerate(configs):
            prefix = f"contracts[{index}]"
            errors = sorted(self.validator.iter_errors(config), key=lambda e: str(list(e.path)))
            issues.extend(ValidationIssue(prefix + "." + ".".join(map(str, error.path)), error.message) for error in errors)
            if errors:
                continue
            columns = config["columns"]
            names = [column["target_name"] for column in columns]
            derived = config.get("derived_columns", [])
            all_names = names + [column["target_name"] for column in derived]
            physical = names + [name + "_raw" for name in names] + list(METADATA_COLUMNS)
            if len(set(all_names)) != len(all_names):
                issues.append(ValidationIssue(prefix + ".columns", "duplicate target_name"))
            if len(set(physical)) != len(physical) or any(len(name.encode()) > 63 or "\x00" in name for name in physical):
                issues.append(ValidationIssue(prefix + ".columns", "Collision de miroir _raw, de métadonnée ou nom physique supérieur à 63 octets"))
            if len({column["source_name"] for column in columns}) != len(columns):
                issues.append(ValidationIssue(prefix + ".columns", "source_name dupliqué"))
            for item in config["target"]["natural_key"]:
                if item not in names:
                    issues.append(ValidationIssue(prefix + ".target.natural_key", f"{item!r} n'est pas une colonne cible déclarée"))
            for offset, column in enumerate(columns):
                sql_type = column["silver_type"].upper().split("(")[0].strip()
                if sql_type not in COMPATIBILITY[column["type"]]:
                    issues.append(ValidationIssue(f"{prefix}.columns[{offset}].silver_type", f"{sql_type} incompatible avec {column['type']}"))
            for offset, column in enumerate(derived):
                if set(column["operate_on_columns"]) - set(names):
                    issues.append(ValidationIssue(f"{prefix}.derived_columns[{offset}]", "operate_on_columns référence une colonne non déclarée"))
            target = config["target"]["table"]
            if target.startswith("_") or target in {"ingestion_batches_log", "alembic_version"}:
                issues.append(ValidationIssue(prefix + ".target.table", "Nom de table réservé"))
            if target in targets:
                issues.append(ValidationIssue(prefix + ".target.table", f"bronze.{target} est déjà produite par une autre configuration"))
            targets.add(target)
            try:
                schema = self.inspector.inspect(source_spec(config))
                known = {column.name: column.provided for column in schema.columns}
                declared = {column["source_name"] for column in columns}
                for name, provided in known.items():
                    if provided and name not in declared:
                        issues.append(ValidationIssue(prefix + ".columns", f"Colonne source {name!r} fournie mais non déclarée dans le contrat"))
                for offset, column in enumerate(columns):
                    name = column["source_name"]
                    message = None
                    if name not in known:
                        match = difflib.get_close_matches(name, known, n=1)
                        message = f"{name!r} absente du fichier {config['source']['path']}" + (f". Vouliez-vous dire {match[0]!r} ?" if match else "")
                    elif not known[name]:
                        message = f"{name!r} existe au DDL mais aucun INSERT ne la fournit ({config['source']['path']})"
                    if message:
                        issues.append(ValidationIssue(f"{prefix}.columns[{offset}].source_name", message))
                if schema.rows == 0:
                    issues.append(ValidationIssue(prefix + ".source.table", "Aucun INSERT : aucune donnée à ingérer"))
            except SourceInspectionError as error:
                issues.append(ValidationIssue(prefix + ".source", str(error)))
        return issues


def validate_or_raise(configs, root, inspector):
    issues = ValidateConfigService(Path(root) / "config/schema/bronze.v2.schema.json", inspector).validate(configs)
    if issues:
        raise ValueError("\n".join(f"{issue.location}: {issue.message}" for issue in issues))

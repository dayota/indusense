"""Lancer le moteur CSV ou PostgreSQL du projet sans dupliquer sa logique métier."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Aucun cache Python écrit avant le contrôle de branche, même lors des imports.
sys.dont_write_bytecode = True


def project_path(root, value):
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--contract", help="Contrat YAML obligatoire pour CSV, interdit pour SQL")
    parser.add_argument("--types", default="config/types.yaml")
    parser.add_argument("--output-root", default=".")
    parser.add_argument("--stem")
    args = parser.parse_args()
    root = Path(args.project).resolve(strict=True)
    branch = subprocess.run(
        ["git", "-C", str(root), "branch", "--show-current"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if branch == "main" or not branch:
        raise ValueError(
            "Branche main ou HEAD détachée : demander à l’utilisateur de créer ou "
            "sélectionner une branche et attendre son choix explicite avant toute écriture."
        )
    source = project_path(root, args.source)
    source_format = {".csv": "csv", ".sql": "sql"}.get(source.suffix.lower())
    if source_format is None:
        raise ValueError("Format non pris en charge : utiliser une source .csv ou .sql (PostgreSQL).")
    if source_format == "csv" and not args.contract:
        raise ValueError("--contract est obligatoire pour un CSV.")
    if source_format == "sql" and args.contract:
        raise ValueError("--contract ne s’applique pas au SQL : le schéma CREATE TABLE fait autorité.")
    for required in ("docs/ingestion-contracts.md", "packages/ingestion/src/indusense_ingestion/ingestion.py", "packages/ingestion/src/indusense_ingestion/contracts.py"):
        if not (root / required).is_file():
            raise ValueError(f"Projet d’ingestion introuvable : {required} absent dans {root}")
    stem = args.stem or source.stem
    if not stem or stem in (".", "..") or "/" in stem or "\\" in stem:
        raise ValueError("--stem doit être un nom de fichier simple")
    sys.path.insert(0, str(root / "packages/ingestion/src"))
    options = {"types_path": project_path(root, args.types), "root": project_path(root, args.output_root)}
    if source_format == "csv":
        from indusense_ingestion.ingestion import generate_identity

        result = generate_identity(source, stem, contract_path=project_path(root, args.contract), **options)
        summary = {"rows": result["rows"], "cols": result["cols"]}
    else:
        if not (root / "packages/ingestion/src/indusense_ingestion/sql_ingestion.py").is_file():
            raise ValueError("Module indusense_ingestion.sql_ingestion absent : le projet doit prendre en charge le SQL.")
        from sqlglot.errors import SqlglotError
        from indusense_ingestion.sql_ingestion import generate_sql_identity

        try:
            result = generate_sql_identity(source, stem, **options)
        except SqlglotError as error:
            raise ValueError(f"Analyse PostgreSQL impossible : {error}") from error
        summary = {
            "tables": {name: {"rows": len(table["rows"]), "cols": len(table["schema"])}
                       for name, table in result["tables"].items()},
            "inventory": result["inventory"],
        }
    print(json.dumps({"format": source_format, "path": str(result["path"]),
                      **summary, "notes": result["notes"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, ImportError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)

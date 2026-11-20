"""Lancer le moteur CSV du projet sans dupliquer sa logique métier."""

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
    parser.add_argument("--contract", required=True)
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
    if source.suffix.lower() != ".csv":
        raise ValueError("Seuls les CSV sont pris en charge ; le SQL est hors périmètre.")
    for required in ("docs/ingestion-contracts.md", "indusense/ingestion.py", "indusense/contracts.py"):
        if not (root / required).is_file():
            raise ValueError(f"Projet d’ingestion introuvable : {required} absent dans {root}")
    stem = args.stem or source.stem
    if not stem or stem in (".", "..") or "/" in stem or "\\" in stem:
        raise ValueError("--stem doit être un nom de fichier simple")
    sys.path.insert(0, str(root))
    from indusense.ingestion import generate_identity

    result = generate_identity(
        source, stem,
        contract_path=project_path(root, args.contract),
        types_path=project_path(root, args.types),
        root=project_path(root, args.output_root),
    )
    print(json.dumps({
        "path": str(result["path"]), "rows": result["rows"], "cols": result["cols"],
        "notes": result["notes"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, ImportError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)

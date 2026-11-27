"""Mettre à jour config/converters.yaml à partir du registre Python et des types."""

import argparse
from pathlib import Path

import yaml

from indusense_ingestion.converter_catalog import build_converter_catalog
from indusense_ingestion.paths import project_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Racine du projet contenant config/types.yaml")
    parser.add_argument("--check", action="store_true", help="Vérifier le catalogue sans écrire")
    args = parser.parse_args()
    root = project_root(args.root)
    output = root / "config/converters.yaml"
    content = (
        "# Généré par packages/ingestion/scripts/update_converters.py ; ne pas modifier à la main.\n"
        + yaml.safe_dump(build_converter_catalog(root / "config/types.yaml"), allow_unicode=True, sort_keys=False)
    )
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != content:
            parser.exit(1, "Catalogue absent ou obsolète : relancer le script sans --check.\n")
        print("Catalogue des convertisseurs à jour.")
        return
    output.write_text(content, encoding="utf-8")
    print(f"Catalogue mis à jour : {output}")


if __name__ == "__main__":
    main()

"""Résolution des ressources, indépendante du lieu d’installation."""
import os
from pathlib import Path


def project_root(value=None):
    if value is not None:
        return Path(value).resolve()
    configured = os.environ.get("INDUSENSE_PROJECT_ROOT")
    if configured:
        return Path(configured).resolve()
    current = Path.cwd().resolve()
    if current.name == "notebooks" and (current.parent / "config/types.yaml").is_file():
        current = current.parent
    if not (current / "config/types.yaml").is_file():
        raise ValueError("Définir INDUSENSE_PROJECT_ROOT ou lancer depuis la racine du projet.")
    return current


def types_catalog(value=None):
    return Path(value) if value is not None else project_root() / "config/types.yaml"

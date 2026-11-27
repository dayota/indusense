"""Recettes réutilisables du modèle ; les versions conservent leurs instantanés en base."""
import os
import re
import tempfile
from pathlib import Path

import sqlalchemy as sa
import yaml
from fastapi import HTTPException

from indusense_ingestion.bronze_contracts import parse_contracts
from .source_archive import checked_path, input_path
from .bronze_storage import normalized_name
from .. import catalog as db


def source_directory(connection, version_id):
    """Dossier de la version : contient inputs, _contracts et artifacts."""
    row = connection.execute(sa.select(db.preparations.c.archive_directory, db.models.c.name, db.model_versions.c.number)
        .select_from(db.model_versions.join(db.models, db.model_versions.c.model_id == db.models.c.id)
            .outerjoin(db.preparations, db.preparations.c.model_version_id == db.model_versions.c.id))
        .where(db.model_versions.c.id == version_id)).mappings().first()
    if row is None: raise HTTPException(404, "Version du modèle introuvable")
    return row['archive_directory'] or f"datas/ingestion/{normalized_name(row['name'])}/{row['number']}"


def source_path(connection, version_id, file, root):
    relative = input_path(source_directory(connection, version_id), file['filename'])
    checked_path(root, relative)
    return '/' + relative


def path_for(connection, version_id, file, root, table=None, *, contract_version='1.0.0', snapshot=False):
    directory = source_directory(connection, version_id)
    name = table if table is not None else Path(file['filename']).stem
    if not name or name in ('.', '..') or '/' in name or '\\' in name or any(ord(char) < 32 for char in name):
        raise ValueError("Le nom de table ne peut pas être utilisé comme nom de fichier contrat")
    if not isinstance(contract_version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', contract_version):
        raise ValueError('La version du contrat doit respecter le format majeur.mineur.correctif')
    parent = Path(directory) if snapshot else Path(directory).parent
    relative = str(parent / '_contracts' / (name + '-' + contract_version + '.yml'))
    return relative, checked_path(root, relative)


def available(connection, version_id, file, root, table=None):
    _, proposed = path_for(connection, version_id, file, root, table)
    name = table if table is not None else Path(file['filename']).stem
    pattern = re.compile(re.escape(name) + r'-([0-9]+\.[0-9]+\.[0-9]+)\.yml')
    result = []
    if proposed.parent.is_dir():
        for entry in sorted(proposed.parent.iterdir()):
            match = pattern.fullmatch(entry.name)
            if match:
                relative = str(entry.relative_to(Path(root)))
                path = checked_path(root, relative)
                if path.is_file(): result.append((relative, path, match[1]))
    # Les anciens noms restent lisibles jusqu'à leur prochaine sauvegarde.
    legacy = proposed.with_name(name + '.yml')
    if legacy.is_file():
        relative = str(legacy.relative_to(Path(root)))
        result.append((relative, checked_path(root, relative), None))
    return result


def version_key(version):
    if not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('La version du contrat doit respecter le format majeur.mineur.correctif')
    return tuple(map(int, version.split('.')))


def candidate_version(choice):
    if choice[2] is not None:
        return choice[2]
    configs = parse_contracts(choice[1].read_text(encoding='utf-8'))
    if len(configs) != 1:
        raise ValueError(f'{choice[0]}: un seul contrat est attendu')
    version = configs[0].get('version')
    version_key(version)
    return version


def latest(choices):
    return max(choices, key=lambda choice: (version_key(candidate_version(choice)), choice[2] is not None))


def read(connection, version_id, file, root, table=None, *, required=False, contract_version=None):
    choices = available(connection, version_id, file, root, table)
    if not choices:
        relative, _ = path_for(connection, version_id, file, root, table, contract_version=contract_version or '1.0.0')
        if required: raise ValueError(f"Contrat local absent : {relative}")
        return relative, None
    choice = latest(choices)
    if contract_version is not None and contract_version != candidate_version(choice):
        raise ValueError('Seule la version la plus récente du contrat peut être chargée')
    relative, path, filename_version = choice
    text = path.read_text(encoding='utf-8')
    configs = parse_contracts(text)
    if len(configs) != 1:
        raise ValueError(f"{relative}: un seul contrat est attendu dans ce fichier YAML")
    config = configs[0]
    if filename_version is not None and config.get('version') != filename_version:
        raise ValueError(f'{relative}: la version du nom de fichier ne correspond pas au contrat YAML')
    source = config.get('source', {})
    if source.get('format') != file['format'].upper() or (table is not None and source.get('table') != table):
        raise ValueError(f"{relative}: ce contrat ne correspond pas à la source ou à la table {table or file['filename']}")
    config['source']['path'] = source_path(connection, version_id, file, root)
    return relative, config


def write_yaml(path, config):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.contract-', delete=False) as stream:
            temporary = Path(stream.name)
            yaml.safe_dump(config, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def publish(connection, version_id, file, root, configs):
    paths = []
    model_directory = str(Path(source_directory(connection, version_id)).parent)
    # Plusieurs versions peuvent sauvegarder en parallèle : ne jamais rétrograder le modèle.
    connection.execute(sa.text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                       {'key': 'model-contracts:' + model_directory})
    for config in configs:
        table = config['source'].get('table') if file['format'] == 'sql' else None
        _, snapshot = path_for(connection, version_id, file, root, table,
                               contract_version=config['version'], snapshot=True)
        choices = available(connection, version_id, file, root, table)
        current = latest(choices) if choices else None
        if current is None or version_key(config['version']) >= version_key(candidate_version(current)):
            promoted = config
        else:
            # Une ancienne recette reste archivée pour la version qui l'utilise.
            parsed = parse_contracts(current[1].read_text(encoding='utf-8'))
            if len(parsed) != 1 or parsed[0].get('version') != candidate_version(current):
                raise ValueError(f'{current[0]}: la version du nom de fichier ne correspond pas au contrat YAML')
            promoted = parsed[0]
        write_yaml(snapshot, config)
        relative, path = path_for(connection, version_id, file, root, table, contract_version=promoted['version'])
        write_yaml(path, promoted)
        for _, old_path, _ in choices:
            if old_path != path:
                old_path.unlink()  # Le dossier du modèle ne conserve que la dernière version.
        sync_directory(path.parent)
        paths.append(relative)
    return paths

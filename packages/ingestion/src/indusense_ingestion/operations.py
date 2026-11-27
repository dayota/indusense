"""Registre fermé, validation, apprentissage explicite et application des opérations."""
import copy
import json
from pathlib import Path

import pandas as pd
from jsonschema import Draft202012Validator

from . import operation_methods as methods
from .contracts import read_config
from .paths import project_root


# Le YAML sélectionne un slug autorisé, jamais un import dynamique.
OPERATIONS = {
    'merge': ('MERGE', methods.merge),
    'normalize': ('NORM', methods.normalize),
    'standardize': ('STD', methods.standardize),
    'encode': ('ENC', methods.encode),
    'pseudonymize': ('ANO', methods.pseudonymize),
    'deduplicate': ('DEL', methods.deduplicate),
    'impute': ('IMP', methods.impute),
    'flag-outliers': ('OUT', methods.flag_outliers),
}


def operation_catalog(root=None):
    root = project_root(root)
    config = read_config(root / 'config/operations.yaml')
    schema = json.loads((root / 'config/schema/bronze.v2.schema.json').read_text(encoding='utf-8'))
    expected = schema['properties']['derived_columns']['items']['properties']['operation']['enum']
    entries = config.get('operations')
    if config.keys() != {'version', 'operations'} or not isinstance(entries, dict) or set(entries) != set(expected):
        raise ValueError('Le catalogue doit couvrir exactement les opérations du schéma Bronze')
    result = {}
    for code, entry in entries.items():
        if not isinstance(entry, dict) or entry.keys() != {'slug'} or entry.get('slug') not in OPERATIONS:
            raise ValueError(f'Slug d’opération inconnu pour {code}')
        registered_code, function = OPERATIONS[entry['slug']]
        if registered_code != code:
            raise ValueError(f'Le slug ne correspond pas à l’opération {code}')
        result[code] = {**entry, 'function': f'{function.__module__}.{function.__qualname__}'}
    return {'version': 1, 'operations': result}


def validate_specification(frame, specification, root):
    if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique or not frame.index.is_unique:
        raise ValueError('Un DataFrame avec colonnes et index uniques est requis')
    schema = json.loads((Path(root) / 'config/schema/bronze.v2.schema.json').read_text(encoding='utf-8'))
    validator = Draft202012Validator({'$defs': schema['$defs'], **schema['properties']['derived_columns']['items']})
    errors = sorted(validator.iter_errors(specification), key=lambda error: str(list(error.path)))
    if errors:
        raise ValueError('; '.join(f'{".".join(map(str, error.path))}: {error.message}' for error in errors))
    if not specification.get('parameters'):
        raise ValueError('Choisir explicitement la méthode et ses paramètres avant l’exécution')
    options = specification['parameters']
    names = specification['operate_on_columns']
    selected = set(names) | set(options.get('group_by', [])) | set(options.get('order_by', []))
    if selected - set(frame.columns):
        raise ValueError(f'Colonnes inconnues : {sorted(selected - set(frame.columns))}')
    if specification['target_name'] in frame.columns:
        raise ValueError('La cible ne doit pas écraser une colonne source')
    if specification['operation'] not in {'MERGE', 'DEL'} and len(names) != 1:
        raise ValueError('Cette opération attend exactement une colonne d’entrée')
    if specification['operation'] == 'ENC':
        if options['method'] == 'ordinal':
            keys = [methods.key([value]) for value in options['categories']]
            if len(set(keys)) != len(keys):
                raise ValueError('Les catégories ordinales doivent être distinctes')
    if specification['operation'] == 'IMP':
        for _, rows in methods.partitions(frame, options):
            methods.ordered(rows, options)
    if specification['operation'] == 'DEL' and options['method'] == 'key':
        if set(options['aggregations']) != set(frame.columns) - set(names):
            raise ValueError('Définir un agrégateur pour chaque colonne hors clé, sans supprimer de source implicitement')
    return specification


def fit_operation(training_frame, specification, *, root=None):
    """Produire un état JSON à conserver ; seul cet appel apprend sur l'entraînement."""
    root = project_root(root)
    catalog = operation_catalog(root)
    specification = copy.deepcopy(validate_specification(training_frame, specification, root))
    slug = catalog['operations'][specification['operation']]['slug']
    state = {'version': 1, 'slug': slug, 'specification': specification,
             'learned': methods.train(training_frame, specification)}
    # Les paramètres appris peuvent être sauvegardés hors du processus Python.
    return json.loads(json.dumps(state, ensure_ascii=False, allow_nan=False))


def apply_operation(frame, state, *, root=None, secrets=None):
    """Réutiliser un état appris, sans ajuster les paramètres aux nouvelles données."""
    root = project_root(root)
    catalog = operation_catalog(root)
    if not isinstance(state, dict) or state.get('version') != 1 or set(state) != {'version', 'slug', 'specification', 'learned'}:
        raise ValueError('État d’opération invalide')
    spec = validate_specification(frame, state['specification'], root)
    slug = catalog['operations'][spec['operation']]['slug']
    if slug != state['slug']:
        raise ValueError('Le slug ne correspond pas à l’état appris')
    learned = state['learned']
    if not isinstance(learned, dict):
        raise ValueError('Paramètres appris invalides')
    needs_groups = spec['operation'] in {'NORM', 'STD', 'ENC', 'OUT'} or (
        spec['operation'] == 'IMP' and spec['parameters']['method'] != 'forward-fill')
    if needs_groups and any(group not in learned for group, _ in methods.partitions(frame, spec['parameters'])):
        raise ValueError('Groupe absent de l’entraînement : aucun réapprentissage automatique')
    function = OPERATIONS[slug][1]
    return function(frame, spec, learned, secrets or {})

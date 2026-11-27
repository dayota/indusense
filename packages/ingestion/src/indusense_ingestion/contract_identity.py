"""Adapter les cartes existantes aux contrats v2, sans inférence ni transformation métier."""
import codecs
from datetime import datetime
from pathlib import PurePosixPath

import pandas as pd

from .bronze_engine import cast
from .bronze_sources import source_spec
from .contracts import load_type_catalog
from .ingestion import PARIS, compute_statistics, render_markdown
from .sql_ingestion import analyze_table, parse_sql_source, render_sql_markdown

SQL_TYPES = {'IDENTITY': 'IDENTIFIER', 'FLOAT': 'NUMBER', 'DATETIME': 'TIMESTAMP', 'DATETIME_UTC': 'TIMESTAMPTZ'}


def columns_from_contract(frame, definitions, types):
    columns, issues = {}, []
    for name in frame.columns:
        kind = definitions[name]['type']
        values, invalid = [], 0
        for raw in frame[name]:
            try:
                values.append(cast(None if pd.isna(raw) else raw, kind))
            except (ValueError, ArithmeticError, OverflowError):
                values.append(None)
                invalid += 1
        columns[name] = {'type': kind, 'options': types[kind], 'values': pd.Series(values, dtype=object)}
        if invalid:
            issues.append(f'{name} : {invalid} valeur(s) incompatible(s) avec {kind}, exclue(s) des statistiques.')
    return columns, issues


def generate_contract_identity(configs, inspector, types_path):
    """Retourner un Markdown ; l'adaptateur API choisit la destination et publie le fichier."""
    begin = datetime.now(PARIS)
    source = configs[0]['source']
    spec = source_spec(configs[0])
    path = inspector.path(spec)
    encoding = codecs.lookup(source['encoding']).name
    metadata = {'source': PurePosixPath(source['path']), 'size': path.stat().st_size,
                'charset': {'utf-8': 'UTF-8', 'utf-8-sig': 'UTF-8 avec BOM', 'iso8859-1': 'ISO-8859-1'}.get(encoding, encoding.upper()),
                'notes': [], 'contract_based': True}
    required = {column['type'] for config in configs for column in config['columns']}
    if source['format'] == 'CSV':
        types = load_type_catalog(types_path, required_types=required)
        records = list(inspector.rows(spec))
        frame = pd.DataFrame(records, columns=[column['source_name'] for column in configs[0]['columns']])
        definitions = {column['source_name']: column for column in configs[0]['columns']}
        columns, issues = columns_from_contract(frame, definitions, types)
        statistics = compute_statistics(columns)
        metadata.update(separator=source['field_delimiter'], notes=issues)
        report = render_markdown(metadata, frame, columns, statistics, begin, datetime.now(PARIS))
    else:
        tables, inventory = parse_sql_source(path.read_text(encoding=source['encoding']))
        recipes = {config['source']['table']: config for config in configs}
        if set(recipes) != set(tables):
            raise ValueError('Un contrat est requis pour chaque table SQL')
        for name, table in tables.items():
            definitions = {column['source_name']: column for column in recipes[name]['columns']}
            for column, definition in table['schema'].items():
                # Les colonnes omises restent documentées, sans évaluer les valeurs par défaut.
                definition['type'] = definitions.get(column, {}).get('type', SQL_TYPES.get(definition['type'], definition['type']))
                required.add(definition['type'])
        types = load_type_catalog(types_path, required_types=required)
        analyses = {}
        for name, table in tables.items():
            analyses[name] = analyze_table(table, types, column_analysis=lambda frame, current:
                columns_from_contract(frame, current['schema'], types))
        report = render_sql_markdown(metadata, analyses, inventory, begin, datetime.now(PARIS))
    # Le libellé historique est conservé ; les types sont ceux validés du contrat v2.
    return report + '\nTypes issus des contrats Bronze v2 validés. Colonnes dérivées non exécutées ; aucune conversion d’horloge.\n'

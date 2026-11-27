"""Méthodes pures de préparation ; aucun accès disque, SQL, secret ou apprentissage implicite."""
import hashlib
import hmac
import json
import math
from datetime import date, datetime, time

import pandas as pd


def scalar(value):
    if pd.isna(value):
        return None
    if hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if not isinstance(value, (str, int, float, bool)):
        raise ValueError('Une valeur scalaire JSON est requise')
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Une valeur finie est requise')
    return value


def key(values):
    # Préserver les distinctions entre chaînes, nombres, booléens et NULL.
    return json.dumps([[type(scalar(value)).__name__, scalar(value)] for value in values],
                      ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def numeric(series):
    values = pd.to_numeric(series, errors='raise').astype('Float64')
    if values.dropna().isin([math.inf, -math.inf]).any():
        raise ValueError('Les valeurs infinies ne sont pas acceptées')
    return values


def partitions(frame, parameters):
    names = parameters.get('group_by', [])
    if not names:
        return [('[]', frame)]
    groups = {}
    for position, values in enumerate(frame[names].itertuples(index=False, name=None)):
        groups.setdefault(key(values), []).append(position)
    return [(name, frame.iloc[positions]) for name, positions in groups.items()]


def train(frame, spec):
    """Apprendre seulement à partir du DataFrame explicitement fourni comme entraînement."""
    code, options = spec['operation'], spec['parameters']
    column = spec['operate_on_columns'][0]
    learned = {}
    if code not in {'NORM', 'STD', 'ENC', 'IMP', 'OUT'}:
        return learned
    if code == 'IMP' and options['method'] == 'forward-fill':
        return learned
    for group, rows in partitions(frame, options):
        if code == 'ENC':
            categories = options.get('categories')
            if options['method'] == 'one-hot':
                # Ordre indépendant de l'ordre physique des lignes d'entraînement.
                categories = sorted({key([value]): scalar(value) for value in rows[column].dropna()}.items())
                categories = [value for _, value in categories]
            known = [key([value]) for value in categories]
            if not known:
                raise ValueError('Aucune catégorie d’entraînement pour l’encodage')
            if any(key([value]) not in known for value in rows[column].dropna()):
                raise ValueError('Une catégorie d’entraînement manque dans l’ordre ordinal explicite')
            learned[group] = {'categories': categories}
            continue
        values = numeric(rows[column]).dropna()
        if values.empty:
            raise ValueError('Aucune valeur d’entraînement pour apprendre les paramètres')
        if code == 'NORM':
            learned[group] = {'minimum': float(values.min()), 'maximum': float(values.max())}
        elif code == 'STD' or (code == 'OUT' and options['method'] == 'z-score'):
            learned[group] = {'mean': float(values.mean()), 'std': float(values.std(ddof=options['ddof']))}
        elif code == 'IMP':
            learned[group] = {'fill': float(getattr(values, options['method'])())}
        elif options['method'] == 'iqr':
            learned[group] = {'q1': float(values.quantile(.25)), 'q3': float(values.quantile(.75))}
        else:
            median = float(values.median())
            learned[group] = {'median': median, 'mad': float((values - median).abs().median())}
        if code == 'NORM' and learned[group]['minimum'] == learned[group]['maximum']:
            raise ValueError('Normalisation impossible : étendue nulle')
        if 'std' in learned[group] and (not math.isfinite(learned[group]['std']) or learned[group]['std'] <= 0):
            raise ValueError('Écart-type nul ou indéfini : choisir une autre méthode')
        if 'mad' in learned[group] and learned[group]['mad'] == 0:
            raise ValueError('MAD nul : choisir une autre méthode')
        if 'q1' in learned[group] and learned[group]['q1'] == learned[group]['q3']:
            raise ValueError('IQR nul : choisir une autre méthode')
    return learned


def add_column(frame, name, values):
    if name in frame.columns:
        raise ValueError(f'Colonne cible déjà présente : {name}')
    if not name or len(name.encode('utf-8')) > 63:
        raise ValueError('Le nom de colonne produit doit contenir entre 1 et 63 octets')
    frame[name] = values


def merge(frame, spec, learned, secrets):
    options, target = spec['parameters'], spec['target_name']
    columns = spec['operate_on_columns']
    if options['method'] == 'concat':
        result = frame[columns].apply(
            lambda row: None if row.isna().any() else options['separator'].join(str(value) for value in row), axis=1)
    else:
        if len(columns) != 2:
            raise ValueError('La fusion date/heure exige exactement deux colonnes, dans cet ordre')
        def combine(row):
            if row.isna().any():
                return None
            day = date.fromisoformat(str(row.iloc[0]))
            hour = time.fromisoformat(str(row.iloc[1]))
            if hour.tzinfo is not None and hour.utcoffset().total_seconds() != 0:
                raise ValueError('Horloge UTC déclarée : aucun décalage ni conversion autorisé')
            from datetime import timezone
            return datetime.combine(day, hour).replace(tzinfo=timezone.utc)
        result = frame[columns].apply(combine, axis=1)
    output = frame.copy(deep=True)
    add_column(output, target, result)
    return output


def numeric_transform(frame, spec, learned, secrets):
    output = frame.copy(deep=True)
    result = pd.Series(pd.NA, index=frame.index, dtype='Float64')
    for group, rows in partitions(frame, spec['parameters']):
        stats = learned[group]
        values = numeric(rows[spec['operate_on_columns'][0]])
        if spec['operation'] == 'NORM':
            values = (values - stats['minimum']) / (stats['maximum'] - stats['minimum'])
        else:
            values = (values - stats['mean']) / stats['std']
        result.loc[rows.index] = values
    add_column(output, spec['target_name'], result)
    return output


def normalize(frame, spec, learned, secrets):
    return numeric_transform(frame, spec, learned, secrets)


def standardize(frame, spec, learned, secrets):
    return numeric_transform(frame, spec, learned, secrets)


def encode(frame, spec, learned, secrets):
    output = frame.copy(deep=True)
    options, target, column = spec['parameters'], spec['target_name'], spec['operate_on_columns'][0]
    categories = learned['[]']['categories']
    keys = [key([value]) for value in categories]
    encoded = frame[column].map(lambda value: None if pd.isna(value) else key([value]))
    if any(pd.notna(value) and value not in keys for value in encoded):
        raise ValueError('Catégorie inconnue : réviser explicitement le contrat, aucun réapprentissage automatique')
    if options['method'] == 'ordinal':
        mapping = {value: rank for rank, value in enumerate(keys)}
        add_column(output, target, encoded.map(mapping).astype('Int64'))
    else:
        start = 1 if options['drop_first'] else 0
        for rank in range(start, len(keys)):
            values = encoded.map(lambda value: pd.NA if pd.isna(value) else int(value == keys[rank])).astype('Int64')
            add_column(output, f'{target}_{rank}', values)
    return output


def pseudonymize(frame, spec, learned, secrets):
    secret = secrets.get(spec['parameters']['secret_ref'])
    if not isinstance(secret, bytes) or not secret.strip():
        raise ValueError('Le secret de pseudonymisation doit être fourni séparément et être non vide')
    def digest(value):
        if pd.isna(value):
            return None
        return hmac.new(secret, key([value]).encode('utf-8'), hashlib.sha256).hexdigest()
    output = frame.copy(deep=True)
    add_column(output, spec['target_name'], frame[spec['operate_on_columns'][0]].map(digest))
    return output


def deduplicate(frame, spec, learned, secrets):
    options, target = spec['parameters'], spec['target_name']
    if target in frame.columns:
        raise ValueError(f'Colonne cible déjà présente : {target}')
    if not target or len(target.encode('utf-8')) > 63:
        raise ValueError('Le compteur doit avoir un nom de 1 à 63 octets')
    columns = spec['operate_on_columns']
    groups = {}
    for position, values in enumerate(frame[columns].itertuples(index=False, name=None)):
        groups.setdefault(key(values), []).append(position)
    records = []
    for positions in groups.values():
        rows = frame.iloc[positions]
        if options['method'] == 'strict':
            # Aucune perte silencieuse d'une colonne hors du sous-ensemble sélectionné.
            if len({key(values) for values in rows.itertuples(index=False, name=None)}) != 1:
                raise ValueError('Doublons de clé avec valeurs différentes : choisir la méthode key et des agrégateurs')
            record = rows.iloc[0].to_dict()
        else:
            record = {name: rows.iloc[0][name] for name in columns}
            for name, strategy in options['aggregations'].items():
                values = rows[name].dropna()
                if strategy == 'identical':
                    unique = {key([value]) for value in rows[name]}
                    if len(unique) != 1:
                        raise ValueError(f'Valeurs différentes dans {name} : choisir un agrégateur')
                    record[name] = rows.iloc[0][name]
                else:
                    values = numeric(values)
                    record[name] = None if values.empty else getattr(values, strategy)()
        record[target] = len(rows)
        records.append(record)
    return pd.DataFrame(records, columns=[*frame.columns, target])


def ordered(rows, options):
    columns = options['order_by']
    if rows[columns].isna().any().any() or rows.duplicated(columns).any():
        raise ValueError('L’ordre doit être complet et unique dans chaque groupe')
    return rows.sort_values(columns, kind='stable')


def impute(frame, spec, learned, secrets):
    options, target, column = spec['parameters'], spec['target_name'], spec['operate_on_columns'][0]
    output = frame.copy(deep=True)
    result = frame[column].copy() if options['method'] == 'forward-fill' else numeric(frame[column])
    flag = pd.Series(False, index=frame.index, dtype='boolean')
    for group, rows in partitions(frame, options):
        rows = ordered(rows, options)
        values = rows[column].copy() if options['method'] == 'forward-fill' else numeric(rows[column])
        missing = values.isna()
        runs = missing.ne(missing.shift()).cumsum()
        lengths = missing.groupby(runs).transform('sum')
        eligible = missing & lengths.le(options['max_gap_rows'])
        if options['method'] == 'forward-fill':
            replacement = values.ffill()
        else:
            numeric(values)  # Refuser les chaînes non numériques au lieu de les coercer.
            replacement = pd.Series(learned[group]['fill'], index=values.index)
        corrected = values.where(~eligible, replacement)
        result.loc[rows.index] = corrected
        flag.loc[rows.index] = missing & corrected.notna()
    add_column(output, target, result)
    add_column(output, target + '_is_imputed', flag)
    return output


def flag_outliers(frame, spec, learned, secrets):
    options, column = spec['parameters'], spec['operate_on_columns'][0]
    result = pd.Series(pd.NA, index=frame.index, dtype='boolean')
    for group, rows in partitions(frame, options):
        values = numeric(rows[column])
        stats = learned[group]
        if options['method'] == 'iqr':
            width = (stats['q3'] - stats['q1']) * options['threshold']
            flags = values.lt(stats['q1'] - width) | values.gt(stats['q3'] + width)
        elif options['method'] == 'z-score':
            flags = ((values - stats['mean']) / stats['std']).abs().gt(options['threshold'])
        else:
            flags = ((values - stats['median']).abs() / stats['mad']).gt(options['threshold'])
        result.loc[rows.index] = flags
    output = frame.copy(deep=True)
    add_column(output, spec['target_name'], result)
    return output

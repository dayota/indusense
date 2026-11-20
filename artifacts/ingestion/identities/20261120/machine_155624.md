# Carte d’identité SQL — machine.sql

- Source: /home/ybourdea/PycharmProjects/indusense/datas/machine.sql
- Filsize: 22.41 Ko
- Charset: UTF-8
- ProcessBeginAt: 15:56:24
- ProcessEndAt: 15:56:24
- Date: 2026-11-20 (Europe/Paris)
- Dialect: PostgreSQL
- Tables Number: 2
- Statements Number: 10

## Instructions

- Transaction: 1
- CREATE TABLE: 2
- CREATE INDEX: 4
- INSERT VALUES: 2
- Commit: 1

Analyse statique uniquement : les lignes comptées sont les tuples présents dans les INSERT, pas les lignes garanties en base. ON CONFLICT n’est pas appliqué. Les défauts (dont NOW()/CURRENT_TIMESTAMP) ne sont pas évalués.
Les types et contraintes SQL sont présentés sous leur forme normalisée par SQLGlot (par exemple NUMERIC devient DECIMAL). Les horodatages avec fuseau sont rendus en UTC. Les contraintes sont décrites, sans validation PostgreSQL complète.
Les statistiques excluent les identifiants, les NULL, les valeurs omises, invalides ou non évaluées. N/A indique une statistique non applicable ou sans valeur exploitable. Les décimaux sont calculés sans conversion en float, avec une précision décimale d’au moins 28 chiffres pour les moyennes.

## Table machine

- Rows Number: 15
- Cols Number: 11
- Colonnes fournies par INSERT : 8

### Column list

| Colname | SQL Type | Infered Type | Nullable | Default | Constraints |
| --- | --- | --- | --- | --- | --- |
| machine_code | VARCHAR(16) | IDENTITY | non | N/A | PRIMARY KEY |
| commissioning_date | DATE | DATE | non | N/A | NOT NULL |
| max_daily_capacity | INT | INTEGER | non | N/A | NOT NULL; CHECK (max_daily_capacity > 0) |
| max_hourly_capacity_pieces | INT | INTEGER | non | N/A | NOT NULL; CHECK (max_hourly_capacity_pieces > 0) |
| model | VARCHAR(32) | TEXT | non | N/A | NOT NULL |
| production_line | VARCHAR(16) | TEXT | non | N/A | NOT NULL |
| location | VARCHAR(16) | TEXT | non | N/A | NOT NULL |
| criticality | VARCHAR(8) | TEXT | non | N/A | NOT NULL; CHECK (criticality IN ('LOW', 'MEDIUM', 'HIGH')) |
| is_active | BOOLEAN | BOOLEAN | non | TRUE | NOT NULL; DEFAULT TRUE |
| created_at | TIMESTAMPTZ | DATETIME_UTC | non | CURRENT_TIMESTAMP | NOT NULL; DEFAULT CURRENT_TIMESTAMP |
| updated_at | TIMESTAMPTZ | DATETIME_UTC | non | CURRENT_TIMESTAMP | NOT NULL; DEFAULT CURRENT_TIMESTAMP |

### Présence des valeurs

| Colname | Valeurs valides | NULL explicites | Omises | Expressions non évaluées |
| --- | --- | --- | --- | --- |
| machine_code | 15 | 0 | 0 | 0 |
| commissioning_date | 15 | 0 | 0 | 0 |
| max_daily_capacity | 15 | 0 | 0 | 0 |
| max_hourly_capacity_pieces | 15 | 0 | 0 | 0 |
| model | 15 | 0 | 0 | 0 |
| production_line | 15 | 0 | 0 | 0 |
| location | 15 | 0 | 0 | 0 |
| criticality | 15 | 0 | 0 | 0 |
| is_active | 0 | 0 | 15 | 0 |
| created_at | 0 | 0 | 15 | 0 |
| updated_at | 0 | 0 | 15 | 0 |

### Statistiques

| Col name | Min value | Max value | Mean value | Median value |
| --- | --- | --- | --- | --- |
| commissioning_date | 2019-07-23 | 2025-05-25 | N/A | N/A |
| max_daily_capacity | 750 | 1428 | 1054.8666666666666 | 1027.0 |
| max_hourly_capacity_pieces | 47 | 89 | 65.86666666666666 | 64.0 |
| created_at | N/A | N/A | N/A | N/A |
| updated_at | N/A | N/A | N/A | N/A |

### Observations

- ON CONFLICT décrit mais non appliqué : ON CONFLICT(machine_code) DO UPDATE SET commissioning_date = excluded.commissioning_date, max_daily_capacity = excluded.max_daily_capacity, max_hourly_capacity_pieces = excluded.max_hourly_capacity_pieces, model = excluded.model, production_line = excluded.production_line, location = excluded.location, criticality = excluded.criticality, updated_at = CURRENT_TIMESTAMP
- is_active : 15 valeur(s) omise(s) ; défaut TRUE non appliqué.
- created_at : 15 valeur(s) omise(s) ; défaut CURRENT_TIMESTAMP non appliqué.
- updated_at : 15 valeur(s) omise(s) ; défaut CURRENT_TIMESTAMP non appliqué.

## Table maintenance

- Rows Number: 115
- Cols Number: 11
- Colonnes fournies par INSERT : 9

### Column list

| Colname | SQL Type | Infered Type | Nullable | Default | Constraints |
| --- | --- | --- | --- | --- | --- |
| maintenance_id | INT | IDENTITY | non | N/A | PRIMARY KEY |
| machine_code | VARCHAR(16) | IDENTITY | non | N/A | NOT NULL; REFERENCES machine (machine_code) ON DELETE RESTRICT |
| maintenance_at | TIMESTAMPTZ | DATETIME_UTC | non | N/A | NOT NULL |
| maintenance_type | VARCHAR(16) | TEXT | non | N/A | NOT NULL; CHECK (maintenance_type IN ('proactive', 'reactive')) |
| action_type | VARCHAR(32) | TEXT | non | N/A | NOT NULL |
| component | VARCHAR(64) | TEXT | non | N/A | NOT NULL |
| description | TEXT | TEXT | non | N/A | NOT NULL |
| related_incident_id | VARCHAR(16) | IDENTITY | oui | N/A | N/A |
| duration_hours | DECIMAL(6, 2) | DECIMAL | non | N/A | NOT NULL; CHECK (duration_hours > 0) |
| created_at | TIMESTAMPTZ | DATETIME_UTC | non | CURRENT_TIMESTAMP | NOT NULL; DEFAULT CURRENT_TIMESTAMP |
| updated_at | TIMESTAMPTZ | DATETIME_UTC | non | CURRENT_TIMESTAMP | NOT NULL; DEFAULT CURRENT_TIMESTAMP |

### Présence des valeurs

| Colname | Valeurs valides | NULL explicites | Omises | Expressions non évaluées |
| --- | --- | --- | --- | --- |
| maintenance_id | 115 | 0 | 0 | 0 |
| machine_code | 115 | 0 | 0 | 0 |
| maintenance_at | 115 | 0 | 0 | 0 |
| maintenance_type | 115 | 0 | 0 | 0 |
| action_type | 115 | 0 | 0 | 0 |
| component | 115 | 0 | 0 | 0 |
| description | 115 | 0 | 0 | 0 |
| related_incident_id | 25 | 90 | 0 | 0 |
| duration_hours | 115 | 0 | 0 | 0 |
| created_at | 0 | 0 | 115 | 0 |
| updated_at | 0 | 0 | 115 | 0 |

### Statistiques

| Col name | Min value | Max value | Mean value | Median value |
| --- | --- | --- | --- | --- |
| maintenance_at | 2025-06-15T06:00:00+00:00 | 2026-05-30T22:00:00+00:00 | N/A | N/A |
| duration_hours | 1.0 | 8.0 | 2.943043478260869565217391304 | 2.64 |
| created_at | N/A | N/A | N/A | N/A |
| updated_at | N/A | N/A | N/A | N/A |

### Observations

- ON CONFLICT décrit mais non appliqué : ON CONFLICT(maintenance_id) DO UPDATE SET machine_code = excluded.machine_code, maintenance_at = excluded.maintenance_at, maintenance_type = excluded.maintenance_type, action_type = excluded.action_type, component = excluded.component, description = excluded.description, related_incident_id = excluded.related_incident_id, duration_hours = excluded.duration_hours, updated_at = CURRENT_TIMESTAMP
- created_at : 115 valeur(s) omise(s) ; défaut CURRENT_TIMESTAMP non appliqué.
- updated_at : 115 valeur(s) omise(s) ; défaut CURRENT_TIMESTAMP non appliqué.

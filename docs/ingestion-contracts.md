# Réutiliser les cartes d’identité CSV et SQL

Le [notebook](../notebooks/sprint1.ipynb) lance le traitement du [module d’ingestion](../scripts/ingestion.py). Installer les dépendances avec `uv sync` avant de l’exécuter.

## Utiliser le skill dataset-identity

Le [skill dataset-identity](../skills/dataset-identity/SKILL.md) accompagne l’examen d’un CSV ou d’un script PostgreSQL et la génération de son rapport. Pour un CSV, il crée ou adapte le contrat YAML ; pour un SQL, le schéma déclaré détermine le contrat en mémoire. Sa source est versionnée dans le dépôt ; son installation personnelle se trouve dans `$CODEX_HOME/skills/dataset-identity` ou, par défaut, `~/.codex/skills/dataset-identity`.

Exemple d’invocation dans une session disposant du skill :

```text
$dataset-identity Crée une carte d’identité pour datas/ventes.csv dans ce projet.
$dataset-identity Crée une carte d’identité pour datas/machine.sql sans exécuter le SQL.
```

La sélection automatique reste autorisée. Si le skill n’apparaît pas dans une session déjà ouverte, ouvrir une nouvelle session ; son [point d’entrée versionné](../skills/dataset-identity/SKILL.md) peut aussi être fourni explicitement à l’agent.

Le skill demande seulement les précisions nécessaires, par exemple pour un format de date ambigu ou un dialecte SQL incertain. Il ne déduit pas les contraintes métier de la seule distribution des données et n’effectue pas de commit ou push sans demande. Le parcours SQL est détaillé dans une [référence dédiée](../skills/dataset-identity/references/sql.md), chargée seulement pour ce format.

Le [lanceur du skill](../skills/dataset-identity/scripts/run_identity.py) utilise le moteur existant et refuse toute génération sur `main` ou en HEAD détachée. Exemple depuis la racine, avec `uv run python` ou l’interpréteur configuré du projet :

```bash
uv run python -B skills/dataset-identity/scripts/run_identity.py --project . --source datas/releves_incidents.csv --contract config/contracts/incidents.yaml
uv run python -B skills/dataset-identity/scripts/run_identity.py --project . --source datas/machine.sql
```

Le lanceur choisit CSV ou PostgreSQL par l’extension du fichier, sans tenir compte de la casse. `--contract` est obligatoire pour les CSV et refusé pour le SQL ; `--types`, `--output-root` et `--stem` fonctionnent dans les deux parcours. Les autres extensions sont refusées. La sortie JSON donne `path`, `format` et `notes`, puis `rows`/`cols` pour les CSV ou `tables` (dimensions par table) et `inventory` pour le SQL.

Ce contrôle complète les consignes de l’agent, qui s’appliquent aussi avant d’écrire le contrat. Le [bilan initial](sprints/1/challenge1-skill-validation.md) et le [bilan de l’extension SQL](sprints/1/challenge2-skill-validation.md) distinguent les essais automatisés du lanceur et la revue des consignes.

## Configuration

- [types.yaml](../config/types.yaml) définit les types, leurs convertisseurs, les formats temporels et les statistiques applicables.
- Les [contrats](../config/contracts/) décrivent les colonnes de chaque dataset. Les noms sont sensibles à la casse.
- Les convertisseurs sont des fonctions Python du [registre explicite](../scripts/contracts.py). Le YAML référence leur nom ; il ne peut pas importer ou exécuter une fonction arbitraire.

Les fichiers portent `version: 1`. Le chargement repose sur un dérivé de `yaml.SafeLoader` refusant aussi les clés dupliquées ([documentation PyYAML](https://pyyaml.org/wiki/PyYAMLDocumentation)). Un type, un convertisseur ou une option inconnus sont refusés avant la lecture du CSV.

## Ajouter un dataset

Créer un contrat YAML, par exemple :

```yaml
version: 1
dataset: ventes
extra_columns: infer
columns:
  reference:
    type: IDENTITY
    nullable: false
  jour:
    type: DATE
    format: "%d/%m/%Y"
    pattern: '\d{2}/\d{2}/\d{4}'
  montant:
    type: FLOAT
    min: 0
  commentaire:
    type: TEXT
    required: false
```

Puis appeler depuis le notebook :

```python
generate_identity(
    ROOT / "datas" / "ventes.csv",
    "ventes",
    contract_path=ROOT / "config" / "contracts" / "ventes.yaml",
)
```

`types_path` permet de choisir un autre catalogue et `root` de choisir une autre racine de sortie. Les chemins sont résolus par rapport au répertoire courant ; le notebook fournit des chemins absolus via `ROOT`.

## Priorités et validation

1. Une colonne explicitement nommée dans le contrat est prioritaire.
2. Sinon, la première règle `column_rules` correspondante s’applique ; son `pattern` sélectionne le nom de colonne.
3. Sinon, `extra_columns: infer` infère le type ; `extra_columns: error` refuse la colonne.

Les options d’une colonne remplacent les valeurs par défaut du type. Une surcharge de `format` sans `pattern` désactive le motif par défaut ; fournir aussi un `pattern` pour imposer strictement la forme du texte. Les types temporels inférés sont DATE, TIME et DATETIME, suivis des entiers et des flottants. Les noms terminant par `_id` ou `_badge` sont inférés comme identifiants. Les types personnalisés sont sélectionnés explicitement dans le contrat.

Chaque colonne déclarée est obligatoire par défaut (`required: false` autorise son absence). `nullable: false` signale les cellules manquantes sans arrêter le rapport. Les valeurs non convertibles ou hors contraintes (`allowed`, bornes numériques `min`/`max`) sont signalées puis exclues des statistiques. Les cellules vides et les espaces sont manquants ; les autres textes sont préservés. Les identifiants conservent leurs zéros initiaux.

Exemple de règle du contrat incidents :

```yaml
column_rules:
  - pattern: '^type_'
    type: INTEGER
    allowed: [0, 1]
```

## Étendre les types

Un nouveau type peut réutiliser un convertisseur (`string`, `integer`, `number`, `datetime`) :

```yaml
  PRICE:
    converter: number
    statistics: [min, max, mean, median]
```

Pour un comportement de conversion nouveau, ajouter une fonction Python au registre puis la référencer dans le catalogue. Les types temporels exigent un format et acceptent min/max ; les chaînes n’ont pas de statistiques. Les types de base restent nécessaires pour l’inférence automatique.

Les sorties restent horodatées à Paris et une sortie existante n’est pas écrasée. Les rapports historiques sont conservés.

Le catalogue contient aussi `DECIMAL` (convertisseur `decimal`), `BOOLEAN` (`boolean`) et `DATETIME_UTC` (`datetime_utc`). Les décimaux restent des `Decimal` pour les calculs et le rendu ; les booléens n’ont pas de statistiques numériques. `DATETIME_UTC` accepte des horodatages ISO 8601 avec fuseau explicite, les convertit en UTC et refuse les valeurs naïves ; son option `format` concerne le rendu CSV, pas le format d’entrée ISO 8601. Les types ajoutés ne participent pas à l’inférence automatique CSV : un contrat ou le schéma SQL les choisit explicitement.

## Carte d’identité PostgreSQL

Le [module SQL](../scripts/sql_ingestion.py) analyse un script avec SQLGlot, sans exécuter de SQL ni se connecter à une base. Le choix du parseur et les vérifications sont décrits dans le [bilan du challenge 2](sprints/1/challenge2-validation.md). Le skill `dataset-identity` réutilise ce même module pour son parcours SQL.

Depuis le notebook, après la cellule définissant `ROOT` :

```python
from scripts.sql_ingestion import generate_sql_identity

sql_report = generate_sql_identity(ROOT / "datas" / "machine.sql", root=ROOT)
print(sql_report["path"])
for name, table in sql_report["tables"].items():
    print(name, len(table["rows"]), len(table["schema"]))
```

Le rapport est enregistré sous `artifacts/ingestion/identities/YYYYMMDD/machine_HHMMSS.md`. Les paramètres `root`, `output_stem` et `types_path` permettent de personnaliser la racine de sortie, le nom de base et le catalogue. Les chemins relatifs sont résolus depuis le répertoire courant.

Le schéma `CREATE TABLE` détermine les types : il n’est pas recopié dans un contrat YAML manuel. Le traitement réutilise la lecture de texte, les convertisseurs et les statistiques des CSV. Les clés primaires, références et noms terminant par `_id`, `_code` ou `_badge` sont considérés comme des identifiants.

Le périmètre couvre les définitions explicites de tables, les index, `BEGIN`/`COMMIT` et les `INSERT ... VALUES`, avec ou sans liste de colonnes. Les identifiants non quotés sont normalisés selon PostgreSQL ; les identifiants quotés conservent leur casse. Les tuples sont comptés et conservés tels qu’ils apparaissent, même en présence de doublons ou de `ON CONFLICT`. Le rapport n’est pas une simulation de l’état de la base.

Chaque table présente ses colonnes déclarées, les listes de colonnes fournies par INSERT, les types SQL normalisés et logiques, les contraintes, les défauts, les statistiques et les observations. Les valeurs omises, les `NULL` explicites, les valeurs valides et les expressions non évaluées sont distingués. Les valeurs invalides sont comptées dans les observations et exclues des calculs.

Les expressions comme `NOW()`, les calculs et les casts ne sont pas exécutés : ils sont indiqués comme non évalués. Les colonnes omises ne sont pas remplies par leur défaut, même s’il est littéral. Les dates ont min/max et les mesures numériques min/max/moyenne/médiane ; les identifiants, booléens et textes n’ont pas de statistiques numériques. Les colonnes temporelles ou numériques sans données exploitables affichent `N/A`.

La précision des décimaux est conservée sans passage par `float`. Les moyennes non finies en base dix sont arrondies selon le contexte décimal, d’au moins 28 chiffres, augmenté pour les valeurs longues. Les `TIMESTAMPTZ` littéraux exigent un fuseau explicite et sont rendus en UTC.

Une erreur de parsing, un type SQL non pris en charge, un INSERT sans table déclarée, une liste de valeurs incohérente ou une instruction hors périmètre interrompt le traitement avant création d’un rapport. `INSERT SELECT`, `CREATE TABLE AS`, les mises à jour autonomes et les procédures ne sont pas pris en charge. Les contraintes sont décrites et les `NULL` explicites incompatibles avec `NOT NULL` sont signalés ; les `CHECK`, la précision déclarée des numériques, les références et l’unicité ne font pas l’objet d’une validation PostgreSQL complète.

## Vérification

Depuis la racine du projet : `uv run python -m unittest discover -s tests -v`.

Les tests vérifient les deux rapports CSV historiques, les contrats et le skill CSV, l’extraction SQL, les décimaux, les fuseaux, les expressions non évaluées et le lancement complet du notebook depuis ses deux répertoires pris en charge. Les rapports de test sont écrits dans des répertoires temporaires.

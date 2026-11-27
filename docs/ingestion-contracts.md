# Réutiliser les cartes d’identité CSV et SQL

Le [notebook](../notebooks/sprint1.ipynb) lance le traitement du [module d’ingestion](../packages/ingestion/src/indusense_ingestion/ingestion.py). Installer les dépendances avec `uv sync --all-packages --locked` avant de l’exécuter.

## Utiliser le skill dataset-identity

Le [skill dataset-identity](../skills/dataset-identity/SKILL.md) accompagne l’examen d’un CSV ou d’un script PostgreSQL et la génération de son rapport. Pour un CSV, il crée ou adapte le contrat YAML ; pour un SQL, le schéma déclaré détermine le contrat en mémoire. Sa source est versionnée dans le dépôt ; son installation personnelle se trouve dans `$CODEX_HOME/skills/dataset-identity` ou, par défaut, `~/.codex/skills/dataset-identity`.

Exemple d’invocation dans une session disposant du skill :

```text
$dataset-identity Crée une carte d’identité pour datas/ventes.csv dans ce projet.
$dataset-identity Crée une carte d’identité pour datas/machine.sql sans exécuter le SQL.
```

La sélection automatique reste autorisée. Si le skill n’apparaît pas dans une session déjà ouverte, ouvrir une nouvelle session ; son [point d’entrée versionné](../skills/dataset-identity/SKILL.md) peut aussi être fourni explicitement à l’agent.

Le skill demande seulement les précisions nécessaires, par exemple pour un format de date ambigu ou un dialecte SQL incertain. Il ne déduit pas les contraintes métier de la seule distribution des données et n’effectue pas de commit ou push sans demande. Le parcours SQL est détaillé dans une [référence dédiée](../skills/dataset-identity/references/sql.md), chargée seulement pour ce format.

Le [lanceur du skill](../skills/dataset-identity/scripts/run_identity.py) utilise le moteur existant et refuse toute génération sur `main` ou en HEAD détachée. Exemple depuis la racine, avec `uv run --all-packages --locked python` ou l’interpréteur configuré du projet :

```bash
uv run --all-packages --locked python -B skills/dataset-identity/scripts/run_identity.py --project . --source datas/releves_incidents.csv --contract config/contracts/incidents.yaml
uv run --all-packages --locked python -B skills/dataset-identity/scripts/run_identity.py --project . --source datas/machine.sql
```

Le lanceur choisit CSV ou PostgreSQL par l’extension du fichier, sans tenir compte de la casse. `--contract` est obligatoire pour les CSV et refusé pour le SQL ; `--types`, `--output-root` et `--stem` fonctionnent dans les deux parcours. Les autres extensions sont refusées. La sortie JSON donne `path`, `format` et `notes`, puis `rows`/`cols` pour les CSV ou `tables` (dimensions par table) et `inventory` pour le SQL.

Ce contrôle complète les consignes de l’agent, qui s’appliquent aussi avant d’écrire le contrat. Le [bilan initial](sprints/1/challenge1-skill-validation.md) et le [bilan de l’extension SQL](sprints/1/challenge2-skill-validation.md) distinguent les essais automatisés du lanceur et la revue des consignes.

## Configuration

- [types.yaml](../config/types.yaml) définit les types, leurs convertisseurs, les formats temporels et les statistiques applicables.
- Les [contrats](../config/contracts/) décrivent les colonnes de chaque dataset. Les noms sont sensibles à la casse.
- Les convertisseurs sont des fonctions Python du [registre explicite](../packages/ingestion/src/indusense_ingestion/contracts.py). Le YAML référence leur nom ; il ne peut pas importer ou exécuter une fonction arbitraire.

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

`INDUSENSE_PROJECT_ROOT` définit la racine des ressources lorsque le traitement est lancé hors du dépôt. Le paquet ne déduit aucun chemin depuis son emplacement d’installation.

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

Le [module SQL](../packages/ingestion/src/indusense_ingestion/sql_ingestion.py) analyse un script avec SQLGlot, sans exécuter de SQL ni se connecter à une base. Le choix du parseur et les vérifications sont décrits dans le [bilan du challenge 2](sprints/1/challenge2-validation.md). Le skill `dataset-identity` réutilise ce même module pour son parcours SQL.

Depuis le notebook, après la cellule définissant `ROOT` :

```python
from indusense_ingestion.sql_ingestion import generate_sql_identity

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

Depuis la racine du projet, installer les membres du workspace puis exécuter les deux suites :

```bash
uv sync --all-packages --locked
uv run --all-packages --locked python -m unittest discover -s packages/ingestion/tests -v
uv run --all-packages --locked python -m unittest discover -s tests -v
```

Les tests vérifient les deux rapports CSV historiques, les contrats et le skill CSV, l’extraction SQL, les décimaux, les fuseaux, les expressions non évaluées et le lancement complet du notebook depuis ses deux répertoires pris en charge. Les rapports de test sont écrits dans des répertoires temporaires.

## Opérations déclarées dans les contrats Bronze v2

Le [catalogue des opérations](../config/operations.yaml) associe les huit codes du
[schéma Bronze](../config/schema/bronze.v2.schema.json) à des slugs du
[registre Python](../packages/ingestion/src/indusense_ingestion/operations.py).
`GET /api/operations` expose les associations et les fonctions correspondantes. Aucun import
de fonction arbitraire depuis un YAML n'est autorisé.

Les [méthodes](../packages/ingestion/src/indusense_ingestion/operation_methods.py) sont exécutables
dans le moteur Python. Elles ne sont pas exécutées pendant l'ingestion Bronze. Leur déclenchement
et leur persistance dans le parcours Nuxt Silver ne sont pas encore raccordés à ce moteur ;
le parcours Silver historique conserve son comportement existant.

Chaque déclaration peut ajouter `parameters`. La méthode est toujours explicite : aucune
stratégie métier, aucun seuil ni ordre ordinal n'est choisi par défaut. Un ancien contrat peut
rester déclaratif en Bronze sans ces paramètres, mais son exécution est alors refusée.

| Code / slug | Méthodes et paramètres |
|---|---|
| MERGE / `merge` | `concat` avec `separator` obligatoire, ou `date-time-utc` avec deux entrées date puis heure. Un NULL produit un NULL ; un décalage non UTC est refusé, sans conversion d'horloge. |
| NORM / `normalize` | `min-max` : `(x-min)/(max-min)` ; sans clipping des nouvelles valeurs. |
| STD / `standardize` | `z-score` : `(x-moyenne)/écart-type` ; `ddof` obligatoire (0 : population, 1 : échantillon). |
| ENC / `encode` | `one-hot` avec `drop_first` obligatoire ; ou `ordinal` avec `categories` dans l'ordre métier explicite. Une catégorie inconnue provoque un refus, sans ajustement silencieux. |
| ANO / `pseudonymize` | `hmac-sha256`, avec `secret_ref` ; le secret non vide est fourni séparément en octets. |
| DEL / `deduplicate` | `strict` : doublons identiques ; ou `key` : clés dans `operate_on_columns`, avec `aggregations` explicite pour chaque autre colonne (`identical`, `min`, `max`, `sum`, `mean`, `median`). `target_name` est le compteur de lignes agrégées. |
| IMP / `impute` | `mean`, `median` ou `forward-fill` ; `order_by` et `max_gap_rows` obligatoires. Un trou entier supérieur au seuil reste NULL, sans remplissage partiel. Ajoute `<target_name>_is_imputed`. |
| OUT / `flag-outliers` | `iqr`, `z-score` ou `mad`, avec `threshold` positif explicite ; `ddof` obligatoire pour z-score. Produit un indicateur nullable sans supprimer ni plafonner les données. |

`group_by` est disponible pour NORM, STD, IMP et OUT. Les paramètres statistiques sont appris
uniquement sur le DataFrame d'entraînement passé à `fit_operation`, jamais dans `apply_operation`.
Un groupe absent de l'entraînement est refusé pour une opération qui dépend de statistiques.
Les étendues, écarts-types, IQR ou MAD nuls sont refusés plutôt que remplacés arbitrairement.

Pour OUT, IQR marque les valeurs hors `[Q1-threshold*IQR, Q3+threshold*IQR]` ; MAD marque
`abs(x-médiane)/MAD > threshold`, sans facteur d'échelle implicite. Les NULL restent indéterminés.
Pour IMP, `max_gap_rows` mesure une longueur en lignes consécutives après tri dans chaque groupe,
et non une durée : il faut donc une série à cadence adaptée au seuil choisi. Les clés de tri
doivent être non nulles et uniques dans chaque groupe ; le report ne traverse jamais les groupes.

L'encodage one-hot utilise les colonnes `<target_name>_0`, `<target_name>_1`, etc. ; leur
correspondance avec les catégories est conservée dans l'état appris, dans un ordre stable.
Les fonctions n'altèrent jamais le DataFrame reçu. Elles ajoutent leurs résultats à une copie,
sauf DEL qui retourne les lignes regroupées et leur compteur. ANO ajoute donc un pseudonyme :
la projection finale des colonnes doit sélectionner celles à conserver en Silver ; l'ajout du
pseudonyme ne supprime pas les identifiants bruts de la copie.

Exemple de déclaration compatible avec `derived_columns` :

```yaml
target_name: temperature_normalized
operation: NORM
operate_on_columns: [temperature_c]
silver_type: DOUBLE PRECISION
parameters:
  method: min-max
  group_by: [machine_id]
```

Apprentissage séparé puis réutilisation, y compris après sérialisation JSON :

```python
import json
from indusense_ingestion.operations import fit_operation, apply_operation

state = fit_operation(training_frame, declaration, root=ROOT)
serialized = json.dumps(state, allow_nan=False)
restored = json.loads(serialized)
prepared_test = apply_operation(test_frame, restored, root=ROOT)

# Pour ANO uniquement : le secret vient de l'appelant, hors contrat et hors état appris.
# prepared = apply_operation(frame, state, root=ROOT,
#                            secrets={"operator": secret_from_secret_manager})
```

Les états appris contiennent la déclaration et les statistiques ou catégories, jamais le secret.
Ils doivent être conservés avec les artefacts d'entraînement et réutilisés tels quels pour les
données de validation, de test et de production. Les catégories et statistiques peuvent elles-mêmes
être sensibles : le registre ne les publie pas dans `GET /api/operations`.

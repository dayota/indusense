# Réutiliser les cartes d’identité CSV

Le [notebook](../notebooks/sprint1.ipynb) lance le traitement du [module d’ingestion](../indusense/ingestion.py). Installer les dépendances avec `uv sync` avant de l’exécuter.

## Configuration

- [types.yaml](../config/types.yaml) définit les types, leurs convertisseurs, les formats temporels et les statistiques applicables.
- Les [contrats](../config/contracts/) décrivent les colonnes de chaque dataset. Les noms sont sensibles à la casse.
- Les convertisseurs sont des fonctions Python du [registre explicite](../indusense/contracts.py). Le YAML référence leur nom ; il ne peut pas importer ou exécuter une fonction arbitraire.

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

Les sorties restent horodatées à Paris et une sortie existante n’est pas écrasée. Les rapports historiques sont conservés. Cette évolution concerne les CSV ; le traitement SQL demeure une étape distincte.

## Vérification

Depuis la racine du projet : `uv run python -m unittest discover -s tests -v`.

Les tests vérifient les deux rapports historiques, un dataset supplémentaire, les contraintes, les erreurs de configuration, les types personnalisés et le lancement du notebook depuis ses deux répertoires pris en charge. Les rapports de test sont écrits dans des répertoires temporaires.

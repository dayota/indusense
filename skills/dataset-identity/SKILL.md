---
name: dataset-identity
description: "Créer ou adapter un contrat YAML et générer une carte d’identité pour un dataset CSV avec le moteur d’ingestion InduSense existant. Utiliser pour ajouter un CSV au processus ou produire son rapport de métadonnées, types et statistiques. Exclure le SQL, les autres formats et les simples explications sans demande de traitement."
---

# Cartes d’identité CSV

## Préparer le contexte

Retrouver la racine du projet dans le contexte utilisateur ou à partir du répertoire courant. Les chemins projet ci-dessous sont relatifs à cette racine, jamais au dossier d’installation du skill. Vérifier la présence de `docs/ingestion-contracts.md`, `indusense/ingestion.py`, `indusense/contracts.py` et `config/types.yaml`. Si ces ressources manquent, demander le chemin du projet ; ne pas recréer le moteur.

Lire les consignes applicables du dépôt puis le guide d’ingestion. Vérifier `git branch --show-current` au début de la tâche et avant toute écriture, y compris du contrat. Sur `main` ou HEAD détachée, demander à l’utilisateur de créer ou sélectionner une branche, attendre son choix explicite et préserver les modifications existantes. L’inspection en lecture seule reste possible. Ne pas créer ou changer de branche automatiquement.

Déterminer la source CSV, le contrat éventuel et la destination attendue. Résoudre les chemins depuis la racine du projet. Refuser de traiter un script SQL ou un autre format comme un CSV : le moteur actuel couvre les CSV. Expliquer cette limite sans installer de parseur SQL.

## Examiner et établir le contrat

Utiliser l’environnement Python configuré pour le projet, avec ses dépendances verrouillées. Importer `read_csv_source` depuis le moteur pour examiner le fichier sans le modifier : encodage et ses limites, séparateur, dimensions, colonnes et valeurs représentatives. Distinguer un examen d’échantillon d’un contrôle sur toutes les lignes. Ne pas normaliser les identifiants ou convertir leurs zéros initiaux en nombres.

Chercher un contrat correspondant dans `config/contracts/`. Préserver ses règles et les modifications de l’utilisateur. Pour un nouveau contrat, construire un YAML `version: 1` avec `dataset`, `columns` et une politique `extra_columns` explicite ; utiliser `infer` par défaut si aucune exigence de fermeture du schéma n’est établie. Respecter la casse exacte des colonnes.

Distinguer types techniques observés et exigences métier. Ne pas inventer `min`, `max`, `allowed`, `nullable: false` ou une règle de présence à partir de la seule distribution des données. Le moteur considère les colonnes déclarées comme obligatoires par défaut : rendre ce choix explicite dans le bilan, employer `required: false` si leur caractère facultatif est établi. Réutiliser une contrainte métier seulement si elle est donnée ou déjà documentée.

Lever les ambiguïtés qui influencent le résultat : par exemple demander si `01/02/2026` signifie le 1er février ou le 2 janvier lorsque le format n’est pas documenté. Ne pas utiliser la langue de l’utilisateur comme preuve du format. Continuer les inspections indépendantes, puis attendre la réponse avant la conversion dépendante. Préserver comme texte les valeurs non interprétables plutôt que prétendre avoir validé un type numérique ou temporel.

Choisir les types dans `config/types.yaml`. Une option de colonne remplace le défaut du type ; surcharger `format` sans `pattern` désactive le motif par défaut. Pour imposer une forme stricte, fournir aussi `pattern`. Priorités : colonne explicite, première règle `column_rules` correspondante, puis inférence ou erreur selon `extra_columns`.

Réutiliser les convertisseurs `string`, `integer`, `number`, `datetime`. Si nécessaire, ajouter un type utilisant un convertisseur existant. Ajouter une fonction Python au registre seulement si le besoin exige un comportement nouveau, avec une vérification ciblée. Ne pas intégrer du code exécutable, des imports dynamiques ou des chemins de fonctions arbitraires dans le YAML. Ne pas dupliquer les conversions ou les statistiques dans le skill.

## Générer et contrôler

Valider le contrat avec `load_configuration` du module `indusense.contracts` avant de traiter les données. Un contrat invalide doit empêcher la génération, sans être corrigé silencieusement.

Le script [run_identity.py](scripts/run_identity.py) centralise le lancement et le contrôle de branche avant l’import du moteur. Depuis la racine du projet, avec l’interpréteur configuré, appeler le script à son chemin réel, résolu depuis le dossier de ce skill :

```text
python -B <dossier-du-skill>/scripts/run_identity.py --project <racine> --source datas/ventes.csv --contract config/contracts/ventes.yaml
```

Remplacer `python` par l’interpréteur configuré, sans supposer que celui du système convient. `--types` choisit un autre catalogue ; `--output-root` une autre racine de sortie ; `--stem` le nom de base du rapport. Le script ne crée pas le contrat et ne décide pas des contraintes métier.

Vérifier les dimensions, les types et les statistiques applicables dans le rapport produit. Vérifier les identifiants préservés, les anomalies signalées, les valeurs invalides exclues et les statistiques sans valeur indiquées `N/A`. Ne pas annoncer une validation de qualité complète lorsque des observations subsistent. Préserver les rapports existants : en cas de collision à la même seconde, attendre un nouvel horodatage et relancer une fois, sans supprimer ni écraser de sortie. Si l’erreur persiste, l’exposer et rechercher sa cause avant de réessayer.

Adapter le notebook seulement si la demande inclut ce lancement. Si le moteur ou sa configuration partagée change, exécuter les tests d’ingestion depuis la racine (`python -m unittest discover -s tests -v` avec l’interpréteur configuré). Pour un simple contrat, contrôler les résultats du dataset concerné.

## Restituer

Donner les liens vers le contrat et le rapport, les dimensions vérifiées, les anomalies et les hypothèses restantes. Indiquer les éventuels types ou convertisseurs ajoutés. Ne pas modifier la source, réécrire les rapports historiques ou effectuer un commit/push sans autorisation dans la demande.

# Challenge 2 — Bilan de réalisation

Date : 2026-11-20. Branche : `sprint1/challenge2`, créée après fusion du challenge 1 dans `main` par la [PR #1](https://github.com/dayota/indusense/pull/1).

## Réalisation

Le [module SQL](../../../indusense/sql_ingestion.py) lit le script PostgreSQL, extrait les schémas et les tuples `INSERT VALUES`, applique les convertisseurs partagés et génère une carte d’identité par script avec une section par table. Le [notebook](../../../notebooks/sprint1.ipynb) lance désormais les traitements CSV puis SQL. Le [guide](../../ingestion-contracts.md) décrit l’API, les types et les limites.

La lecture de texte et les statistiques sont partagées avec les CSV. Le [catalogue](../../../config/types.yaml) et le [registre](../../../indusense/contracts.py) ajoutent DECIMAL, BOOLEAN et DATETIME_UTC. Les schémas SQL alimentent automatiquement les contrats en mémoire : aucune copie manuelle des tables dans un YAML n’est nécessaire.

## Choix du parseur

[SQLGlot](https://sqlglot.com/sqlglot.html) a été retenu pour son arbre syntaxique parcourable et son dialecte PostgreSQL explicite. [sqlparse](https://sqlparse.readthedocs.io/en/stable/intro.html) offre une analyse non validante de tokens et d’instructions ; l’extraction structurée recherchée aurait demandé davantage de logique spécifique.

SQLGlot **30.33.0** a été installé avec `uv add sqlglot` et verrouillé. Son import et le parsing complet ont été exécutés avec Python 3.15. Les 10 instructions ont produit les nœuds attendus, notamment les contraintes, les `TIMESTAMPTZ` et les clauses `ON CONFLICT`. Le succès du parsing n’équivaut pas à une validation complète par PostgreSQL.

## Rapport généré

[Carte d’identité SQL machine_155624.md](../../../artifacts/ingestion/identities/20261120/machine_155624.md).

| Mesure | Résultat |
|---|---|
| Encodage et taille | UTF-8, 22,41 Ko |
| Instructions | 10 : BEGIN, 2 CREATE TABLE, 4 CREATE INDEX, 2 INSERT VALUES, COMMIT |
| Table machine | 15 tuples, 11 colonnes déclarées, 8 fournies par INSERT |
| Table maintenance | 115 tuples, 11 colonnes déclarées, 9 fournies par INSERT |
| Mise en service des machines | Du 2019-07-23 au 2025-05-25 |
| Capacité journalière | Min 750, max 1 428, médiane 1 027 ; somme 15 823, moyenne 15 823 / 15 |
| Dates de maintenance | Du 2025-06-15 06:00:00 UTC au 2026-05-30 22:00:00 UTC |
| Durée des maintenances | Min 1,0 h, max 8,0 h, médiane 2,64 h ; somme 338,45 h, moyenne 338,45 / 115 |
| Identifiants d’incident liés | 25 valeurs explicites et 90 NULL |

Les valeurs attendues sur les capacités et les durées ont aussi été contrôlées indépendamment de SQLGlot par une lecture ciblée des lignes de tuples du fichier fourni. Ce contrôle de référence n’est pas utilisé dans le moteur d’extraction.

L’empreinte SHA-256 du [script source](../../../datas/machine.sql) a été contrôlée avant et après traitement :

```text
9eb877ae806515e852df46dd9f97f31aabfa8420a8f07dc50a5be4cefced8fcb
```

Aucune instruction SQL n’a été exécutée. Les défauts et `NOW()` ne sont pas évalués ; les colonnes omises restent distinctes des NULL explicites. Le rapport expose les statistiques `N/A` pour les colonnes sans valeurs observables et décrit les clauses `ON CONFLICT` sans simuler leurs effets en base.

## Vérifications exécutées

La suite `python -B -m unittest discover -s tests -v`, avec l’interpréteur du projet, réussit : **25 tests**, dont 9 tests SQL et les 16 tests CSV et du skill existants.

Les [tests SQL](../../../tests/test_sql_ingestion.py) couvrent le fichier fourni, les résultats chiffrés attendus, les colonnes INSERT réordonnées, les doublons, les chaînes échappées avec virgule ou point-virgule, les NULL et omissions, les expressions non évaluées, les décimaux longs, les fuseaux, les booléens, les contraintes de table et les identifiants. Ils couvrent aussi un schéma sans données, une syntaxe invalide, des listes de valeurs incohérentes, des types ou instructions hors périmètre et le refus d’écraser une sortie existante.

Les tests de régression vérifient les tableaux des rapports CSV historiques inchangés. Le notebook complet a été exécuté depuis la racine et depuis son dossier, avec des sorties temporaires. Les vérifications de branche du lanceur CSV restent fonctionnelles.

## Limites explicites

L’analyse est statique et ciblée sur les constructions du script fourni. Les expressions SQL, y compris les casts, sont signalées sans calcul ; `INSERT SELECT`, `CREATE TABLE AS`, les procédures et les mises à jour autonomes sont refusés. Les types et contraintes sont rendus sous la forme normalisée de SQLGlot, avec leurs alias éventuels.

Les contraintes sont décrites mais ne constituent pas une validation de toutes les règles PostgreSQL, notamment CHECK, références, unicité, précision et échelle déclarées. Les décimaux sont calculés sans float ; les moyennes périodiques utilisent une précision décimale d’au moins 28 chiffres. Les horodatages sans fuseau explicite dans une colonne TIMESTAMPTZ sont signalés comme invalides plutôt que d’inventer le fuseau de session d’une base.

Le skill `dataset-identity` et son installation restent limités aux CSV. Le commit et le push du challenge 2 restent à effectuer sur demande.

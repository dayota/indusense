# Challenge 2 — Carte d’identité du script SQL

Statut : réalisé et vérifié le 2026-11-20 sur `sprint1/challenge2`. Voir le [bilan de réalisation](challenge2-validation.md) et le [rapport SQL](../../../artifacts/ingestion/identities/20261120/machine_155624.md).

## Objectif

Réaliser la section [« Pour aller plus loin »](TODO-SPRINT1_1.md#pour-aller-plus-loin) : choisir et installer une bibliothèque de parsing SQL, puis produire une carte d’identité du [script machine.sql](../../../datas/machine.sql), avec les métadonnées, les colonnes et les statistiques applicables comme pour les CSV.

Analyser le script sans l’exécuter et sans créer de base de données. Le rapport décrit les définitions et valeurs contenues dans le fichier, pas l’état final d’une base PostgreSQL.

## État initial et périmètre

Le script annonce PostgreSQL et contient `BEGIN`, `COMMIT`, deux `CREATE TABLE`, quatre `CREATE INDEX` et deux `INSERT ... VALUES ... ON CONFLICT DO UPDATE`.

| Table | Colonnes déclarées | Colonnes fournies par INSERT | Tuples présents |
|---|---:|---:|---:|
| `machine` | 11 | 8 | 15 |
| `maintenance` | 11 | 9 | 115 |

Ces nombres constituent les résultats attendus à confirmer par le parseur. Les données couvrent des identifiants, du texte, des entiers, un décimal `NUMERIC(6,2)`, une date, un booléen et des horodatages `TIMESTAMPTZ`.

Réutiliser le [moteur CSV](../../../indusense/ingestion.py), le [chargement des contrats](../../../indusense/contracts.py) et le [catalogue des types](../../../config/types.yaml) lorsque leurs interfaces conviennent. Préserver le fonctionnement du [notebook](../../../notebooks/sprint1.ipynb), des contrats CSV et du skill CSV existant. L’extension du skill au SQL est hors périmètre de ce challenge.

## Étape 1 — Vérifier la branche et la source

- [x] Appliquer les [consignes du dépôt](../../../AGENTS.md) : vérifier la branche au début de la tâche et avant toute écriture ; sur `main` ou HEAD détachée, attendre le choix explicite d’une branche par l’utilisateur.
- [x] Vérifier la présence du script et relever son empreinte pour contrôler sa préservation.
- [x] Confirmer l’encodage, la taille et les constructions SQL présentes.

**Livrable :** inventaire de la source et référence de son empreinte, sans modification du SQL.

## Étape 2 — Choisir et installer le parseur

- [x] Évaluer d’abord [SQLGlot](https://sqlglot.com/sqlglot.html) pour parcourir un arbre syntaxique et extraire les schémas et les tuples avec le dialecte explicite `postgres`.
- [x] Comparer brièvement avec [sqlparse](https://sqlparse.readthedocs.io/en/stable/intro.html), qui fournit une analyse non validante ; privilégier l’outil qui permet l’extraction structurée requise sans reconstruire un parseur.
- [x] Ajouter uniquement la bibliothèque retenue avec `uv add` et conserver les changements de dépendances dans le verrou.
- [x] Vérifier son import dans l’environnement Python 3.15 du projet et son analyse du script complet, notamment `TIMESTAMPTZ`, `ON CONFLICT` et les contraintes.
- [x] Examiner les nœuds obtenus et les avertissements : un parsing réussi n’est pas une validation PostgreSQL complète. Refuser les représentations génériques opaques des constructions indispensables à l’extraction.

**Livrable :** choix documenté, dépendance installée et preuve de lecture structurée du script. Le choix SQLGlot reste à confirmer par cet essai.

## Étape 3 — Extraire les schémas et les valeurs

- [x] Créer un module SQL dédié, proposé sous `indusense/sql_ingestion.py`, avec des fonctions séparant lecture, parsing, extraction, analyse et génération.
- [x] Extraire les tables, l’ordre des colonnes, les types SQL déclarés et les contraintes utiles à leur description : clé primaire, référence, nullabilité, défaut et `CHECK`.
- [x] Extraire les tuples des `INSERT ... VALUES` en respectant leur liste explicite de colonnes ; vérifier que chaque tuple a le bon nombre de valeurs.
- [x] Regrouper les tuples par table et conserver les doublons présents dans le fichier.
- [x] Reconnaître chaînes SQL échappées, nombres, booléens et `NULL` depuis les nœuds syntaxiques. Ne pas découper les valeurs à la virgule ou les instructions au point-virgule avec une simple séparation de texte.
- [x] Distinguer valeur littérale, `NULL` explicite, colonne omise et expression non évaluée.
- [x] Inventorier `BEGIN`, `COMMIT` et les index sans les traiter comme des lignes de données. Décrire `ON CONFLICT` sans appliquer ses mises à jour ni compter les affectations comme des tuples supplémentaires.

**Livrable :** une représentation structurée des deux tables et des données explicitement présentes, avec les limites d’extraction signalées.

## Étape 4 — Adapter les types et calculer les statistiques

- [x] Associer les types déclarés aux types logiques existants ; conserver le type SQL original dans le rapport.
- [x] Reconnaître les identifiants à partir des clés et références du schéma et des conventions explicites : `machine_code`, `maintenance_id`, `related_incident_id`. Exclure les identifiants des statistiques numériques, même s’ils sont stockés en entier.
- [x] Réutiliser les conversions et statistiques communes plutôt que les recopier. Prévoir des contrats YAML par table uniquement pour les correspondances ou exceptions utiles ; ne pas maintenir manuellement une copie intégrale du schéma SQL.
- [x] Ajouter au catalogue et au registre un type ou un convertisseur seulement si les comportements existants ne suffisent pas, notamment pour les horodatages avec fuseau ou les décimaux.
- [x] Préserver la précision des valeurs `NUMERIC(6,2)` lors des calculs ; choisir et vérifier explicitement la représentation décimale avant toute conversion vers des flottants.
- [x] Pour `commissioning_date` et `maintenance_at`, calculer min/max ; conserver les fuseaux et comparer les instants de manière cohérente, avec une sortie documentée en UTC pour les horodatages fournis en `+00`.
- [x] Pour les capacités et `duration_hours`, calculer min/max/moyenne/médiane. Pour les textes, identifiants et booléens, ne pas produire de statistiques numériques.
- [x] Exclure les `NULL`, les valeurs invalides et les données absentes des calculs, en signalant les anomalies de conversion.
- [x] Ne pas évaluer `NOW()` ni inventer une date pour les colonnes `created_at` et `updated_at`. Afficher les défauts déclarés séparément ; les colonnes omises n’ont pas de valeurs observées et leurs statistiques restent `N/A`.

**Livrable :** types et statistiques par table, sans fusion des populations des deux tables ni simulation de l’état d’une base.

## Étape 5 — Générer le rapport Markdown

- [x] Produire un rapport unique sous `artifacts/ingestion/identities/YYYYMMDD/machine_HHMMSS.md`, avec date et horodatage de traitement selon la convention Paris existante.
- [x] Inclure les métadonnées communes : `Source`, `Filsize`, `ProcessBeginAt`, `ProcessEndAt`, `Charset`, puis le dialecte et le nombre de tables et d’instructions.
- [x] Ajouter une section par table avec `Rows Number` pour les tuples du script et `Cols Number` pour les colonnes déclarées ; indiquer aussi le nombre de colonnes fournies par les INSERT.
- [x] Présenter la liste des colonnes, les types SQL et logiques, les défauts pertinents et le tableau des statistiques.
- [x] Expliquer que les tuples comptés ne sont pas des insertions garanties en base : `ON CONFLICT` dépend de son contenu initial.
- [x] Inclure les observations, les expressions non évaluées et les constructions non prises en charge. Une erreur de syntaxe ou une impossibilité d’extraire les données attendues doit interrompre la génération plutôt que produire un rapport complet trompeur.
- [x] Préserver les rapports existants en refusant tout écrasement, comme pour les CSV.

**Livrable :** carte d’identité du script, lisible et comparable aux rapports CSV, avec une séparation claire entre métadonnées fichier et données par table.

## Étape 6 — Intégrer le lancement dans le notebook

- [x] Ajouter une section SQL dans le notebook existant, qui appelle le module et affiche le chemin du rapport et les observations.
- [x] Garder la logique de parsing et de calcul dans les modules réutilisables.
- [x] Vérifier le lancement depuis la racine du projet et depuis le dossier du notebook.
- [x] Compléter le [guide d’ingestion](../../ingestion-contracts.md) avec le lancement SQL et ses limites, tout en conservant le périmètre CSV du skill.

**Livrable :** lancement reproductible du traitement CSV et SQL depuis le notebook.

## Étape 7 — Vérifier les résultats et les régressions

- [x] Confirmer les 2 tables, 10 instructions, 15 tuples machine et 115 tuples maintenance, ainsi que les 11 colonnes déclarées pour chaque table.
- [x] Vérifier que les dates et nombres du rapport correspondent aux valeurs sources, avec des attentes chiffrées établies indépendamment du calcul testé.
- [x] Tester les listes de colonnes INSERT réordonnées, les `NULL`, les colonnes omises, une chaîne avec apostrophe échappée et une chaîne contenant virgule ou point-virgule.
- [x] Tester les décimaux, les fuseaux horaires, l’exclusion des identifiants et les statistiques sans valeur exploitable.
- [x] Tester une erreur de syntaxe, une expression non évaluée et une instruction hors périmètre ; vérifier que leur traitement ne passe pas sous silence une extraction incomplète.
- [x] Tester la collision de sortie et vérifier l’empreinte inchangée de la source.
- [x] Exécuter les tests CSV et du skill existants ; en cas de modification d’un composant partagé, confirmer leurs résultats inchangés.
- [x] Exécuter le notebook dans les deux répertoires pris en charge, avec sorties temporaires pour les tests.

**Livrable :** tests ciblés réussis, rapport final contrôlé et absence de régression CSV.

## Critères de fin

- La bibliothèque retenue est installée et verrouillée, avec un essai confirmé sous Python 3.15.
- La carte d’identité du SQL contient les champs demandés et des statistiques correctes par table.
- La différence entre schéma déclaré, valeurs explicites, colonnes omises et expressions non évaluées est visible.
- Le script source reste intact et aucune instruction SQL n’est exécutée.
- Le notebook et la documentation permettent de reproduire le rapport.
- Les tests SQL, CSV et du lanceur du skill sont concluants. Le commit et le push seront effectués sur demande.

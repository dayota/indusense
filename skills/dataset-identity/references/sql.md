# Analyser un script PostgreSQL

Lire cette référence seulement pour une demande SQL. Les chemins projet sont résolus depuis sa racine, comme indiqué dans le [point d’entrée](../SKILL.md).

## Examiner la source

Lire la partie PostgreSQL de `docs/ingestion-contracts.md` et vérifier `scripts/sql_ingestion.py`. Utiliser l’environnement du projet avec ses dépendances verrouillées, dont SQLGlot. Si le module manque, demander le bon projet ; ne pas installer un moteur parallèle.

Utiliser `read_text_source` et `parse_sql_source` pour l’examen en lecture seule. Le dialecte pris en charge est PostgreSQL : demander le dialecte si les indices sont ambigus ou signaler l’incompatibilité, sans prétendre prendre en charge un autre dialecte.

Le module lit les tables déclarées, les index, BEGIN/COMMIT et les INSERT VALUES. Il conserve les tuples, les doublons et l’ordre des colonnes indiqué par chaque INSERT. Les identifiants SQL non quotés sont normalisés selon PostgreSQL ; les noms quotés conservent leur casse. Aucun SQL, défaut ou expression n’est exécuté et aucune base n’est créée.

## Générer

Lancer `scripts/run_identity.py` depuis le dossier réel du skill avec `--project` et `--source` pour un fichier `.sql`, sans `--contract`. Ce lanceur appelle `generate_sql_identity`, qui déduit le contrat en mémoire à partir de CREATE TABLE. Ne pas recopier le schéma dans un YAML.

Ne pas contourner une erreur en convertissant le SQL en CSV ou en exécutant le script. Une erreur de parsing, un type inconnu, INSERT SELECT, CREATE TABLE AS ou une instruction hors périmètre doit être exposé comme une limite. Un rapport complet ne doit pas être annoncé si l’extraction attendue a échoué.

## Vérifier et expliquer

- Vérifier les nombres de tables, d’instructions et de tuples par table, ainsi que les colonnes déclarées et les listes de colonnes fournies par INSERT.
- Distinguer valeurs littérales, NULL explicites, colonnes omises et expressions non évaluées. Les défauts, même littéraux, ne comblent pas les omissions.
- Ne pas calculer NOW(), les casts ou les expressions arithmétiques : le module les signale et les exclut des statistiques.
- Préserver les décimaux sans passage par float et rendre les horodatages avec fuseau en UTC. Un TIMESTAMPTZ naïf est invalide ; ne pas supposer un fuseau de session.
- Vérifier l’exclusion des identifiants des statistiques numériques, même pour une clé primaire entière. Les dates et horodatages ont min/max ; les mesures numériques ont aussi moyenne/médiane.
- Expliquer les N/A pour les statistiques non applicables ou les colonnes sans valeurs exploitables.
- Décrire ON CONFLICT sans l’appliquer : les tuples présents ne sont pas un nombre d’insertions garanties en base.
- Présenter les contraintes et types SQL normalisés comme des descriptions ; le module ne prouve pas la validité complète selon PostgreSQL, notamment pour CHECK, références, unicité ou précision/échelle déclarée.

Le fichier `datas/machine.sql`, s’il est fourni dans le projet InduSense, constitue un cas de référence : deux tables, 10 instructions, 15 tuples machine et 115 tuples maintenance, avec 11 colonnes déclarées chacune. Ne pas appliquer ces attentes à un autre script.

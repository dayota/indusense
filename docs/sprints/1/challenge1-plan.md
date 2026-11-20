# Plan du challenge 1 — Cartes d’identité des CSV

## Objectif

Produire deux rapports Markdown décrivant les fichiers CSV sources, leurs colonnes et leurs statistiques, depuis le [notebook existant](../../../notebooks/sprint1.ipynb). Pandas est déjà déclaré dans le projet.

## 1. Lire les fichiers sources

- Utiliser [releves_incidents.csv](../../../datas/releves_incidents.csv) et [telemetry.csv](../../../datas/telemetry.csv).
- Relever le chemin absolu et la taille, présentée avec deux décimales et une unité adaptée.
- Vérifier l’encodage : UTF-8 en priorité ; signaler tout recours à un autre encodage.
- Détecter le séparateur parmi virgule, point-virgule et tabulation.

## 2. Charger et décrire chaque CSV

- Enregistrer l’heure de début du traitement.
- Charger les données sans supprimer de lignes ni de doublons.
- Compter les lignes hors en-tête et les colonnes.
- Identifier les types à partir des noms **et des valeurs** :

| Colonnes observées | Type prévu |
|---|---|
| `incident_id`, `machine_id`, `operator_badge` | `IDENTITY` |
| `date` | `DATE` |
| `time` | `TIME` |
| `timestamp` | `DATETIME` |
| Mesures, sévérité et compteurs | `INTEGER` ou `FLOAT` |
| Noms, commentaires, équipe | `TEXT` |

Les identifiants resteront des chaînes. Les indicateurs `type_*` seront considérés comme des entiers binaires.

## 3. Calculer les statistiques

- Numériques : minimum, maximum, moyenne et médiane.
- Dates et horodatages : minimum et maximum.
- Heures : première et dernière heure.
- Exclure les valeurs manquantes des calculs ; afficher `N/A` si aucune valeur exploitable n’existe.
- Signaler les valeurs incompatibles avec le type attendu, sans les ignorer silencieusement.

## 4. Générer les deux rapports Markdown

Chaque rapport contiendra :

- `Source` : chemin absolu du document source.
- `Filsize` : taille avec deux décimales et unité adaptée.
- `ProcessBeginAt` : heure de début au format `HH:MM:SS`.
- `ProcessEndAt` : heure de fin au format `HH:MM:SS`.
- `Charset` : encodage utilisé.
- `Rows Number` : nombre de lignes hors en-tête.
- `Cols Number` : nombre de colonnes.
- Un tableau des colonnes avec `Colname` et `Infered Type`.
- Un tableau des statistiques pour les colonnes numériques et temporelles.

Enregistrer l’heure de fin après l’analyse, juste avant l’écriture du rapport. Créer le dossier de sortie daté et utiliser l’heure de début pour le suffixe `HHMMSS`.

Les chemins attendus pour le challenge du 20 novembre 2026 sont :

```text
artifacts/ingestion/identities/20261120/releves_incidents_HHMMSS.md
artifacts/ingestion/identities/20261120/telemetry_HHMMSS.md
```

Utiliser le nom `releves_incidents_HHMMSS.md`, cohérent avec le fichier source et la consigne corrigée.

## 5. Vérifier le résultat

- Vérifier la présence des deux rapports et de tous les champs demandés.
- Vérifier la concordance des dimensions avec les CSV.
- Vérifier l’absence de statistiques numériques sur les identifiants.
- Contrôler la cohérence des résultats : minimum ≤ médiane/moyenne ≤ maximum.
- Vérifier que relancer le notebook produit des rapports correctement horodatés.

## Organisation du code

Factoriser le traitement en cinq fonctions réutilisables :

1. Lecture du CSV.
2. Inférence des types.
3. Calcul des statistiques.
4. Rendu Markdown.
5. Orchestration du traitement et écriture des rapports.

Le traitement SQL reste hors périmètre de ce challenge.

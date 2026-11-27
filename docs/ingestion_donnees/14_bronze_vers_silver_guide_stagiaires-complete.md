# Du bronze au silver : rendre les mesures fiables et explicables

> **Objectif de l'atelier.** À partir des données brutes ingérées, produire un jeu de mesures contrôlées, cohérentes et traçables. Une valeur surprenante n'est pas automatiquement une erreur : dans un projet de maintenance prédictive, elle peut être le signal le plus précieux.

## 1. Situer les trois niveaux

| Niveau | Question | Contenu attendu |
| --- | --- | --- |
| **Bronze** | Qu'a-t-on reçu ? | Données sources conservées, y compris valeurs manquantes, doublons et erreurs, avec provenance et heure d'ingestion. |
| **Silver** | Quelles observations sont interprétables et avec quelle fiabilité ? | Schéma, unités et temps harmonisés ; doublons résolus ; erreurs identifiées ; valeurs manquantes et suspects signalés ; corrections justifiées. |
| **Gold** | Quelles observations et variables pour un usage précis ? | Fenêtres, agrégats, variables dérivées, labels mûrs, découpages entraînement/validation/test et transformations propres au modèle. |

**« Standardiser » peut désigner deux choses différentes.** Standardiser *le contrat de données* (noms, types, unités, fuseaux, codes machine) relève du silver. Centrer-réduire une variable (`StandardScaler`) ou la ramener entre 0 et 1 (`MinMaxScaler`) dépend du modèle : on ajuste ces transformations uniquement sur l'entraînement, puis on les applique à la validation, au test et à l'inférence. Il est possible de conserver une copie dérivée pour l'exploration, mais les mesures physiques d'origine restent accessibles dans silver.

**Cas Indusense.** La maquette du sprint montre `machine_code`, `predicted_at`, `temperature`, `vibration`, `pressure` et `label` dans un *gold synthétique*. Ce fichier est déjà échantillonné et étiqueté : **ce n'est pas le bronze de l'atelier**. Les unités réelles, la cadence des capteurs et la clé métier des relevés sont à relever dans le bronze ingéré. Les noms ci-dessous sont des exemples à adapter au schéma réellement constaté. Les retours terrain `SENSOR_ISSUE` servent à qualifier une mesure, pas à effacer toutes les valeurs élevées.

## 2. Avant de modifier une seule ligne : établir le contrat

Sur un échantillon puis sur l'ensemble du bronze, remplir cette fiche avec l'équipe métier :

| À préciser | Exemple de question | Conséquence dans silver |
| --- | --- | --- |
| Grain | Une ligne = une lecture de quel capteur, de quelle machine, à quel instant ? | Définit la clé et les vrais doublons. |
| Identifiants | `machine_code` est-il stable ? Existe-t-il un `sensor_id`, un identifiant d'événement source ? | Évite de fusionner deux capteurs ou deux événements distincts. |
| Temps | Heure de mesure ou d'ingestion ? Fuseau et précision ? | Conserver les deux ; convertir la mesure en UTC sans inventer de fuseau. |
| Grandeurs | Température en °C ou °F, pression absolue ou relative, vibration RMS ou pic ? | Conversion explicite et nom de colonne non ambigu ; ne pas convertir des mesures incompatibles. |
| Cadence et état | Lecture toutes les secondes, arrêt machine, maintenance, changement de capteur ? | Distinguer une absence normale d'une panne de collecte. |
| Plages métier | Quelles valeurs impossibles, seulement rares, et variables selon le régime ? | Valider les règles avec un expert ; garder les événements rares plausibles. |
| Provenance | Fichier, API, lot, horodatage, version de schéma ? | Rejouer la transformation et remonter à la ligne brute. |

**Livrable 1 :** dictionnaire des colonnes et tableau des règles, avec unité, clé, sens des `null`, plage *physiquement impossible* confirmée et responsable de validation. Aucun seuil chiffré « universel » n'est proposé pour Indusense.

## 3. Parcours de transformation, dans cet ordre

### Étape A — Photographier le bronze

1. Figer l'entrée : chemin ou identifiant de lot, date de collecte, nombre de lignes, empreinte du fichier et version du schéma.
2. Compter les lignes par machine, capteur et période ; vérifier la couverture attendue et les intervalles entre mesures.
3. Mesurer les taux de `null`, valeurs non numériques, timestamps invalides, valeurs infinies et doublons. Afficher *où* ils se concentrent, pas seulement un pourcentage global.
4. Produire quelques courbes brutes. Ne pas commencer par `dropna()`, `drop_duplicates()` ou une moyenne globale.

**À montrer en salle :** « 2 % de valeurs absentes » peut cacher une machine totalement muette pendant une heure critique.

### Étape B — Harmoniser le schéma et les unités

- Renommer selon un dictionnaire stable ; convertir les types en conservant le texte original dans le bronze. Une conversion impossible devient `null` **avec motif**, jamais `0` silencieux.
- Mettre les horodatages en UTC ; distinguer `measured_at` de `ingested_at` et conserver le fuseau ou l'information source permettant de vérifier la conversion.
- Ramener les unités à une unité canonique **si l'unité source est connue** ; documenter formule, version et unité initiale. Ne pas assimiler par défaut pression absolue et pression relative.
- Joindre le référentiel machine de façon temporelle si ses attributs changent ; traiter séparément machines inconnues et changements de capteur.
- Séparer une erreur de parsing ou une valeur physiquement impossible confirmée d'une valeur seulement statistiquement inhabituelle.

### Étape C — Dédupliquer sans perdre un événement

1. Chercher d'abord les **copies techniques** : même identifiant d'événement source ou même clé validée, même mesure, même contenu. Conserver une occurrence avec ses sources et compter les copies.
2. À clé identique mais valeurs différentes, ne pas garder arbitrairement la dernière : mettre en conflit, rechercher ordre de révision, horodatage d'émission et règle de priorité de source.
3. Deux lectures voisines d'un capteur ne sont pas des doublons ; deux capteurs d'une même machine au même instant non plus. Une réémission après panne réseau peut porter un nouvel instant d'ingestion mais le même instant de mesure.
4. Mesurer `lignes reçues = lignes retenues + copies écartées + lignes en quarantaine`, selon la convention choisie ; conserver les identifiants des copies et conflits.

### Étape D — Classer les observations avant de les corriger

| État | Exemple | Action initiale |
| --- | --- | --- |
| Valide | Lecture compatible avec unité et régime | Conserver. |
| Manquant | Paquet absent, valeur vide | Garder `null` et le motif s'il est connu ; décider ensuite si une estimation est utile. |
| Invalide | Parsing impossible, unité inconnue, contrainte physique confirmée violée | Isoler la valeur d'analyse ou mettre la ligne en quarantaine, avec justification. |
| Suspect | Pic soudain, décalage durable, score d'anomalie élevé | Garder valeur et drapeau ; faire examiner le contexte machine. |
| Incident plausible | Hausse de vibration avant intervention | Garder ; ne jamais « nettoyer » un signal de panne au seul motif qu'il est rare. |

La mise en quarantaine garde la trace du rejet et permet une reprise. **Silver n'exige pas que chaque cellule soit remplie** : parfois `null + indicateur de qualité` est la donnée la plus honnête.

## 4. Détecter les valeurs atypiques : du simple à l'avancé

Une *valeur atypique* s'écarte d'une référence ; une *anomalie métier* exige un contexte (machine, mode de marche, intervention, capteur). On calcule les seuils par variable, par famille de machines et, si nécessaire, par régime. Les méthodes statistiques sont des **candidats à revue**, pas une instruction de suppression.

| Méthode et bibliothèque Python | Idée et emploi | Limite / décision |
| --- | --- | --- |
| Contrat physique ou métier : `pandas`, `pandera` | Bornes vérifiées et règles d'unité/type ; premier filtre. | Une limite métier mal définie efface de vrais incidents. |
| Quartiles / IQR : `pandas.Series.quantile` | `IQR = Q3 - Q1`, signaler hors de `[Q1 − 1,5×IQR ; Q3 + 1,5×IQR]`. Bon repérage visuel avec boxplot. | Règle indicative, fragile en distributions asymétriques ou multimodales ; aucune suppression automatique. |
| Médiane et MAD : `scipy.stats.median_abs_deviation` | `score = |x − médiane| / MAD_normalisée`, MAD normalisée avec `scale="normal"`. Plus robuste aux pics qu'une moyenne/écart-type. | Si MAD = 0, score indéfini ; traiter séparément les séries constantes. Le seuil est à étalonner. |
| Écart à une référence locale : `pandas` (médiane glissante, dérivée) | Compare au voisinage temporel du *même capteur* ; utile pour pics, dérives, capteur bloqué. | Une fenêtre centrée voit le futur ; pour une alerte en direct, utiliser seulement le passé et respecter les changements de régime. |
| `IsolationForest` : `sklearn.ensemble` | Combine plusieurs variables pour prioriser les observations rares. | Le paramètre `contamination` et la population d'ajustement influencent le seuil ; entraînement sur une période de référence, validation métier. |
| `LocalOutlierFactor` : `sklearn.neighbors` | Signale une densité locale différente de celle des voisins. | Sensible à l'échelle et au choix des voisins ; par défaut, prévu pour analyser l'échantillon ajusté, pas pour noter directement de nouvelles lignes. Pour cet usage, voir `novelty=True` et ses précautions. |

**Exemple à discuter.** À 14 h, la vibration monte alors que la température et la pression dérivent aussi. Le point sort du boxplot : capteur défectueux ou début de panne ? Examiner la courbe avant/après, l'état de la machine, la maintenance et les autres capteurs ; conserver le relevé tant que la cause n'est pas établie.

**Graphes de diagnostic :** série temporelle par machine avec points suspects et périodes d'arrêt/maintenance ; histogramme et boxplot *par régime ou machine* ; nuage vibration–température coloré par machine/état ; évolution des médianes et des valeurs manquantes dans le temps. Compter les alertes par source et par période avant de fixer un seuil.

## 5. Valeurs manquantes : choisir l'estimation et garder sa trace

Avant d'imputer, demander : absence aléatoire, capteur arrêté, machine hors service ou événement lié à l'incident ? Regarder longueur des trous, fréquence, variable, machine et régime. Une longue coupure n'est pas équivalente à un point manquant isolé.

| Stratégie / outil | Quand l'essayer | Risque et précaution |
| --- | --- | --- |
| **Ne pas imputer** ; `pandas.isna` | Capteur indisponible, cible inconnue, trou long ou valeur à ne pas inventer. | Le modèle gold devra accepter les `null`, exclure la ligne pour cet usage ou appliquer une stratégie dédiée. |
| Constante métier ; `SimpleImputer(strategy="constant")` | Code « inconnu » pour une catégorie, si défini au contrat. | `0` n'est pas une température manquante ; éviter les valeurs plausibles trompeuses. |
| Médiane par machine/régime ; `pandas.groupby`, `SimpleImputer(strategy="median")` | Référence simple sur une population comparable, pour courtes absences sans dynamique essentielle. | Aplatit la variabilité ; statistique apprise sur l'entraînement seulement pour un modèle. Prévoir repli si groupe trop petit. |
| Dernière mesure disponible ; `pandas.groupby().ffill()` | Signal lent, trou court, capteur stable. | Imposer durée maximale et séparation par machine, capteur et période de fonctionnement ; jamais de remplissage à travers une maintenance ou un arrêt. Utilise le passé uniquement. |
| Interpolation temporelle ; `pandas.Series.interpolate(method="time", limit_area="inside")` | Exploration ou réparation rétrospective de *petites lacunes internes*, si la dynamique le permet. | Elle utilise aussi un point futur : interdite telle quelle pour une prédiction en ligne à l'instant du trou. Borner la durée réelle du trou, pas seulement le nombre de lignes. |
| K plus proches voisins ; `sklearn.impute.KNNImputer` | Plusieurs variables corrélées, comparaison expérimentale sur des données comparables. | La distance dépend de l'échelle et du régime ; coûteuse ; ajuster uniquement sur l'entraînement et mesurer l'erreur. |
| Modèle itératif ; `sklearn.impute.IterativeImputer` | Référence multivariée à comparer si volume et stabilité suffisants. | Plus complexe, peut inventer des relations ; API expérimentale requérant `from sklearn.experimental import enable_iterative_imputer` avant l'import ; borner les valeurs physiquement possibles. |

**Décision pédagogique recommandée pour Indusense :** conserver la valeur source, `was_missing`, `imputation_method`, `quality_reason`, et éventuellement `value_estimated`. Comparer d'abord « pas d'imputation » et une méthode simple. Si une imputation est nécessaire dans silver pour un usage commun, elle doit être validée, déterministe, réversible et limitée aux trous autorisés. Les imputations apprises (médiane, KNN, itérative) utilisées pour un modèle appartiennent à un pipeline gold/inférence ajusté **sur l'entraînement seulement**, même si leur politique est documentée dès silver.

**Comment évaluer ?** Masquer artificiellement un petit ensemble de valeurs réellement observées dans une période d'entraînement, imputer puis comparer aux valeurs originales (erreur absolue médiane, erreurs sur pics et sur machines peu représentées). Valider aussi l'effet sur l'usage final. Ce test ne prouve pas la qualité sur les pannes de capteurs non aléatoires ; garder des cas réels pour revue humaine. Ne jamais imputer un `label` de panne à partir des capteurs.

### Exemple minimal de traçabilité (à adapter au bronze)

```python
import pandas as pd

# Colonnes et unités supposées pour l'exemple ; à confirmer dans le contrat.
df = pd.read_parquet("bronze/releves.parquet")
df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True, errors="coerce")
df["temperature_c"] = pd.to_numeric(df["temperature_c"], errors="coerce")

# Les timestamps invalides vont en quarantaine AVANT le tri ; ne pas les effacer.
quarantine = df[df["measured_at"].isna()].copy()
quarantine["quality_reason"] = "invalid_timestamp"
valid = df[df["measured_at"].notna()].copy()
valid = valid.sort_values(["machine_code", "sensor_id", "measured_at"])
valid["temperature_was_missing"] = valid["temperature_c"].isna()
valid["temperature_c_source"] = valid["temperature_c"]

# Exemple : au plus une mesure précédente, seulement si elle date de <= 5 min.
# À exécuter séparément pour chaque segment de fonctionnement sans maintenance.
keys = ["machine_code", "sensor_id", "run_segment_id"]
groups = valid.groupby(keys, dropna=False, sort=False)
previous_value = groups["temperature_c"].ffill(limit=1)
previous_time = valid["measured_at"].where(valid["temperature_c"].notna())
previous_time = previous_time.groupby([valid[k] for k in keys], dropna=False).ffill(limit=1)
short_gap = (valid["measured_at"] - previous_time).le(pd.Timedelta(minutes=5))
fill_mask = valid["temperature_was_missing"] & short_gap & previous_value.notna()
valid["temperature_c_estimated"] = valid["temperature_c"].where(~fill_mask, previous_value)
valid["temperature_imputation_method"] = "none"
valid.loc[fill_mask, "temperature_imputation_method"] = "ffill_5min_v1"
```

Ce code illustre une **règle à valider**, pas un seuil Indusense approuvé. `run_segment_id` doit être établi à partir des états/maintenances ; si ces informations manquent, ne pas appliquer ce remplissage. Les colonnes `*_source` et les identifiants de lignes doivent permettre de relier la décision au bronze. L'exemple ne dédoublonne pas : la clé et la résolution des conflits exigent d'abord le contrat.

## 6. Normalisation, validation et publication du silver

| Transformation | À faire en silver ? | Preuve à enregistrer |
| --- | --- | --- |
| Noms/types, UTC, unités physiques, codes machines | Oui, après validation du contrat. | Valeur initiale ou lien bronze, formule et version de mapping. |
| Déduplication des copies exactes | Oui, avec clé et règle explicites. | Nombre, identifiants écartés, règle de priorité. |
| Valeurs invalides et suspects | Oui : qualification, quarantaine ou champ `null` motivé. | Valeur initiale, règle, verdict, statut de revue. |
| Imputation limitée et partagée | Si besoin et validée ; conserver valeur source et indicateur. | Méthode, paramètres, version, fréquence, erreur estimée. |
| `StandardScaler`, `RobustScaler`, `MinMaxScaler` (`sklearn.preprocessing`) | En général au gold et à l'inférence. | Paramètres ajustés sur entraînement, version du pipeline, mêmes colonnes et ordre. |
| « Normalisation » d'une ligne à norme 1 (`sklearn.preprocessing.Normalizer`) | Seulement si l'usage du modèle le justifie, au gold. | Justification ; elle change le sens des grandeurs physiques. |

`RobustScaler` utilise médiane et quantiles et résiste mieux aux valeurs extrêmes que `StandardScaler` ; `MinMaxScaler` ne résout pas le problème des outliers. Aucun de ces outils ne répare une erreur de capteur.

**Contrôles de sortie à automatiser :** colonnes et types attendus ; clé unique validée ; temps valide ; unité connue ; absence de valeurs hors contrat dans les champs déclarés valides ; taux de `null` et d'imputation par variable/machine ; cohérence des indicateurs et du journal ; volumes réconciliés avec le bronze. Un contrôle échoué bloque la publication ou route le lot en quarantaine. Les seuils d'alerte se fixent après observation d'un historique représentatif et accord métier, pas à partir d'une seule journée.

**Journal minimal d'une transformation :** `run_id`, version de code et de contrat, entrée et empreinte, sortie et empreinte, ligne source, machine/capteur/temps, colonne, ancienne valeur, nouvelle valeur, motif, méthode, paramètres ou modèle d'imputation, décision humaine éventuelle, date de traitement. Conserver un manifeste par lot et une table des exceptions ; éviter de recopier tous les champs sensibles dans les journaux.

## 7. Quels graphiques ouvriront le passage vers gold ?

| Graphique / outil | Question à poser | Décision pour gold |
| --- | --- | --- |
| Série temporelle (`matplotlib`, `seaborn.lineplot`) par machine et capteur, avec trous, suspects, interventions | Le signal précède-t-il l'incident ? Les dérives suivent-elles un arrêt ou un changement de capteur ? | Choix de fenêtres et variables historiques ; repérage de fuite temporelle. |
| Carte des manquants (`seaborn.heatmap` sur indicateurs) par machine et jour | Manque-t-il surtout certaines machines, périodes ou variables ? | Qualité de la cohorte ; indicateurs de manque ; exclusions motivées. |
| Histogrammes et boxplots (`seaborn.histplot`, `boxplot`) par machine/régime | Un seuil global mélange-t-il plusieurs populations ? | Segmenter les cohortes ou créer des variables tenant compte du régime. |
| Nuages de points (`seaborn.scatterplot`) avec couleur machine/régime | Certaines relations ne valent-elles que pour un type de machine ? | Définir des interactions ou analyses séparées. |
| Matrices Pearson et Spearman (`pandas.DataFrame.corr`, `seaborn.heatmap`) sur variables numériques | Quelles variables se ressemblent ; relations linéaires ou monotones ? | Candidats à la redondance ; vérifier les couples sur les nuages de points. |
| Courbes avant/après imputation, distributions des seules valeurs imputées vs observées | La correction crée-t-elle un plateau ou gomme-t-elle des pics ? | Revoir la politique d'imputation et la durée maximale des trous. |
| Distribution par période et par groupe, puis par label **mûr et validé** | Un effet apparent vient-il d'un changement de machine, de saison ou de collecte ? | Évaluer stabilité temporelle et choix du découpage gold. |

**Lire les corrélations avec prudence :** Pearson repère surtout des relations linéaires ; Spearman, des relations monotones sur les rangs. Une corrélation globale peut être créée par le mélange de machines ou des tendances communes, et ne prouve pas une causalité. Les `null` peuvent changer le nombre de paires utilisées ; afficher ce nombre. Une corrélation avec un label n'a de sens que si le label a été validé, mûri et associé à une fenêtre de mesures **antérieure** à la prédiction. Ne pas calculer de corrélation entre features et futurs labels pour décider de nettoyer tout le silver : cela introduirait une sélection dépendante de la cible.

**Passage au gold Indusense :** définir la question de prédiction et son horizon ; associer chaque exemple à une machine et à un instant de décision ; n'utiliser que les données disponibles alors ; construire des agrégats de fenêtres passées (médiane, maximum, pente, durée du manque) ; joindre les labels finaux à la bonne fenêtre. La maquette du sprint utilise un horizon de 24 h et une consolidation de 48 h pour ses retours terrain : confirmer l'horizon du cas réel avant toute jointure. Séparer entraînement, validation et test dans le temps et empêcher le chevauchement de fenêtres d'une même machine entre ensembles si cela crée une fuite. Ajuster imputations apprises et mise à l'échelle **après** cette séparation, dans un pipeline réutilisé à l'inférence.

## 8. Travaux courts pour le groupe

1. **10 minutes — contrat.** Sur dix lignes du bronze, identifier grain, clé candidate, unité, horodatage de mesure et champ de provenance. Noter trois questions à poser au métier avant de dédupliquer.
2. **15 minutes — trois pics.** Tracer une série vibration pour une machine, superposer un boxplot par régime, puis classer trois points en « erreur certaine », « suspect » ou « plausible ». Écrire la justification et la prochaine vérification.
3. **15 minutes — deux trous.** Comparer un point manquant de 30 secondes et une coupure de 2 heures. Décider : laisser `null`, propager une valeur, interpoler pour une analyse rétrospective ou mettre en quarantaine. Décrire l'information conservée.
4. **15 minutes — préparation gold.** Tracer une matrice Pearson/Spearman et deux courbes de machines. Proposer deux variables de fenêtre et citer une fuite de données possible.

**Critère de réussite :** chaque groupe livre un petit échantillon silver avec sa clé, ses unités, ses drapeaux de qualité, son journal de corrections, un rapport avant/après et une règle écrite pour les cas non résolus. Une ligne supprimée ou imputée doit pouvoir être expliquée et reliée à la source.

## Références Python officielles

- `pandas` : [interpolation](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.interpolate.html), [corrélations](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.corr.html).
- `scipy` : [median_abs_deviation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.median_abs_deviation.html).
- `scikit-learn` : [imputation et indicateurs de manque](https://scikit-learn.org/stable/modules/impute.html), [détection d'outliers et nouveauté](https://scikit-learn.org/stable/modules/outlier_detection.html), [prétraitement et changement d'échelle](https://scikit-learn.org/stable/modules/preprocessing.html).
- `seaborn` : [API des graphiques](https://seaborn.pydata.org/api.html).
- `pandera` : [validation des DataFrames](https://pandera.readthedocs.io/en/stable/dataframe_models.html).

Les méthodes proposées servent à comparer des options. Les paramètres, seuils et unités définitifs se décident sur les relevés réels, avec les personnes qui connaissent les machines.

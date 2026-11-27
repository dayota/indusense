# Du bronze au silver : recevoir, comprendre, préparer

> **Fil conducteur.** Imaginez la réception des courses pour une cuisine collective. À la livraison, on conserve le bon de livraison et les colis tels qu'ils arrivent. Avant de cuisiner, on vérifie ce qui est arrivé, on repère les colis comptés deux fois, on lit les étiquettes, on met de côté ce qui pose question et on note chaque décision. Les données suivent la même logique.
>
> **Objectif.** À la fin, chacun doit pouvoir répondre : « Qu'avons-nous reçu ? Qu'avons-nous compris ? Qu'avons-nous changé ? Que faut-il demander au métier ? Peut-on repartir de la source ? »

## Le trajet en une minute

| Niveau | Dans la cuisine | Dans le projet de données | Question clé |
| --- | --- | --- | --- |
| **Bronze** | La livraison, le bon et l'inventaire à l'arrivée | Les lignes sources conservées telles quelles, plus les informations techniques d'ingestion | **Qu'avons-nous reçu ?** |
| **Silver** | Les produits identifiés, vérifiés, rangés et les exceptions signalées | Des données typées, harmonisées, dédoublonnées si la règle le permet, qualifiées et traçables | **Que pouvons-nous utiliser et avec quelles réserves ?** |
| **Gold** | Les ingrédients préparés pour une recette donnée | Un jeu construit pour une analyse, un indicateur ou un modèle précis | **Pour quel usage et à quel instant ?** |

Le silver n'est pas « un bronze sans trous ». Une absence expliquée, conservée et signalée vaut mieux qu'un chiffre inventé. De même, un événement rare peut être précisément celui que le projet cherche à détecter.

---

# Partie 1 — Le processus valable pour tout projet

## 1. Ce que nous savons déjà de l'ingestion bronze

Dans cet atelier, les lignes des fichiers du dossier `datas` ont été intégrées **à l'identique**. Les valeurs des colonnes sources sont gardées **en texte**. Pour chaque colonne, une colonne technique porte le **type inféré** par l'ingestion. Chaque ligne porte en outre un **checksum** destiné au repérage rapide des copies strictes, un **indice de confiance lié aux valeurs manquantes**, et un **`batch_id`** qui indique son lot d'ingestion.

| Information existante | Image du quotidien | Ce qu'elle permet | Ce qu'elle ne garantit pas |
| --- | --- | --- | --- |
| Valeur source en texte | L'étiquette telle qu'imprimée sur le colis | Retrouver exactement `"12,5"`, `"NA"` ou `"0012"` | Que ce texte soit un nombre, une absence ou un code valide. |
| Type inféré par colonne | Une proposition de rangement faite à la réception | Repérer les colonnes probablement numériques, dates, codes… | Que la proposition convienne à toutes les lignes ou au sens métier. |
| Checksum de ligne | Une empreinte du contenu du colis | Regrouper rapidement des lignes potentiellement identiques | Que deux événements métier soient le même événement ; comparer le contenu et connaître le périmètre du calcul. |
| Indice de confiance sur les manquants | Une case « livraison complète ? » sur la fiche de réception | Prioriser les questions sur les absences de valeurs | La fiabilité du capteur, du type, de l'unité ou de la mesure. |
| `batch_id` | Le numéro de livraison | Isoler un chargement, le rejouer, comparer les lots | Que les lignes de deux lots différents soient nécessairement distinctes. |

**À ne pas confondre :** une colonne de type inféré n'est pas encore une colonne réellement convertie ; un checksum n'est pas encore une décision de suppression ; l'indice de confiance mesure ici la *complétude*, pas une qualité totale.

### À la sortie du bronze : quatre artefacts à produire

Un *artefact* est simplement un résultat conservé pour que quelqu'un d'autre puisse vérifier et reprendre le travail : fichier, tableau, graphique ou compte rendu.

| Artefact | Contenu minimum | La question qu'il règle |
| --- | --- | --- |
| **1. Manifeste de lot** | `batch_id`, fichiers sources, date d'ingestion, nombre de lignes par fichier et par lot, colonnes reçues, version de la règle de checksum et périmètre des champs hachés, lien vers les sources. | « D'où viennent ces lignes et peut-on refaire l'ingestion ? » |
| **2. Portrait du bronze** | Nombre de lignes, exemples de textes bruts et de types inférés, répartition des valeurs manquantes par colonne/fichier/lot, distribution de l'indice de confiance, checksum répétés *dans et entre les lots*, dates et identifiants inhabituels. | « Où sont les zones d'incertitude ? » |
| **3. Registre des questions au métier** | Colonne ou lignes concernées, exemple source, `batch_id`, question, impact possible, personne à solliciter, statut de réponse. | « Que ne pouvons-nous pas décider seuls ? » |
| **4. Bilan de réception** | Quantités attendues si connues, quantités reçues, fichiers absents, colonnes inattendues, erreurs d'ingestion et décision : lot à étudier ou à recharger. | « L'entrée est-elle suffisamment documentée pour commencer silver ? » |

**Exemple courant.** Un bon de livraison indique dix cartons ; le registre en montre neuf. On ne complète pas le dixième carton en devinant son contenu : on note l'écart et on contacte l'expéditeur. Pour les données, une colonne vide sur tout un `batch_id` doit d'abord déclencher une recherche de cause.

**Premier arrêt collectif :** afficher le portrait du bronze avant toute conversion. Une moyenne globale de valeurs manquantes peut masquer un lot entier incomplet. Le rapport doit montrer les comptes *et* les proportions, ainsi que le nombre de lignes concernées.

## 2. Avant silver : convenir de ce que signifie chaque donnée

Le dictionnaire et les règles de transformation forment un **contrat de données**. Pour chaque colonne, inscrire son sens métier, les textes qui signifient « absent » (`""`, `"NA"`, etc., si le métier le confirme), le type attendu, l'unité, les valeurs acceptables, les cas à mettre en attente et la personne qui valide la règle.

Trois questions à poser avant de toucher aux lignes :

1. **Qu'est-ce qu'une ligne ?** Une vente, une lecture de capteur, une intervention ? Quelle combinaison de champs identifie réellement un événement ?
2. **Que signifient les valeurs ?** `"12,5"` signifie-t-il 12,5 degrés, 12,5 euros ou le code `12,5` ? `"0"` est-il un résultat réel ou une convention d'absence ?
3. **Quand et où la mesure a-t-elle été produite ?** Une date d'événement n'est pas nécessairement la date d'ingestion ; une unité ou un fuseau peuvent varier selon la source.

**Artefact préalable :** une version datée du contrat, avec les questions encore ouvertes. Une règle inconnue n'est pas remplacée par une supposition silencieuse.

## 3. Passer au silver : six gestes, avec une preuve à chaque fois

### Geste 1 — Convertir les textes, sans perdre l'original

On lit l'étiquette et on range le produit dans la bonne catégorie. Concrètement : interpréter les textes en nombres, dates, booléens ou codes **selon le contrat**, pas selon le seul type inféré. Convertir `"12,5"` demande une règle explicite de séparateur décimal ; `"0012"` peut être un code dont les zéros comptent. Un échec de conversion devient une valeur non utilisable **accompagnée du texte initial et du motif**, pas un zéro.

**Preuve :** tableau des conversions réussies et échouées par colonne et par `batch_id`, avec exemples. Le bronze reste disponible ; le silver conserve une référence à la ligne source.

### Geste 2 — Donner les mêmes repères à tout le monde

Comme on ne mélange pas kilogrammes et grammes dans une recette, harmoniser noms de colonnes, codes, unités et dates. Convertir une unité seulement quand l'unité d'origine est connue ; distinguer l'heure de l'événement de l'heure d'ingestion. Pour une date sans fuseau, demander la règle à la source avant de déclarer qu'elle est en UTC.

**Preuve :** dictionnaire silver avec nom, type, unité, formule de conversion, version de la règle et colonne source.

### Geste 3 — Distinguer copies, conflits et vrais événements

Deux scans du même colis peuvent être une copie ; deux cartons identiques peuvent être deux colis réels. Commencer par grouper les checksums égaux, puis comparer les valeurs sources et la définition du checksum. S'il couvre les colonnes techniques, ou si leur contenu varie entre lots, deux copies métier peuvent avoir des checksums différents. À l'inverse, une empreinte égale mérite vérification du contenu ; elle ne suffit pas à prouver l'identité métier.

Définir ensuite la **clé métier** : par exemple identifiant d'événement source, ou machine + capteur + instant si le métier confirme cette granularité. À clé identique et contenu identique, documenter la copie écartée du jeu d'analyse. À clé identique et contenu différent, placer le **conflit** en attente de règle ; ne pas conserver arbitrairement « la dernière ligne ». Comparer aussi les lots entre eux, car une réingestion peut recopier le précédent.

**Preuve :** registre des copies (`ligne conservée ↔ lignes écartées`), registre séparé des conflits, nombres par lot. On ne supprime rien du bronze.

### Geste 4 — Qualifier les trous et les valeurs surprenantes

Sur une facture, un prix vide et un prix à 100 fois le tarif habituel posent deux questions différentes. Pour les données, classer chaque cas : **valeur présente et plausible**, **absence à expliquer**, **conversion impossible**, **valeur physiquement impossible selon règle validée**, ou **valeur rare mais possible**.

L'indice de confiance du bronze sert de **point de départ** pour les absences : repérer les lignes à demander au métier, puis détailler *quelles colonnes manquent et pourquoi*. Il ne doit pas « couvrir » une mesure erronée. Une valeur atypique est d'abord **signalée**, jamais effacée sur un simple score statistique.

Pour repérer des cas à examiner, commencer par une règle métier et une courbe. Si cela ne suffit pas, comparer avec des valeurs semblables : la **boîte à moustaches** repère les points éloignés des quartiles ; la **médiane et la MAD** mesurent l'écart à une valeur centrale peu influencée par quelques pics. Pour plusieurs colonnes à la fois, `IsolationForest` recherche des combinaisons rares ; `LocalOutlierFactor` compare un point à la densité de ses voisins. Ces outils fournissent une **liste de candidats**, pas un verdict. Une distribution mêlant plusieurs types de machines peut rendre une mesure normale « anormale » en apparence ; comparer des groupes cohérents avant de décider.

**Preuve :** motifs de qualité par colonne et ligne, liste des cas à revoir avec exemples et réponses métier, taux d'absence et d'anomalies par groupe. Les valeurs non résolues restent visibles ou vont en quarantaine avec leur lien au bronze.

### Geste 5 — Décider si une valeur absente doit être estimée

Quand un ingrédient manque, on peut changer la recette, attendre la livraison ou utiliser un substitut documenté ; on ne prétend pas que le produit était là. Ici, **imputer** signifie produire une *estimation*, distincte de la valeur observée.

| Option | Image du quotidien et cas utile | Point de vigilance |
| --- | --- | --- |
| **Laisser vide** | « Le colis n'est pas arrivé. » Choix souvent juste si la cause est inconnue. | Prévoir comment l'usage suivant traitera cette absence. |
| **Constante métier** | « Statut inconnu » est une vraie catégorie prévue par le contrat. | Ne pas utiliser `0` comme faux nombre mesuré. |
| **Médiane d'un groupe comparable** | Estimer à partir de produits du même type plutôt que de tout le magasin. | Efface une partie de la variation ; un petit groupe donne une estimation fragile. |
| **Dernière valeur connue** | Reprendre une mesure récente si la grandeur change lentement. | Fixer une durée maximale ; ne pas traverser un arrêt ou un changement d'état. |
| **Interpolation dans le temps** | Estimer un point manquant *entre* deux observations connues. | Le point de droite est une information future : méthode réservée aux usages rétrospectifs adaptés. |
| **Voisins ou modèle multivarié** | Chercher des lignes similaires pour proposer une valeur. | Plus complexe à expliquer ; sensible aux différences d'échelle et aux relations apprises. |

En silver, privilégier **l'absence expliquée**. Si une estimation partagée est réellement nécessaire, conserver côte à côte la valeur observée (éventuellement absente), la valeur estimée, un indicateur `was_missing`, la méthode et sa version, le contexte et la décision métier. Comparer l'estimation à des valeurs connues volontairement masquées, puis vérifier qu'elle ne gomme pas les cas importants. Les méthodes qui apprennent des statistiques pour un modèle seront ajustées **sur l'entraînement uniquement**, après le découpage au niveau gold.

Les deux méthodes avancées du tableau ont des logiques différentes : `KNNImputer` estime à partir des **lignes les plus ressemblantes** ; `IterativeImputer` estime une colonne à partir des **autres colonnes**, puis recommence. Avant de les retenir, vérifier que la ressemblance a un sens métier, que les mesures sont comparables et que le gain face à une méthode simple est réel. Elles ne peuvent pas retrouver avec certitude ce qu'un capteur n'a pas mesuré.

**Preuve :** registre d'imputation (qui, quoi, comment, sur quelle période et avec quelle version), comptages avant/après et exemples comparés visuellement. Aucune étiquette de résultat futur n'est « imputée » à partir des mesures.

### Geste 6 — Contrôler et publier

On refait l'inventaire après rangement. Vérifier les colonnes, les types, les unités, les clés, les dates, les taux de valeurs manquantes, les duplications restantes, les conflits et l'explication des écarts. Une ligne exclue du silver analysable doit apparaître dans le registre de copies ou dans la quarantaine.

**Preuve :** rapport de qualité silver et bilan de rapprochement bronze → silver, avec `batch_id`, version du contrat et version du traitement. Si une règle obligatoire échoue, le lot attend une correction ou une validation ; on ne publie pas un résultat silencieusement incomplet.

### Le paquet de sortie silver

| Artefact à remettre | À quoi sert-il ? |
| --- | --- |
| **Dataset silver versionné** | Lire les champs typés et harmonisés, avec références aux lignes et aux `batch_id` bronze, et indicateurs de qualité. |
| **Contrat et dictionnaire silver** | Comprendre noms, types, unités, clés et règles effectivement appliquées. |
| **Journal des transformations** | Retracer les conversions, corrections, estimations, déduplications et versions de traitement. |
| **Registres copies / conflits / quarantaine** | Savoir où sont passées les lignes non retenues et quels cas attendent une décision. |
| **Rapport de qualité et graphiques** | Comparer bronze et silver, montrer les manquants, les valeurs rares et les effets des décisions. |
| **Liste de questions métier et décisions** | Éviter de transformer une incertitude en vérité technique. |

Le contrôle de rapprochement doit expliquer les volumes **par lot et par statut** : lignes bronze reçues, lignes silver retenues, copies exactes écartées, lignes en quarantaine et conflits, selon des catégories mutuellement exclusives. Si une ligne retenue porte aussi un drapeau « suspect », elle reste dans les lignes retenues : on ne la compte pas deux fois.

## 4. Voir les données avant de préparer gold

Les graphiques sont des instruments de conversation, comme étaler les ingrédients sur la table avant de choisir une recette.

| Vue | Question simple | Usage de la réponse |
| --- | --- | --- |
| Barres des absences par colonne, fichier et `batch_id`, puis distribution de l'indice de confiance bronze | « Le manque est-il diffus ou concentré sur une livraison ? » | Revenir vers la bonne source et prioriser les corrections. |
| Courbe des valeurs dans le temps avec trous et événements | « Le pic est-il isolé ? Suit-il un changement connu ? » | Séparer erreur probable et phénomène métier possible. |
| Histogrammes et boîtes à moustaches par groupe comparable | « Comparons-nous des choses de même nature ? » | Discuter seuils et segmentations, sans suppression automatique. |
| Nuage de deux variables et matrice de corrélation | « Quelles mesures évoluent ensemble ? » | Proposer des hypothèses de variables pour gold. |
| Avant/après conversion, déduplication et éventuelle imputation | « Le traitement a-t-il changé l'histoire racontée par les données ? » | Revoir une règle qui efface une variation utile. |

Une **corrélation** indique que deux variables varient ensemble dans les données observées ; elle ne prouve pas qu'une variable cause l'autre. La calculer sur des données typées et comparables, et afficher combien de couples de valeurs sont réellement présents. Comparer, si utile, Pearson (relation plutôt linéaire) et Spearman (relation monotone). Les graphiques avec un résultat futur ne deviennent pertinents qu'après la définition des exemples gold et la validation des résultats.

**Frontière silver → gold :** silver est réutilisable par plusieurs analyses ; gold sélectionne une population, une période, une cible et construit les variables pour *un usage*. La mise à l'échelle pour un modèle (`StandardScaler`, `RobustScaler`, `MinMaxScaler`) appartient généralement au pipeline gold et à l'inférence, ajusté uniquement sur les données d'entraînement. Elle ne remplace ni la conversion des unités, ni la qualification des erreurs du silver.

---

# Partie 2 — Appliquer le processus à Indusense

## 5. La question métier et les objets à reconnaître

Indusense vise notamment à exploiter des mesures de machines pour éclairer un risque de panne. Une vibration élevée peut être une erreur de capteur **ou** un signe précoce utile. Une température seule peut ne rien dire sans l'état de la machine. C'est pourquoi le silver doit préserver les observations et les doutes plutôt que fabriquer d'emblée un tableau « parfait ».

La maquette du sprint contient un **gold synthétique** avec `machine_code`, `predicted_at`, `temperature`, `vibration`, `pressure`, `label`. Ce fichier illustre un usage aval ; il n'est pas le bronze réellement ingéré par les stagiaires. Les noms des colonnes, les unités, les clés et la fréquence des fichiers `datas` doivent être relevés dans **leur** portrait du bronze. Les tâches ci-dessous sont à appliquer à leurs fichiers, sans prétendre que toutes les sources ont déjà le même schéma.

### Après l'ingestion bronze d'Indusense

1. Produire le **manifeste par `batch_id` et par fichier** : lignes attendues/reçues, colonnes, version du checksum. Vérifier si l'empreinte porte seulement sur les champs sources ou aussi sur des champs techniques ; cette réponse conditionne son emploi entre lots.
2. Produire le **portrait des valeurs texte et des types inférés** : exemples de nombres avec virgule/point, dates, identifiants de machine, codes d'état, textes d'absence. Signaler les colonnes où le type inféré paraît incohérent avec le métier.
3. Cartographier les **manquants et l'indice de confiance** par fichier, machine, variable et lot. Rechercher une machine entière absente, une période sans relevés ou un seul capteur muet.
4. Grouper les **checksums répétés**, au sein d'un lot et entre lots, puis relever les mêmes clés métier avec contenus divergents. Ne rien dédupliquer encore sans validation de la clé.
5. Transmettre les questions : unité de chaque mesure, cadence, fuseau, identifiant du capteur, machine arrêtée ou active, signification des valeurs manquantes et des codes spéciaux, plages physiquement impossibles.

**Exemple à raconter en cours.** Un lot affiche une confiance moyenne élevée, mais la vibration manque précisément pour une machine pendant un arrêt. Le score global ne dit ni si l'absence est normale, ni si l'arrêt précède un incident. Le tableau par machine et par période permet de poser la bonne question au responsable métier.

### Construire le silver d'Indusense

| Décision | Travail concret | Artefact ou preuve |
| --- | --- | --- |
| Identifier le relevé | Valider l'identifiant d'événement ou la combinaison machine, capteur, instant de mesure et éventuelle source. | Définition de la clé ; cas qui ne s'y conforment pas. |
| Taper les champs | Convertir les textes selon les règles de chaque fichier : identifiants restent des codes, mesures deviennent numériques si possible, dates interprétées avec le bon fuseau. | Rapport de conversion et valeurs source liées aux erreurs. |
| Harmoniser les mesures | Noms, unités et instants cohérents ; distinguer l'instant mesuré de l'instant ingéré. | Dictionnaire et formules versionnées. |
| Traiter les duplications | Vérifier checksum et contenu ; résoudre copies exactes, réserver les mesures contradictoires à la revue. | Registres de copies et conflits, y compris entre `batch_id`. |
| Qualifier | Distinguer mesure manquante, capteur défaillant, valeur impossible validée par le métier et pic plausible. | Drapeaux, motifs, quarantaine et questions ouvertes. |
| Préserver l'information | Garder les mesures originales ou leur lien bronze ; si estimation nécessaire, la rendre visible à côté de l'observation. | Journal d'imputation et comparaison avant/après. |

**Valeurs atypiques à examiner, pas à gommer.** Commencer par des courbes vibration, température et pression **par machine et dans le temps**, avec périodes de maintenance et d'arrêt si elles sont disponibles. Comparer ensuite des machines de même type ou dans le même régime. Un seuil physique validé peut signaler une erreur certaine ; une valeur seulement rare reçoit un drapeau et une revue. Si un retour métier mentionne `SENSOR_ISSUE`, le relier aux mesures concernées sans transformer automatiquement tout pic en défaut de capteur.

**Manquants à examiner.** Un relevé isolé absent et une panne de transmission de deux heures ne se traitent pas de la même façon. Sans cadence, états machine et règle de durée validées, laisser la mesure absente. Si une propagation ou une interpolation est autorisée, enregistrer la durée du trou, la méthode et la valeur estimée séparément. Une interpolation utilisant une observation future ne doit pas être réutilisée telle quelle pour prédire en direct.

### Préparer ensuite le gold, sans le fabriquer dans le silver

Avec le silver publié, les stagiaires peuvent tracer :

- les trois courbes de mesures par machine avec trous, pics et interventions ;
- une carte des absences par machine, capteur et période ;
- des histogrammes/boîtes à moustaches par type de machine et régime ;
- des nuages vibration–température et une matrice de corrélations sur des populations comparables ;
- une comparaison des séries avant et après toute estimation.

Ces vues permettent de proposer des **fenêtres de mesures antérieures à l'instant de prédiction** et des résumés (niveau, maximum, évolution, durée sans signal). Le gold pourra ensuite joindre des **labels de panne validés et mûrs**, définir l'horizon et séparer les périodes d'entraînement, de validation et de test. Le sprint présente, pour sa maquette, un horizon de 24 heures et une consolidation de 48 heures ; vérifier la règle du projet réel avant de l'adopter. Une intervention, un diagnostic ou une mesure arrivés après l'instant de prédiction ne doivent pas devenir une variable censée être connue avant cet instant.

## 6. Petite mise en situation pour les stagiaires

**Trois lignes, trois décisions.** Pour un même fichier et un `batch_id` donné, choisir :

1. Une ligne possède le même checksum et les mêmes valeurs source qu'une autre. **Question :** copie d'ingestion ou événement métier répété ? Quelle clé et quel rapport faut-il consulter avant de décider ?
2. Le texte de température est `"NA"`, le type inféré indique « texte » et l'indice de confiance est faible. **Question :** que peut-on affirmer du texte reçu, et que faut-il vérifier avant de le traiter comme une absence ? Quelle cause demander au métier ?
3. Une vibration est très haute juste avant une intervention. **Question :** quel graphique et quel contexte regarder avant de la qualifier ? Que perdrait-on en l'effaçant ?

**Restitution attendue :** une page avec le portrait du lot, les questions métier, trois décisions justifiées et les artefacts qui permettront de retrouver chaque ligne. L'objectif n'est pas d'avoir « zéro valeur manquante » : c'est de pouvoir défendre chaque transformation.

## Aide-mémoire Python, si l'on passe à l'implémentation

| Besoin | Bibliothèques / fonctions utiles | Documentation |
| --- | --- | --- |
| Profiler, convertir, regrouper, repérer les doublons et calculer des corrélations | `pandas` (`to_numeric`, `to_datetime`, `groupby`, `duplicated`, `corr`) | [Documentation pandas](https://pandas.pydata.org/docs/) |
| Valider un contrat de colonnes et de valeurs | `pandera` | [Documentation Pandera](https://pandera.readthedocs.io/en/stable/) |
| Visualiser distributions, boîtes, nuages, courbes et cartes | `seaborn`, `matplotlib` | [API seaborn](https://seaborn.pydata.org/api.html) |
| Repérer les valeurs rares | Quartiles avec `pandas`; médiane/MAD avec `scipy.stats.median_abs_deviation`; éventuellement `sklearn.ensemble.IsolationForest` ou `sklearn.neighbors.LocalOutlierFactor` | [SciPy MAD](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.median_abs_deviation.html) ; [scikit-learn, détection d'anomalies](https://scikit-learn.org/stable/modules/outlier_detection.html) |
| Comparer les imputations | `pandas` (`ffill`, `interpolate`) ; `sklearn.impute.SimpleImputer`, `KNNImputer`, `IterativeImputer` | [pandas interpolate](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.interpolate.html) ; [scikit-learn, imputation](https://scikit-learn.org/stable/modules/impute.html) |
| Préparer des variables pour un modèle gold | `sklearn.preprocessing.StandardScaler`, `RobustScaler`, `MinMaxScaler` dans un pipeline ajusté sur l'entraînement | [scikit-learn, prétraitement](https://scikit-learn.org/stable/modules/preprocessing.html) |

**Ordre conseillé :** contrat métier → règles simples → graphiques et revue → méthodes statistiques si elles apportent quelque chose. Les algorithmes produisent des *indices* ; le registre des décisions explique pourquoi une ligne a finalement été conservée, estimée ou écartée de l'analyse.

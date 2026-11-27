# Développer InduSense en local

Le dépôt rassemble une interface Nuxt, une API FastAPI et un moteur Python partagé de cartes d’identité CSV et PostgreSQL. Les notebooks importent le même moteur que l’API. PostgreSQL reste accessible à DataGrip sur la boucle locale ; Traefik expose les interfaces HTTP.

## Organisation

| Emplacement | Responsabilité |
| --- | --- |
| [apps/ui](apps/ui/) | Interface Nuxt, dépendances Node et verrou pnpm |
| [apps/api](apps/api/) | API FastAPI, accès PostgreSQL et tests HTTP |
| [packages/ingestion](packages/ingestion/) | Analyse CSV/SQL, conversions, statistiques et rapports |
| [config](config/) | Catalogue des types et contrats CSV |
| [datas](datas/) | Sources de référence, montées en lecture seule dans l’API |
| [artifacts](artifacts/) | Rapports générés et références historiques |
| [notebooks](notebooks/) | Exploration et démonstration du moteur partagé |
| [infra/monitoring](infra/monitoring/) | Prometheus, Alertmanager et provisioning Grafana |
| [tests](tests/) | Vérifications du skill et intégration entre composants |

Le [workspace uv](pyproject.toml) gère les deux paquets Python avec un seul [verrou](uv.lock). Le projet conserve Python 3.15. L’interface utilise Node 24 et pnpm 10.33.3, également disponibles dans son image Docker.

L’interface reprend le [template Dashboard officiel Nuxt UI](https://github.com/nuxt-ui-templates/dashboard), adapté aux parcours InduSense : barre latérale repliable, recherche de navigation, vue d’ensemble, panneaux, formulaires, tableaux, fenêtres de création et historique latéral. Sa [licence MIT](apps/ui/LICENSE.nuxt-dashboard) est conservée. La police Public Sans et les icônes Lucide sont embarquées localement ; le thème clair/sombre suit les composants Nuxt UI.

## Prérequis locaux

- Docker Engine et Docker Compose.
- Le Traefik local déjà configuré avec le provider Docker, les entrypoints `web` (HTTP) et `websecure` (HTTPS), et le réseau externe `localhost-proxy`.
- La résolution de `indusense.localhost` et des sous-domaines de monitoring vers `127.0.0.1` sur la machine du navigateur.

La stack ne crée pas un second Traefik. Vérifier son état avec `docker ps` et la présence du réseau avec `docker network inspect localhost-proxy`.

Copier [.env.example](.env.example) vers `.env` et ajuster les identifiants locaux avant le premier démarrage. Les valeurs par défaut sont destinées au développement. Pour les fichiers générés par l’API, `LOCAL_UID` et `LOCAL_GID` peuvent être définis dans `.env` à partir de `id -u` et `id -g` ; leur valeur par défaut est 1000.

## Démarrer les applications

Mode développement avec rechargement automatique :

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --wait
```

Les sources Python et Nuxt sont montées depuis le dépôt. Les dépendances Python restent dans l’image ; les dépendances Node et les fichiers Nuxt générés utilisent des volumes dédiés.

Le service ponctuel `migrate` applique les migrations Alembic après le contrôle de santé PostgreSQL et avant le démarrage de l’API. Les schémas `bronze`, `silver` et `gold` sont créés dans la même base. Silver contient les contrats, résultats de préparation et lignes en attente de résolution ; gold reste à implémenter.

Le catalogue dispose d'une migration initiale consolidée :
[`0001_initial`](apps/api/migrations/versions/0001_initial.py). Elle crée directement
le schéma complet sur une base neuve. Les anciennes révisions `0001` à `0008`
ont été regroupées ; les migrations Bronze générées pour chaque modèle restent distinctes.
Pour une base existante déjà à l'ancien état `0008_model_database`, vérifier que
son schéma correspond intégralement aux modèles actuels, puis remplacer seulement
le repère Alembic avec `.venv/bin/alembic -c apps/api/alembic.ini stamp --purge 0001_initial`.
Cette opération ne doit pas servir à ignorer des changements de schéma manquants.

| Accès | Adresse |
| --- | --- |
| Application | https://indusense.localhost |
| Modèles, datasets et téléversement | https://indusense.localhost/modeles |
| Documentation FastAPI | https://indusense.localhost/api/docs |
| Santé du processus API | https://indusense.localhost/api/health |
| Disponibilité PostgreSQL depuis l’API | https://indusense.localhost/api/ready |
| Métriques de l’API | https://indusense.localhost/api/metrics |

Le navigateur appelle `/api` sur la même origine. Lors du rendu serveur, Nuxt utilise `http://api:8000/api`. Traefik conserve le préfixe `/api` et donne priorité au routeur FastAPI. Les ports internes 3000 et 8000 ne sont pas publiés sur l’hôte.

L’application et l’API restent accessibles en HTTP. Les routeurs HTTPS utilisent
le certificat fourni par le Traefik local ; aucun certificat ni résolveur ACME
n’est créé par cette stack.

Nuxt Icon utilise `/_icons`, servi par Nuxt, pour éviter le préfixe `/api` réservé à FastAPI. Les icônes sont chargées depuis la collection Lucide locale, sans repli vers un service externe.

Pour lancer les images compilées sans les montages de développement :

```bash
docker compose up -d --build --wait
```

Pour arrêter la stack sans supprimer ses volumes :

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile monitoring down
```

Après modification des dépendances Python, reconstruire l’image API. Pour Nuxt, mettre à jour le verrou avec pnpm, reconstruire l’image et synchroniser le volume de dépendances avec `docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps ui pnpm install --frozen-lockfile`.

## Connexion DataGrip

Créer une connexion PostgreSQL avec l’hôte `127.0.0.1`, le port `DB_PORT` (5432 par défaut), la base `DB_NAME`, l’utilisateur `DB_USER` et le mot de passe `DB_PASSWORD`. Avec les valeurs par défaut : base `indusense_db`, utilisateur `indusense_user`, mot de passe `dbpassword`.

`DB_NAME` est le catalogue de l’application. Pour consulter les données typées d’une
version, utiliser la base du modèle affichée dans l’interface, avec le même hôte,
port et compte. Son schéma par défaut est `versionning` ; les données sont dans
`"<version>-bronze"`. Les anciennes bases séparées par version restent consultables.

Si le port local est occupé, choisir par exemple `DB_PORT=5433`. L’API continue à utiliser `db:5432` à l’intérieur du réseau Docker.

PostgreSQL utilise le volume `indusense-db-data` par défaut. Changer le mot de passe d’initialisation ne modifie pas celui d’un volume déjà initialisé. Un changement majeur de version PostgreSQL nécessite une migration de ses données.

## Modèles, datasets et bronze

Depuis Nuxt, créer un modèle et sa première version. Le formulaire Bronze comporte
cinq onglets, avec glissement vers l’étape suivante et navigation Retour/Suivant :

1. **Fichiers** : cliquer sur **Téléverser les fichiers** ou sur la zone de dépôt
   pour choisir un ou plusieurs CSV ou SQL, puis **Suivant** pour les téléverser.
   L’API archive les octets originaux dans `datas/ingestion/<modele_normalise>/<version>/inputs/`
   avec leurs noms de fichiers d’origine, puis les associe au brouillon.
   Les chemins directs `<version>/<nom_fichier>` ne sont plus utilisés ni acceptés
   pour les sources téléversées ; l'archivage, la consultation et les contrats utilisent `inputs`.
   Aucune base de dataset n’est encore créée. L’onglet **Fichiers** propose **Consulter** et
   **Télécharger l’original** ; l’aperçu est limité à 128 Kio et le téléchargement
   conserve l’intégralité des octets. Retirer un fichier du brouillon conserve son
   archive dans l’historique de la version. Un autre contenu sous le même nom est
   refusé pour préserver l’original ; une nouvelle version possède son propre dossier.
2. **2. Contrats** : le seul contrat existant proposé est le YAML correspondant dans
   `datas/ingestion/<modele>/_contracts/`. Pour un CSV, il porte le nom
   du fichier sans son extension CSV, suivi de la version du contrat :
   `<nom_fichier>-<version_contrat>.yml`. Pour un SQL, chaque table dispose de son
   propre `<nom_table>-<version_contrat>.yml` (par exemple `machine-1.0.0.yml` et
   `maintenance-1.0.0.yml`). La version est celle du YAML et doit correspondre au
   nom du fichier ; les anciens noms sans version restent lisibles. Le chargement
   choisit automatiquement la version sémantique la plus élevée : `1.10.0` vient
   après `1.9.0`. Le dossier du modèle conserve seulement cette dernière recette.
   Une demande API visant explicitement une ancienne version est refusée ;
   aucune sélection d'une autre version n'est proposée dans l'interface.
   Chaque sauvegarde archive aussi le contrat utilisé sous
   `datas/ingestion/<modele>/<version_modele>/_contracts/<nom>-<version_contrat>.yml`.
   Les sauvegardes d'une autre version du modèle ne modifient pas ces copies.
   Les versions déjà sauvegardées conservent également leur instantané en base.
   Aucun contrat d’un autre modèle n’est proposé dans l’interface.

   Lors de la sauvegarde, `source.path` contient le chemin complet de l'original :
   `/datas/ingestion/<modele>/<version>/inputs/<nom_fichier>`. La recette commune au modèle
   est adaptée à la version sélectionnée avant sauvegarde, sans modifier les
   instantanés des anciennes versions. Le préfixe `/datas/ingestion/` est résolu
   dans la racine du projet, y compris après extraction d'un export hors ligne.

   Quand le YAML correspondant est absent, un formulaire permet de générer le
   contrat : source, table cible, clé métier, colonnes, types, type PostgreSQL Silver,
   unités, nullabilité, descriptions, seuil d’erreurs et opérations dérivées.
   Un contrat existant apparaît dans ce même formulaire en consultation.
   **Modifier le contrat** ouvre une popup pour choisir un incrément correctif,
   mineur ou majeur, puis active l'édition et **Sauvegarder le(s) contrat(s)**.
   Annuler ne change ni la version ni le mode de consultation. Pour un nouveau
   contrat, la sauvegarde est disponible directement et la modification est désactivée.
   Les types et opérations proviennent directement de `bronze.v2.schema.json`.
   Les clés métier et unités restent explicites. **Sauvegarder le(s) contrat(s)**
   valide le lot contre le schéma et les sources réelles avant d’écrire les YAML
   dans `_contracts`. Le SQL est analysé sans exécution et toutes ses tables doivent
   avoir un contrat ; seules les colonnes effectivement fournies par les INSERT
   peuvent être déclarées.
   **Suivant** soumet également les formulaires : une erreur de validation maintient
   l'étape 2. Après acceptation, l'API génère les cartes d'identité en réutilisant
   les calculs de statistiques et les rendus Markdown existants, adaptés aux contrats v2.
   Enregistrer seul ne passe plus automatiquement à l'étape suivante.
3. **Cartes d’identité** : consulter les rapports enregistrés dans
   `datas/ingestion/<modele>/<version>/artifacts/ingestion-<nom_fichier>.md`, puis
   **Suivant** pour confirmer cette étape. Le nom complet est conservé :
   `ingestion-telemetry.csv.md` ou `ingestion-machine.sql.md`.
   Les cartes contiennent la source sous `inputs`, la taille, les horaires de début
   et de fin, l'encodage déclaré, les dimensions, les colonnes et leurs types du contrat,
   et les statistiques applicables du catalogue. Les identifiants et valeurs invalides
   sont exclus des statistiques numériques. Le rapport SQL décrit toutes les tables,
   les instructions, les omissions et les valeurs par défaut sans les exécuter.
   Les cartes doivent avoir été générées pour permettre leur validation.
4. **Chargement des données** : le SQL Alembic est préparé après confirmation des
   cartes. Le relire, puis **Approuver et lancer le chargement**. Le robot animé
   accompagne les phases réelles de migration, ingestion et publication. La revue est liée par SHA-256 aux
   octets sources, aux contrats, à leurs révisions et au script. Un changement
   invalide l’approbation. Les `derived_columns` sont des déclarations pour Silver,
   sans création de colonne fictive ni exécution de transformation métier.
5. **Rapports et validation** : consulter les métriques, batch IDs et dictionnaires
   dans **Rapport d'ingestion**, puis les tables et logs paginés en lecture seule
   dans **Revue**. Cliquer sur **Valider le bronze dataset**. Le bouton reste bloqué tant que tous les
   lots et leurs rapports ne sont pas scellés. Il ouvre explicitement Silver.

Après création, les étapes précédentes sont en **consultation seule**, dans l’UI et
l’API. Les versions existant avant la migration v2 restent entièrement en
consultation, sans reconstruction. Une nouvelle version peut reprendre leurs
fichiers originaux ; les anciens contrats v1 et décisions humaines ne sont pas
appliqués au nouveau parcours.
Le bouton **Journal** affiche la timeline de la version dans un panneau latéral.

### Statuts des versions de modèle

Chaque version possède exactement un statut parmi `ingestion-bronze`, `ingestion-silver`, `ingestion-gold`, `training`, `challenger` et `champion`. Une nouvelle version commence en `ingestion-bronze`, même si elle reprend les datasets d’un champion. La migration attribue aussi ce statut aux versions préexistantes.

Pour chaque modèle, il peut exister au maximum un champion et un challenger. Deux index uniques partiels PostgreSQL garantissent ces règles, y compris pour des écritures concurrentes ou directes en base. Les autres statuts peuvent être partagés par plusieurs versions. Des modèles différents peuvent chacun posséder leur champion et leur challenger.

Le statut est en lecture seule. Le nouveau formulaire garde `ingestion-bronze`
après chargement : seul **Valider Bronze** autorise `ingestion-silver`. Les casts
en erreur sous le seuil ne suppriment pas les lignes ; les valeurs brutes restent
consultables et les motifs sont dans `_cast_errors`. Les corrections et
transformations suivantes relèvent de Silver, hors du périmètre de cette évolution.

L’API calcule le statut suivant ; le client ne peut pas choisir sa cible, revenir en arrière ou sauter une étape. Le verrou du modèle empêche deux validations simultanées de faire progresser deux fois la version. Les validations et transitions sont historisées. Les validations gold, entraînement et promotion challenger/champion seront ajoutées avec leurs workflows ; aucun sélecteur manuel ne permet de les anticiper.

Le brouillon accepte au maximum 10 fichiers et 100 Mio au total, avec 25 Mio par
fichier et 200 000 caractères par contrat. Les propositions ne choisissent pas de
clé métier ni d’unité inconnue : il faut les renseigner. L’encodage et les
séparateurs sont déclarés, jamais devinés. Une nouvelle sauvegarde invalide la
confirmation des cartes d’identité et la revue de migration. Les contrats sauvegardés
sont ensuite retrouvés dans le dossier `_contracts` de cette version.

### Convertisseurs disponibles

[converters.yaml](config/converters.yaml) recense les fonctions du registre Python
et les types qu’elles prennent en charge. `GET /api/converters` vérifie que ce
fichier correspond encore au code. Ce catalogue concerne les moteurs historiques ;
le parcours v2 déclare les opérations futures via `derived_columns` (`MERGE`,
`NORM`, `STD`, `ENC`, `ANO`, `DEL`, `IMP`, `OUT`) et ne les exécute pas en Bronze.

Pour actualiser ou vérifier ce fichier :

```bash
uv run --all-packages --locked python packages/ingestion/scripts/update_converters.py --root .
uv run --all-packages --locked python packages/ingestion/scripts/update_converters.py --root . --check
```

### Intégrité et doublons

L’API calcule toujours le SHA-256 des octets reçus. Si le client fournit aussi son
empreinte dans le manifeste, une différence provoque un refus.

Dans le formulaire, le couple version/empreinte est unique : un fichier identique,
même renommé, est reconnu sans être ajouté deux fois. Les écritures du modèle sont
sérialisées par un verrou PostgreSQL. Deux créations simultanées ne créent pas deux
datasets. Les anciennes sources et les snapshots du catalogue sont conservés pour
la compatibilité et l’historique.

L’empreinte reconnaît les fichiers identiques octet pour octet. Changer l’encodage
ou l’ordre des lignes change l’empreinte. Les lignes répétées sont conservées ; la
clé métier est déclarée par l’utilisateur. Le rejeu utilise la clé primaire
`(_source_hash, _row_number)` et un reçu transactionnel associant SHA-256 du fichier
et contenu exact du contrat sauvegardé. Une recette différente exige une nouvelle
version ; un rejeu identique est journalisé `SKIPPED` sans réinsérer de ligne.

### Stockage et analyse

La base `DB_NAME` contient le catalogue des modèles et versions, le journal, les
brouillons et leurs fichiers originaux en `bytea`, ainsi que la file persistante des
chargements. La création produit une base par modèle (nom normalisé, limité à 63 octets),
avec `versionning` comme schéma par défaut. Ce schéma conserve les versions, leurs
événements, les exécutions, les lots et leurs métriques. Chaque version isole ses données
dans `"<numero>-bronze"`, avec ses sceaux et ses logs `_ingestion_errors` conservés après
rollback. Le compte PostgreSQL de l’API doit pouvoir créer des bases. Une base portant
le marqueur de propriété de ce modèle peut être réutilisée ; une base étrangère est
refusée et n’est jamais remplacée. Les bases historiques gardent leur organisation.

Les exécutions sont suivies par `POST /api/model-versions/{id}/bronze/executions` et
`GET /api/model-versions/{id}/bronze/executions/current`. Un rechargement de Nuxt retrouve
le traitement ; un redémarrage de l'API reprend les demandes persistées avec les mêmes
révisions. L'idempotence empêche de réinsérer les lots déjà scellés.

Chaque colonne déclarée produit `<target_name>_raw` en TEXT et une colonne typée
au mieux. Une cellule vide produit NULL sans erreur ; une cellule non convertible
reste dans le miroir brut avec NULL typé et un motif dans `_cast_errors`.
`nullable` est une attente Silver et ne rejette pas une ligne Bronze.

Chaque ligne porte `_batch_id`, `_source_file`, `_source_hash`, `_row_number`,
`_ingested_at`, `_cast_errors` et `_row_checksum`. Le checksum est celui du JSON
canonique de la ligne source analysée ; il n’est pas une contrainte de déduplication.
Les dates UTC sont étiquetées sans décaler l’heure ; une valeur explicitement dans
un autre fuseau est signalée comme erreur de cast.

Les CSV sont parcourus en flux ; le dump SQL est analysé intégralement par SQLGlot,
jamais exécuté. Le chargement écrit par lots de 5 000 lignes et transaction par
configuration. Dépasser `max_cast_error_ratio` annule cette configuration, sans
annuler une autre configuration réussie. Un échec PostgreSQL annule le lot entier ;
les octets sources restent archivés, y compris pour une cellule non représentable
en TEXT PostgreSQL. Aucun correctif ou rejet humain ne modifie Bronze.

Si `max_cast_error_ratio` est absent, sa valeur par défaut est `0.0` : une seule
ligne portant une erreur de cast annule le chargement de cette configuration.
Les quatre contrats de référence et les propositions indiquent explicitement `0.0`.

Le catalogue central `bronze.ingestion_batches_log` conserve chaque tentative dans
des transactions séparées, même en cas de rollback. Les statuts sont RUNNING,
SUCCESS, PARTIAL, FAILED ou SKIPPED. Les rapports JSON et dictionnaires, avec
section `transformations`, sont conservés en base et publiés sous
`artifacts/bronze/<batch_id>/`. Les dérivations futures y sont distinguées des
casts effectués. Une interruption de publication peut être réparée par rejeu sans
duplication. La création de base est hors transaction ; une interruption entre sa
création et l’enregistrement du lien peut laisser une base orpheline, jamais
réutilisée automatiquement.

Les mappings sont décrits dans le [catalogue](apps/api/src/indusense_api/catalog.py), les migrations dans [migrations](apps/api/migrations/), et le parcours métier dans [workflow.py](apps/api/src/indusense_api/services/workflow.py).

### API du formulaire Bronze

Les routes sous `/api/model-versions/{id}/bronze` suivent le formulaire :

| Action | Route |
| --- | --- |
| État, fichiers, rapports et résultat | `GET /` |
| Téléverser (`files` + manifeste JSON) | `POST /files` |
| Retirer un fichier du brouillon | `DELETE /files/{file_id}` |
| Archiver les sources déjà présentes ou héritées | `POST /files/archive` |
| Consulter une archive (encodage explicite facultatif) | `GET /files/{file_id}/preview` |
| Inventorier les tables SQL, sans exécution | `POST /files/{file_id}/inspect-sql` |
| Télécharger les octets originaux | `GET /files/{file_id}/download` |
| Choisir et charger les contrats | `POST /contracts/load` |
| Sauvegarder les contrats modifiés | `POST /contracts/save` |
| Confirmer les cartes d’identité | `POST /identities/confirm` |
| Catalogue des contrats v2 | `GET /contracts/catalogue` |
| Générer la migration à revoir | `POST /migrations/generate` |
| Approuver son empreinte | `POST /migrations/approve` |
| Charger ou rejouer | `POST /create` |
| Valider explicitement Bronze | `POST /validate` |
| Exporter sources, recettes et rapports | `GET /export` |
| Consulter les lignes intégrées | `GET /rows?table=...` |

Les fichiers et révisions transmis doivent appartenir à la version et correspondre
à l’intégralité de sa préparation. Une révision périmée est refusée. Les mutations
des fichiers et contrats sont refusées après création, même par appel direct.

Les archives sont indexées dans `bronze.source_archives`, indépendamment des
fichiers actifs du brouillon. Les lectures vérifient leur taille et leur SHA-256.
Le montage Docker `datas` reste en lecture seule ; seul son sous-dossier
`datas/ingestion` est monté en écriture pour l’API. Ce dossier est exclu de Git.

### API historique conservée

Les routes de lecture restent disponibles. Les mutations des versions antérieures
sont refusées ; les nouvelles versions utilisent exclusivement le formulaire v2.
Les descriptions ci-dessous documentent le format historique, pas un autre chemin
de création de Bronze v2.

Créer un modèle via `POST /api/models` avec `name` et éventuellement `description`. La réponse contient `id` et `version_id`. `POST /api/models/{id}/versions` crée une version ; le champ facultatif `from_version_id` permet de reprendre les datasets d’une version du même modèle.

`POST /api/model-versions/{id}/validate-stage` reçoit `{"stage": "bronze"}` ou `{"stage": "silver"}` et renvoie la version mise à jour après contrôle des conditions. Une étape inactive ou incomplète donne HTTP 409. L’ancienne route `PATCH /api/model-versions/{id}/status` refuse toute modification manuelle avec HTTP 405. Le catalogue et les détails des versions exposent le statut en lecture seule.

`POST /api/model-versions/{version_id}/uploads` reçoit un formulaire multipart avec des champs répétés `files` et un champ `manifest` contenant une liste JSON. Les entrées du manifeste correspondent aux fichiers dans le même ordre :

```json
[
  {"dataset_name": "telemetry", "contract": "telemetry", "mode": "snapshot"},
  {"dataset_name": "machines", "contract": null, "mode": "snapshot"}
]
```

Chaque entrée peut inclure `sha256`. Le résultat par fichier indique `created`, `reused` ou `duplicate`, l’identifiant et le numéro du snapshot ainsi que son résumé de qualité. Un contrat CSV est obligatoire pour un CSV et interdit pour le SQL. Les UUID et manifestes sont validés ; seul le mode `snapshot` est accepté.

`POST /api/model-versions/{version_id}/preload` utilise le même formulaire multipart.
Les entrées indiquent `contract_mode: "existing"` et une référence `contract`, ou
`contract_mode: "generate"`. Sa réponse conserve l’ordre des fichiers et fournit
pour chacun `filename`, `sha256`, `contract_yaml` (null pour SQL) et `summary`.
Le chargement final ajoute `contract_yaml` contenant le YAML édité. La génération
ne s’effectue pas silencieusement au chargement final : son contrat doit avoir été
proposé puis transmis explicitement. Les anciens clients utilisant seulement un
nom de contrat existant restent compatibles.

`GET /api/contracts/catalogue` renvoie des options `{label, value}` pour les contrats
de configuration et les contrats conservés avec les snapshots CSV. Une référence
`snapshot:{uuid}` désigne le contrat immuable d’un snapshot ; le catalogue regroupe
les contrats enregistrés identiques. `GET /api/contracts` conserve la liste des noms
des contrats de configuration pour les clients existants.

Les endpoints `GET /api/models`, `GET /api/model-versions/{id}` et `GET /api/datasets/{id}` exposent le catalogue et l’historique. `GET /api/dataset-versions/{id}/rows` expose un aperçu paginé, avec `table`, `offset` et `limit` (100 lignes maximum). `GET /api/dataset-versions/{id}/report` télécharge la carte d’identité. La documentation interactive reste disponible sous `/api/docs`.

## Monitoring optionnel

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile monitoring up -d --build --wait
```

- Grafana : http://grafana.indusense.localhost — identifiants définis par `GRAFANA_ADMIN_USER` et `GRAFANA_ADMIN_PASSWORD` (`admin` et `indusense` par défaut).
- Prometheus : http://prometheus.indusense.localhost.
- Alertmanager : http://alertmanager.indusense.localhost.

Le tableau de bord **InduSense API** est provisionné dans Grafana. Il présente la disponibilité de la collecte, le débit de requêtes, la latence et les erreurs serveur. Prometheus collecte directement `api:8000/api/metrics`. Une alerte apparaît dans Alertmanager si cette collecte échoue pendant une minute ; aucune notification externe n’est configurée.

## Python et notebooks hors Docker

```bash
uv sync --all-packages --locked
```

Sélectionner ensuite l’interpréteur `.venv/bin/python` pour le [notebook du sprint 1](notebooks/sprint1.ipynb). Le notebook fonctionne depuis la racine ou depuis son propre dossier. Les imports utilisent le paquet installé `indusense_ingestion`.

Pour un appel depuis un autre répertoire, définir `INDUSENSE_PROJECT_ROOT` ou transmettre explicitement les chemins des ressources et la racine de sortie. Le moteur SQL analyse les scripts sans exécuter leurs instructions. Voir le [guide d’ingestion](docs/ingestion-contracts.md).

## Vérifications

```bash
uv sync --all-packages --locked
uv run --all-packages --locked python -m unittest discover -s packages/ingestion/tests -v
uv run --all-packages --locked python -m unittest discover -s apps/api/tests -v
uv run --all-packages --locked python -m unittest discover -s tests -v
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile monitoring config --quiet
```

Depuis le dossier de l’interface :

```bash
pnpm install --frozen-lockfile
pnpm typecheck
pnpm build
```

Pour inclure les contrôles HTTP de la stack déjà démarrée :

```bash
INDUSENSE_TEST_URL=http://indusense.localhost uv run --all-packages --locked python -m unittest discover -s tests -v
```

Pour les tests d’ingestion, d’atomicité et de concurrence sur PostgreSQL :

```bash
INDUSENSE_POSTGRES_TESTS=1 uv run --all-packages --locked python -m unittest discover -s apps/api/tests -v
```

Cette suite crée une base temporaire `indusense_test_…`, y applique les migrations, puis la supprime en fin de test. Elle utilise la connexion PostgreSQL locale configurée par `DB_HOST`, `DB_PORT`, `DB_USER` et `DB_PASSWORD`, dont le rôle doit pouvoir créer une base. Elle ne charge aucune donnée dans la base de travail.

Le skill d’ingestion versionné dans le dépôt suit les nouveaux chemins. Si une copie personnelle du skill était installée avant cette réorganisation, elle doit être synchronisée depuis cette source avant sa prochaine utilisation.

### Préparation Silver historique

Ce parcours reste consultable pour les anciennes versions. Leurs sources,
résultats et décisions sont figés. Les nouvelles versions utilisent Bronze v2.

Dans **Modèles et datasets**, le panneau **Préparation bronze → silver** propose un
brouillon de contrat par table source. Il peut être remplacé par un fichier YAML,
modifié puis validé. Enregistrer crée une révision immuable, propre à la version du
modèle, au snapshot et à sa table ; un contrôle de révision évite les écrasements
entre deux onglets. Le catalogue de types est celui conservé avec la source bronze.

**Préparer en silver** applique la dernière révision enregistrée. Le traitement est
atomique et idempotent pour cette révision. Chaque colonne source est accompagnée
de `nom__type`, contenant son type déclaré. L’aperçu restitue leur ordre source,
même si PostgreSQL réordonne les clés des objets JSONB. Les valeurs sont stockées
dans `silver.rows.data` ; les colonnes ne deviennent pas des tables SQL générées
par upload. Les décimaux exacts sont sérialisés en chaînes ; les formats temporels
suivent le catalogue et le contrat.

La propriété `hash` est un SHA-256 de `indusense-row-v1\n` suivi du JSON UTF-8
canonique de la ligne bronze : clés triées, séparateurs `,` et `:`, sans échappement
ASCII. Les noms et valeurs originaux sont inclus ; absence de clé, NULL, chaîne et
nombre restent distincts. Les colonnes générées et corrections humaines sont
exclues. Le hash est une empreinte de traçabilité : les lignes identiques restent
présentes et partagent leur hash.

Une valeur invalide ou une valeur manquante interdite écarte **toute la ligne** dans
`silver.quarantine`. La vue **Table tampon** permet soit de corriger les cellules
et de réintégrer la ligne après revalidation du contrat de son exécution, soit de
l’écarter définitivement avec un motif. La source bronze ne change jamais. Les
corrections et rejets sont conservés lors d’une nouvelle préparation de la même
source dans cette version ; un nouveau contrat revalide les corrections.

Toute erreur en attente, y compris sur une ancienne source associée à la version,
bloque dans l’API et l’interface les statuts gold, training, challenger et champion.
Une nouvelle préparation ne peut pas masquer une table tampon non résolue. Une
fois la préparation engagée, tous les snapshots actuellement associés doivent être
traités avec leur dernière révision de contrat avant de progresser. Une nouvelle
version du modèle reprend ses propres contrats et décisions ; seules ses sources
bronze peuvent être héritées. Les traitements gold et l’entraînement restent à
implémenter.

Les routes sont regroupées sous `/api/model-versions/{id}/silver` : éditeur et
révisions sous `/contracts/{snapshot}`, validation sous
`/contracts/{snapshot}/validate`, traitement sous `/prepare/{snapshot}`, résultats
paginés sous `/runs/{run}/rows`, table tampon paginée sous `/quarantine` et décision
sous `/quarantine/{issue}/resolve`. Le paramètre `table` sélectionne la table d’un
snapshot SQL. Le fichier SQL reçu n’est jamais exécuté.

### CLI Bronze v2

La CLI partage validation, lecteurs, migrations et chargement avec l’API :

```bash
uv run indusense bronze validate --root .
uv run indusense bronze plan --root .
# Après revue du script produit et création d’une base dédiée vide :
uv run indusense bronze load --database ma_base --approved-plan-sha256 EMPREINTE --root .
```

Le catalogue défini par DB_NAME doit avoir reçu les migrations de l’API. Les
identifiants viennent des variables DB_*, jamais des scripts Alembic. Les contrats
CLI sont lus sous `config/bronze/*.yml`. Les quatre contrats de référence portent
les clés métier et unités validées : télémétrie `(machine_id, timestamp)`, incidents
`incident_id`, machines `machine_code`, maintenance `maintenance_id` ; PIECE,
LEVEL, PIECE_PER_DAY et PIECE_PER_HOUR complètent les unités physiques.
`make bronze` attend BRONZE_DATABASE et
BRONZE_APPROVED_PLAN_SHA256 ; `make bronze-plan` prépare la revue.

Les tests PostgreSQL sur les quatre sources vérifient 135 626 lignes de télémétrie,
1 245 incidents, 15 machines et 115 maintenances, soit 137 001 lignes, zéro erreur
de cast et un rejeu sans insertion supplémentaire. Les 2 937 NULL typés correspondent
exactement aux cellules absentes : 2 847 cellules CSV vides (894 températures,
995 pressions, 958 rotations) et 90 NULL SQL explicites. Le chiffre global de
894 annoncé dans le processus v2 correspond seulement aux températures ; cet
écart quantitatif est constaté sur les sources, sans modifier les règles du processus.

L’export ZIP disponible dans Nuxt contient les octets originaux, les contrats
exacts, le JSON Schema, le manifeste d’empreintes et les rapports. Il peut être
décompressé dans un dossier indépendant puis utilisé avec `--root` pour un rejeu.

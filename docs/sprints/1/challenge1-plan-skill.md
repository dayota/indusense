# Plan du challenge 1 — Skill dataset-identity

## Objectif et état

Statut : réalisé le 2026-11-20. Le [skill](../../../skills/dataset-identity/SKILL.md) est créé, validé et installé dans `~/.codex/skills/dataset-identity`. Le [bilan de validation](challenge1-skill-validation.md) détaille les tests exécutés et les limites de la revue conversationnelle.

Créer un skill `dataset-identity` permettant à un agent d’ajouter un dataset CSV au processus de cartes d’identité existant. S’appuyer sur le [guide d’ingestion](../../ingestion-contracts.md), les [contrats YAML](../../../config/contracts/), le [catalogue des types](../../../config/types.yaml) et le [module Python](../../../indusense/ingestion.py).

Le skill guide les décisions et les vérifications. Les YAML décrivent les contrats ; le module Python réalise les conversions, les statistiques et la génération des rapports.

## Périmètre de la première version

- Examiner un CSV fourni et créer ou adapter son contrat YAML.
- Réutiliser les types et convertisseurs disponibles.
- Générer sa carte d’identité et expliquer les anomalies observées.
- Conserver les sources, les rapports existants et les modifications de l’utilisateur.

Le SQL, les autres formats, la création d’un moteur d’ingestion supplémentaire et les commits ou push automatiques sont hors périmètre.

## Étape 1 — Définir les déclencheurs et les livrables

- [x] Décrire les demandes couvertes : « crée une carte d’identité pour ce CSV », « ajoute ce dataset au traitement » et « adapte ce contrat au fichier fourni ».
- [x] Distinguer une demande de génération d’une simple explication du fonctionnement.
- [x] Définir les entrées : chemin du CSV, racine du projet, contrat existant éventuel, indications métier éventuelles et destination de sortie.
- [x] Définir les livrables : contrat créé ou mis à jour, rapport Markdown, résumé des contrôles et des limites.

**Résultat attendu :** une description de skill précise, qui ne se déclenche pas pour une demande SQL ou une analyse de données sans lien avec les cartes d’identité.

## Étape 2 — Préparer une structure minimale

- [x] Créer le dossier `dataset-identity` à l’emplacement demandé lors de l’implémentation ; à défaut, utiliser `$CODEX_HOME/skills` ou `~/.codex/skills`.
- [x] Rédiger `SKILL.md` avec le frontmatter `name: dataset-identity` et une `description` indiquant sa capacité et ses déclencheurs.
- [x] Garder la sélection automatique autorisée par défaut ; permettre aussi l’appel explicite `$dataset-identity`.
- [x] Ajouter `agents/openai.yaml` si nécessaire pour les métadonnées d’interface, après consultation des instructions correspondantes de création de skills.
- [x] Ne créer des références ou scripts supplémentaires que s’ils apportent un usage concret. Ne pas recopier le moteur Python ou le guide dans le skill.

Le skill doit retrouver le projet à partir du contexte ou d’un chemin fourni, sans coder en dur un chemin propre à une machine. Si le guide ou le module requis est absent, signaler ce prérequis et demander l’emplacement utile plutôt que reconstruire le moteur.

**Résultat attendu :** un point d’entrée court, avec des liens résolus depuis la racine du projet vers les ressources existantes.

## Étape 3 — Décrire l’examen du dataset

- [x] Lire les consignes du dépôt, dont [AGENTS.md](../../../AGENTS.md), et vérifier la branche active. Sur `main` ou en HEAD détachée, appliquer l’[ADR 0001](../../ADR/0001-ne-pas-travailler-sur-main.md) avant toute écriture.
- [x] Vérifier que le fichier source existe et relever encodage, séparateur, dimensions, noms des colonnes et exemples représentatifs.
- [x] Utiliser la [lecture CSV existante](../../../indusense/ingestion.py) ; préserver les chaînes, les identifiants avec zéros initiaux et les sources.
- [x] Distinguer ce qui a été observé sur un échantillon de ce qui a été vérifié sur l’ensemble du fichier.
- [x] Identifier les ambiguïtés utiles à résoudre : dates comme `01/02/2026`, codes numériques, unités ou nombres utilisant une virgule décimale.

**Résultat attendu :** des faits observables permettant de préparer le contrat et une liste limitée d’ambiguïtés, sans règles métier inventées.

## Étape 4 — Construire le contrat YAML

- [x] Rechercher un contrat existant et préserver ses contraintes explicites.
- [x] Choisir les types dans le catalogue et déclarer les colonnes avec les bons noms et la bonne casse.
- [x] Définir les options pertinentes : `format`, `pattern`, `required`, `nullable`, `allowed`, bornes numériques et politique `extra_columns`.
- [x] Distinguer une proposition structurelle d’une contrainte métier : une colonne sans valeur vide ne prouve pas qu’elle est non nullable ; une plage observée ne définit pas une plage autorisée.
- [x] Appliquer les priorités du moteur : colonne explicite, première règle de nom correspondante, puis inférence ou refus des colonnes supplémentaires.
- [x] Ne demander une précision que si elle change le résultat ; poursuivre les vérifications indépendantes en attendant.
- [x] Valider le contrat avec le [chargeur existant](../../../indusense/contracts.py) avant la génération du rapport.

**Résultat attendu :** un contrat accepté par le moteur, avec des hypothèses clairement signalées et aucune contrainte métier déduite arbitrairement.

## Étape 5 — Réutiliser ou étendre les types

- [x] Réutiliser les convertisseurs du registre : `string`, `integer`, `number` et `datetime`.
- [x] Préférer une option de colonne à un nouveau type lorsqu’elle suffit, par exemple un format de date différent.
- [x] Pour un type supplémentaire partageant un convertisseur existant, ajouter une définition au catalogue seulement si le besoin le justifie.
- [x] Si une nouvelle fonction de conversion est nécessaire, expliciter cette extension du moteur et la valider par un cas ciblé avant de l’utiliser.
- [x] Préserver le chargement YAML sécurisé et le registre explicite : aucun code Python ni import arbitraire ne doit être exécuté depuis le YAML.

**Résultat attendu :** une extension minimale et vérifiée, sans duplication des conversions dans le skill.

## Étape 6 — Générer et vérifier la carte d’identité

- [x] Utiliser l’environnement du projet et ses dépendances verrouillées.
- [x] Appeler `generate_identity` avec des chemins explicites vers la source, le contrat et, si nécessaire, le catalogue et la racine de sortie.
- [x] Vérifier les dimensions, les types, les statistiques et les observations du rapport.
- [x] Vérifier la préservation des identifiants, l’exclusion des valeurs invalides et l’affichage de `N/A` lorsque nécessaire.
- [x] Préserver les rapports horodatés existants ; en cas de collision de nom, ne pas écraser le rapport et relancer avec un nouvel horodatage.
- [x] Adapter le notebook uniquement si la demande inclut le lancement de ce dataset depuis le notebook.
- [x] Restituer les liens vers les livrables et les contrôles réalisés. Ne committer ou pousser que si la demande l’autorise.

**Résultat attendu :** un rapport reproductible et un bilan fidèle des anomalies, sans modification des données sources.

## Étape 7 — Valider le skill sur des demandes réalistes

- [x] Exécuter le validateur `quick_validate.py` de la compétence de création de skills pour contrôler la structure, le frontmatter et les éventuels placeholders.
- [x] Vérifier les liens, la portée de la description et la cohérence entre le skill et le guide d’ingestion.
- [x] Rejouer un dataset existant et vérifier que les types et statistiques restent inchangés.
- [x] Essayer un nouveau CSV avec séparateur point-virgule, identifiants à zéros initiaux et dates au format français.
- [x] Essayer un cas comportant des valeurs invalides et un contrat inconnu ou incorrect : les anomalies doivent être signalées, les erreurs de configuration doivent empêcher la génération.
- [x] Revoir le scénario d’une demande avec date ambiguë : les consignes imposent de demander le format utile sans inventer une convention. La qualité de cette interaction reste à confirmer en usage réel.
- [x] Vérifier le comportement sur `main` dans un dépôt temporaire : aucune écriture avant le choix explicite d’une branche.
- [x] Vérifier qu’une demande portant sur du SQL expose la limite actuelle sans prétendre produire une carte CSV adaptée.
- [x] Produire les livrables de ces essais dans des répertoires temporaires et lancer les [tests d’ingestion existants](../../../tests/test_ingestion.py) si le moteur ou ses configurations ont changé.

**Résultat attendu :** une validation de la structure et du comportement réel, au-delà du seul contenu textuel des instructions.

## Critères de fin

- Le skill est disponible à l’emplacement retenu et possède une description ciblée.
- Un agent peut traiter un nouveau CSV avec le moteur existant à partir du skill et du contexte projet.
- Les contrats, le catalogue et les convertisseurs conservent leurs responsabilités distinctes.
- Les ambiguïtés et contraintes métier non établies sont explicites.
- Les sources, les rapports historiques et la règle de branche sont préservés.
- Les essais sont concluants et le guide d’ingestion mentionne le skill et son invocation.

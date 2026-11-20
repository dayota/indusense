# ADR 0001 — Ne jamais travailler directement sur main

- Statut : accepté
- Date : 2026-11-20

## Contexte

La branche `main` doit rester une branche d’intégration. Les modifications doivent être préparées sur une branche de travail afin de permettre leur revue avant intégration.

## Décision

Il est interdit de travailler directement sur la branche `main`, y compris pour modifier de la documentation, des notebooks ou la configuration du projet.

Au début de chaque tâche et avant toute modification ou tout commit, vérifier la branche active avec `git branch --show-current`.

Si la branche active est `main` :

1. Suspendre toute opération susceptible de modifier les fichiers du dépôt ou de créer un commit.
2. Demander systématiquement à l’utilisateur de créer une branche de travail ou de sélectionner une branche existante.
3. Attendre son choix explicite ; ne pas choisir, créer ou changer de branche automatiquement.
4. Vérifier que la branche choisie est active et différente de `main` avant de reprendre le travail.

La consultation en lecture seule nécessaire à cette vérification reste autorisée. Si des modifications existent déjà sur `main`, les préserver et les signaler à l’utilisateur sans les supprimer, les remiser ou les déplacer automatiquement.

Si aucune branche n’est active (HEAD détachée), demander également à l’utilisateur de créer ou sélectionner une branche avant de modifier le dépôt.

Les changements sont ensuite intégrés à `main` par une pull request et une fusion selon le processus du projet. Aucun commit de travail ni push direct sur `main` n’est autorisé.

## Conséquences

- Chaque tâche nécessitant des modifications utilise une branche de travail.
- Le travail est suspendu sur `main` jusqu’au choix explicite d’une branche par l’utilisateur.
- Les agents appliquent cette règle via les consignes du dépôt dans [AGENTS.md](../../AGENTS.md).
- Cette décision constitue une règle de travail ; elle ne configure pas de protection technique de branche sur l’hébergeur Git.

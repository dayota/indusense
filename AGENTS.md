# Consignes pour les agents

## Branche de travail obligatoire

Appliquer l’[ADR 0001](docs/ADR/0001-ne-pas-travailler-sur-main.md).

- Vérifier la branche active au début de chaque tâche et avant toute modification ou tout commit avec `git branch --show-current`.
- Ne jamais modifier les fichiers du dépôt, créer un commit ou effectuer un push direct sur `main`.
- Si `main` est active, suspendre les opérations d’écriture et demander systématiquement à l’utilisateur de créer ou sélectionner une branche de travail. Attendre son choix explicite avant de créer ou changer de branche et de reprendre le travail.
- Si HEAD est détachée, demander également une branche de travail avant toute modification.
- Préserver les modifications existantes ; ne pas les supprimer, les remiser ou les déplacer automatiquement pour changer de branche.

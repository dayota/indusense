# Validation du skill dataset-identity

Date : 2026-11-20. Branche de réalisation : `sprint1/challenge1`.

Ce bilan décrit la version initiale limitée aux CSV. L’[extension SQL du challenge 2](challenge2-skill-validation.md) documente le périmètre et les tests actuels.

## Livrables

- [Instructions du skill](../../../skills/dataset-identity/SKILL.md).
- [Métadonnées d’interface](../../../skills/dataset-identity/agents/openai.yaml), avec sélection automatique autorisée par défaut.
- [Lanceur](../../../skills/dataset-identity/scripts/run_identity.py), qui appelle le moteur existant et contrôle la branche avant tout import métier.
- [Tests du lanceur](../../../tests/test_dataset_identity_skill.py).
- [Guide et invocation](../../ingestion-contracts.md).

La source est versionnée dans le dépôt. Une copie a été installée dans `~/.codex/skills/dataset-identity` ; les modifications futures de la source doivent être reportées dans cette installation. Le moteur et ses configurations existantes n’ont pas été modifiés pour créer le skill.

## Vérifications exécutées

Le validateur `quick_validate.py` de la compétence de création de skills accepte la source du skill. La suite `python -B -m unittest discover -s tests -v`, exécutée avec l’interpréteur du projet, réussit : **16 tests**, dont 6 spécifiques au lanceur et 10 tests d’ingestion existants.

| Cas exécuté | Résultat observé |
|---|---|
| CSV incidents existant | 1 245 lignes, 18 colonnes ; tableaux et observations identiques au rapport historique |
| Nouveau CSV à séparateur point-virgule | 2 lignes, 3 colonnes ; dates françaises correctement rendues et colonne code traitée comme identifiant |
| Valeur numérique invalide | Anomalie signalée ; valeur exclue des statistiques ; source inchangée |
| Type inconnu dans le contrat | Échec explicite avant création d’un rapport |
| Branche `main` dans un dépôt temporaire | Refus avec demande de choix explicite d’une branche ; empreintes de tous les fichiers identiques avant et après |
| HEAD détachée dans un dépôt temporaire | Même refus et absence d’écriture, y compris de cache Python |
| Script SQL | Refus de format explicite ; aucun fichier modifié |
| Autres scénarios d’ingestion existants | Préservation des zéros initiaux, contrats invalides, types personnalisés, collision de sortie et lancement du notebook : tests réussis |

Les tests du lanceur partent d’un sous-dossier, utilisent un projet temporaire et créent leurs rapports hors du dépôt de travail. Ils vérifient le comportement exécutable ; ils ne se limitent pas à comparer le texte des instructions.

## Revue des décisions conversationnelles

Les scénarios suivants ont été examinés lors de la rédaction du skill ; ils ne constituent pas une évaluation indépendante d’un agent en situation réelle.

- **Demande de carte d’identité CSV** : la description couvre la création du contrat et du rapport ; les ressources du projet sont résolues depuis sa racine.
- **Date `01/02/2026` sans convention connue** : les consignes imposent de demander le format utile et d’attendre la réponse avant la conversion dépendante. Les inspections indépendantes peuvent continuer.
- **Plage de valeurs ou absence de cellules vides** : les consignes interdisent d’en déduire une borne métier ou une obligation de non-nullité.
- **Simple question sur le fonctionnement ou demande SQL** : la description les exclut du déclenchement prévu ; si explicitement invoqué sur du SQL, le skill explique sa limite.
- **Création du contrat sur `main`** : l’agent doit appliquer les consignes de branche avant cette écriture. Le lanceur bloque lui-même la génération, mais ne peut pas empêcher une écriture réalisée par un autre outil.

## Limites et entretien

La qualité des questions et la sélection automatique devront être confirmées lors des usages réels. Le skill ne fournit ni moteur SQL ni contrôle technique universel des écritures du dépôt. Les instructions d’agent et le contrôle du lanceur ont des portées complémentaires.

Pour une évolution : modifier la source versionnée, relancer le validateur et les tests pertinents, puis synchroniser explicitement la copie installée. Ne pas remplacer silencieusement une installation contenant des modifications locales.

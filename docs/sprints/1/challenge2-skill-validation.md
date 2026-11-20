# Extension SQL du skill dataset-identity

Date : 2026-11-20. Branche : `sprint1/challenge2`.

## Changement réalisé

Le [skill](../../../skills/dataset-identity/SKILL.md) couvre désormais les CSV et les scripts PostgreSQL. Le [lanceur](../../../skills/dataset-identity/scripts/run_identity.py) sélectionne le moteur selon l’extension `.csv` ou `.sql`, sans distinction de casse, et conserve le contrôle de branche avant tout traitement. Il ne duplique pas le parsing, les conversions ou les statistiques du moteur.

Le parcours CSV conserve son contrat YAML obligatoire. Le parcours SQL refuse `--contract` : il utilise directement le schéma CREATE TABLE, comme le [module du challenge 2](../../../scripts/sql_ingestion.py). Les options de catalogue, de nom et de destination de sortie sont communes. Le JSON de sortie conserve les dimensions CSV et fournit les dimensions par table et l’inventaire des instructions pour le SQL.

Les [consignes PostgreSQL](../../../skills/dataset-identity/references/sql.md) sont chargées seulement pour ce parcours. Elles précisent l’analyse sans exécution, les NULL, les omissions, les expressions non évaluées, les décimaux, les fuseaux et les limites du moteur. Les [métadonnées d’interface](../../../skills/dataset-identity/agents/openai.yaml) et le [guide](../../ingestion-contracts.md) ont été adaptés ; la sélection automatique reste autorisée par défaut.

## Vérifications exécutées

Le validateur de skills accepte la source et la copie installée. La suite `python -B -m unittest discover -s tests -v`, avec l’interpréteur du projet, réussit : **29 tests**, dont 10 essais du lanceur, 9 tests SQL et 10 tests du traitement CSV et du notebook.

Les [essais du lanceur](../../../tests/test_dataset_identity_skill.py) vérifient notamment :

| Scénario | Résultat |
|---|---|
| CSV incidents et nouveau CSV | Comportement et résultats existants préservés |
| Script SQL de référence | 15 machines, 115 maintenances, 11 colonnes chacune et 10 instructions |
| Rapport SQL | Corps identique au rapport de référence produit par le module |
| CSV sans contrat / SQL avec contrat | Refus explicite, sans écriture |
| SQL mal formé ou instruction UPDATE | Échec explicite sans traceback ni rapport partiel |
| Extension `.SQL`, types et destination personnalisés | Prise en charge ; sortie placée au bon endroit |
| Décimaux et colonnes omises | Moyenne exacte 0,15 pour 0,1 et 0,2 ; omissions signalées |
| `main` et HEAD détachée | Les deux formats sont bloqués ; tous les fichiers restent identiques |
| Autre format | Refus explicite sans écriture |

Les essais utilisent des dépôts et des sorties temporaires. Le script SQL de référence reste intact et aucune instruction SQL n’est exécutée.

## Installation et usage

La copie dans `~/.codex/skills/dataset-identity` a été synchronisée après vérification de son identité avec la version antérieure du dépôt. Une comparaison confirme qu’elle est identique à la nouvelle source versionnée. Son lanceur installé a également été exécuté sur le script réel, avec sortie temporaire : les dimensions attendues sont confirmées.

```text
$dataset-identity Crée une carte d’identité pour datas/machine.sql sans exécuter le SQL.
```

La description et les décisions conversationnelles ont été revues, sans évaluation indépendante d’un agent. La sélection automatique du skill et les questions de clarification restent à observer en usage réel. Le périmètre SQL demeure celui du module existant ; cette évolution n’ajoute aucun dialecte ni aucune nouvelle instruction SQL.

# RGPD et projet IA Indusense : les 7 principes, côté ML engineer

> **Objectif pédagogique.** Savoir reconnaître les données personnelles dans une chaîne de maintenance prédictive et transformer chacun des sept principes de l'article 5 du RGPD en décisions techniques vérifiables.

## Point de départ

Dans Indusense, une mesure de température ou de vibration liée uniquement à une machine n'identifie pas nécessairement une personne. En revanche, un `reviewer_id`, un commentaire, une adresse IP, ou des horaires de machine recoupés avec les plannings peuvent identifier indirectement un salarié. Un identifiant remplacé par un pseudonyme **reste une donnée personnelle** si le lien avec la personne peut être rétabli. Le RGPD s'applique alors aux traitements concernés, y compris aux copies dans les exports, logs et jeux d'entraînement.

**Répartition des rôles.** L'organisation qui décide *pourquoi* et *comment* traiter les données est généralement le **responsable du traitement** ; un prestataire agissant pour son compte peut être **sous-traitant**. Le ML engineer conçoit et applique les garanties techniques, signale les risques et fournit des preuves. Il ne décide pas seul de la base légale, de l'information des salariés, des durées officielles ou de la nécessité d'une analyse d'impact relative à la protection des données (**AIPD**). Ces décisions se prennent avec le responsable du traitement, le délégué à la protection des données (**DPO**) s'il existe, les métiers et la sécurité.

## 1. Licéité, loyauté et transparence

**Principe.** Les personnes doivent comprendre l'usage de leurs données ; cet usage doit avoir une base légale et ne pas les surprendre. Le consentement est une possibilité parmi celles de l'article 6, pas le point de départ obligatoire.

**Dans Indusense.** Le responsable du traitement définit la base légale et informe les salariés concernés si leurs interventions, identifiants ou commentaires sont enregistrés pour qualifier les alertes. Il explicite que le modèle vise la **maintenance des machines** et la validation humaine des pannes, ainsi que les éventuelles utilisations pour l'entraînement et le suivi. Le projet ne doit pas laisser croire que ces données servent seulement à réparer une machine si elles servent aussi à analyser la conduite individuelle des opérateurs.

**Action du ML engineer.** Cartographier les champs personnels et leurs flux (API → base → interface Streamlit → export → Prefect → entraînement → MLflow et suivi). Décrire à quoi sert chaque champ et qui y accède ; signaler tout usage non prévu au responsable du traitement. Concevoir des écrans et des notices cohérents avec le fonctionnement effectif, sans se substituer à la validation juridique de l'information.

**Preuve attendue.** Inventaire des données et schéma de flux, finalités et base légale validées par le responsable, version de la notice d'information alignée sur le produit.

## 2. Limitation des finalités

**Principe.** Les données sont collectées pour des objectifs déterminés, explicites et légitimes ; leur réutilisation doit rester compatible avec ces objectifs ou être encadrée séparément.

**Dans Indusense.** Une télémétrie et un retour terrain collectés pour **prévoir et confirmer des pannes** peuvent alimenter un réentraînement prévu et documenté. Les détourner vers le **classement individuel des techniciens** constituerait une autre finalité à examiner ; le seul fait que les données soient disponibles ne l'autorise pas.

**Action du ML engineer.** Associer chaque table, export et pipeline à sa finalité autorisée ; empêcher qu'un nouveau tableau de bord, une expérience ou un partage récupère des données identifiantes hors de ce cadre. Demander une revue avant de créer une nouvelle feature fondée sur l'identité ou l'activité d'un salarié.

**Preuve attendue.** Fiche de finalité par jeu de données, permissions des consommateurs et revue documentée de toute réutilisation.

## 3. Minimisation des données

**Principe.** Ne traiter que les données adéquates, pertinentes et nécessaires à l'objectif.

**Dans Indusense.** Les features de démonstration sont `temperature`, `vibration` et `pressure`, avec un code machine et une date. Le nom, le badge ou la performance individuelle du technicien ne sont pas nécessaires pour prédire une panne. Un commentaire libre peut révéler des informations personnelles imprévues ; il faut le limiter et privilégier des choix structurés comme « capteur défaillant » ou « panne confirmée ».

**Action du ML engineer.** Justifier chaque feature et retirer les colonnes personnelles inutiles *avant* l'export ou l'entraînement. Limiter les champs libres et les réponses API, séparer les identifiants de validation métier des features du modèle, éviter les identifiants individuels dans les métriques et les logs. Pseudonymiser si une liaison est indispensable ; tester le risque de réidentification par machine, date et planning.

**Preuve attendue.** Dictionnaire des features avec justification, schéma d'export limité aux colonnes approuvées et test d'absence de champs interdits.

## 4. Exactitude

**Principe.** Les données personnelles doivent être exactes et rectifiées ou effacées sans tarder lorsqu'elles sont inexactes au regard de leur finalité. Pour l'IA, la qualité des données métier est aussi une condition pratique pour ne pas entraîner sur des faits faux.

**Dans Indusense.** Une déclaration d'incident n'est pas nécessairement une panne confirmée. Le sprint relève des incohérences entre machines et incidents ; un retour `pending` ne doit donc pas devenir automatiquement un label. Les heures de mesure, de prédiction, de panne, de déclaration et de validation doivent rester distinctes.

**Action du ML engineer.** Valider les unités, les plages, les horodatages et les jointures ; mettre les cas contradictoires en quarantaine ; ne constituer le jeu « gold » qu'avec des retours vérifiés et mûrs. Permettre une **correction historisée** d'un feedback et propager les rectifications aux exports et entraînements suivants selon une procédure définie avec le responsable.

**Preuve attendue.** Contrôles de qualité exécutés, liste des cas exclus, provenance des labels et historique des corrections.

## 5. Limitation de la conservation

**Principe.** Une donnée personnelle identifiable n'est conservée que pendant la durée nécessaire à sa finalité ; une durée prolongée doit avoir sa justification et ses garanties.

**Dans Indusense.** Distinguer télémétrie brute, prédictions, retours et commentaires, logs techniques, exports Parquet/CSV, snapshots d'entraînement, sauvegardes et artefacts de suivi. La traçabilité d'un modèle ne justifie pas de garder indéfiniment les identités et commentaires bruts. Aucune durée universelle (« 30 jours » ou « 5 ans ») ne peut être déduite du schéma technique seul.

**Action du ML engineer.** Faire valider une durée **par catégorie et finalité**, avec point de départ, sort à échéance et exceptions justifiées. Implémenter purge ou anonymisation effective, y compris pour exports, sauvegardes et environnements de test, et en vérifier l'exécution. Documenter quelles références de provenance restent nécessaires après purge ; prévoir comment instruire une demande de rectification ou d'effacement portant sur les données utilisées pour entraîner un modèle.

**Preuve attendue.** Tableau de conservation approuvé, tâches de purge testées et traces de leur exécution. Les empreintes de datasets et les versions du code peuvent aider à la traçabilité sans conserver chaque donnée brute identifiable.

## 6. Intégrité et confidentialité

**Principe.** Protéger les données contre les accès ou usages non autorisés, la perte, la destruction et l'altération accidentelle à l'aide de mesures adaptées au risque.

**Dans Indusense.** Les retours terrain peuvent contenir des commentaires personnels et les snapshots peuvent être copiés hors de la base. La maquette locale utilise deux clés de rôle partagées et SQLite : elle sert à apprendre le parcours, **pas à établir la sécurité d'une production**.

**Action du ML engineer.** Avec les équipes d'infrastructure : contrôler les accès selon les rôles, utiliser en exploitation une identité nominative, chiffrer les échanges et les stockages selon le risque, garder les secrets hors des dépôts, protéger les sauvegardes et journaux, limiter les droits de Prefect/MLflow, tester la restauration et détecter les accès anormaux. Ne jamais écrire de badge, nom, commentaire brut ou token dans un log technique ; traiter aussi les risques de copie ou d'extraction depuis les artefacts de modèle.

**Preuve attendue.** Matrice d'habilitation, configuration de sécurité revue, tests d'accès, procédures d'incident et de restauration.

## 7. Responsabilité : pouvoir démontrer les six premiers points

**Principe.** Le responsable du traitement doit respecter les principes précédents **et pouvoir en apporter la preuve**. La responsabilité juridique de l'organisation ne disparaît pas parce qu'une équipe ML a construit le modèle.

**Dans Indusense.** Pour chaque prédiction et chaque version de modèle, retrouver les données autorisées, le schéma de features, les validations métier, le jeu de données, le code, les résultats de tests et la décision de mise en production. Une expérience MLflow ou un journal technique ne constitue pas à lui seul un dossier RGPD.

**Action du ML engineer.** Produire une fiche de dataset et une fiche de modèle ; conserver les versions, empreintes et résultats des contrôles ; documenter les écarts et les corrections ; participer à l'évaluation des risques et à l'AIPD **si elle est requise**. Faire valider par les bons responsables les choix de finalité, de base légale, de conservation et d'accès. Prévoir des procédures pour localiser les données liées à une personne et traiter les demandes que le responsable du traitement reçoit.

**Preuve attendue.** Registre et décisions tenus par l'organisation, fiches de données/modèle, rapports de tests, historique d'accès et de purge, comptes rendus des revues et, le cas échéant, AIPD.

## Ce que je vérifie avant de livrer un pipeline Indusense

| Question à poser | Ce que je fournis en tant que ML engineer | Décision à faire valider |
| --- | --- | --- |
| Quelles données peuvent désigner un salarié ? | Inventaire des champs, recoupements possibles et flux | Qualification des traitements et information des personnes |
| Pourquoi chaque champ est-il traité ? | Justification des features, des logs et des usages | Finalités et base légale |
| Qui peut accéder à quoi et combien de temps ? | Droits techniques, tests, politique de purge proposée | Habilitations et durées de conservation |
| Les labels et modèles sont-ils fiables ? | Contrôles, exclusions, provenance et historique des corrections | Critères métier de validation et de mise en production |
| Peut-on prouver ce qui a été fait ? | Manifeste, rapports de tests, versions et traces utiles | Dossier de conformité et arbitrage des risques |

**Mise en situation (5 minutes).** Un technicien écrit dans Streamlit : « Jean était absent lors de la panne de MACH-01 ». Le pipeline exporte ensuite tous les commentaires vers le jeu d'entraînement. Identifiez au moins trois problèmes et proposez trois modifications. *Réponse attendue :* la phrase identifie une personne, sa présence n'est pas nécessaire à la prédiction de panne, et la copie multiplie les données à protéger ; remplacer le texte par un fait machine structuré, exclure les commentaires des features et exports, et cadrer l'accès/la conservation du commentaire éventuellement nécessaire au suivi métier.

## Sources et portée

- [Règlement (UE) 2016/679, articles 5, 6, 13, 24, 25, 32 et 35 (EUR-Lex)](https://eur-lex.europa.eu/eli/reg/2016/679/oj/fra).
- [CNIL — Chapitre II du RGPD : principes](https://www.cnil.fr/fr/reglement-europeen-protection-donnees/chapitre2).
- [CNIL — Identifier les données personnelles et distinguer pseudonymisation/anonymisation](https://www.cnil.fr/fr/identifier-les-donnees-personnelles).
- [CNIL — Rôle du responsable du traitement et du sous-traitant](https://www.cnil.fr/fr/rgpd-comment-bien-identifier-son-role).
- [CNIL — Collecte et gestion des données dans un système d'IA](https://www.cnil.fr/fr/tenir-compte-de-la-protection-des-donnees-dans-la-collecte-et-la-gestion-des-donnees).
- [CNIL — Quand une AIPD est requise](https://www.cnil.fr/fr/listes-des-traitements-pour-lesquels-une-aipd-est-requise-ou-non).

Les exemples Indusense sont des **applications pédagogiques** des principes à la feuille de route et à la maquette locale du Sprint 4. Ils ne constatent pas la conformité du système déployé ; celle-ci dépend des traitements, accès et décisions effectivement mis en place.

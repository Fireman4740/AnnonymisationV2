# Métriques du banc actif — noyau réduit

Révision du 15 octobre 2026, à la demande de l'utilisateur : conserver moins
de mesures, avec des définitions vérifiables et des contrôles explicites.
Cette révision remplace le catalogue exécutable de SPEC-07. Les scorecards
ont désormais le schéma **3.1** et la politique **reliable-conditional-v2**.
Le noyau décrit ici est complété par les [évaluations conditionnelles](metrics-research.md) :
utilité sur une tâche, QICR, MALE-k et Brier/ECE sur événements observés.

## Mesures conservées

| Mesure | Source et contrôle | Limite de lecture |
|---|---|---|
| Précision, rappel, F1 de spans | Comptes micro `partial` du paquet nervaluate épinglé ; offsets convertis explicitement ; bootstrap par document | Localisation avec demi-crédit au chevauchement ; ce n'est pas un score de confidentialité |
| F1 strict | Même référence ; bornes et catégorie exactes | Mesure de détection sur le gold annoté |
| Fuite gold et fuite directe | Présence littérale normalisée des valeurs gold testables ; dénominateurs et comptes conservés | Ne mesure pas l'inférence contextuelle ni les attributs absents du gold |
| Couverture des masques | Caractères gold effectivement recouverts par les décisions appliquées ; KEEP exclu | Une reformulation peut protéger sans recouvrir exactement le gold |
| Rappel TAB officiel | Évaluateur TAB original, sources et version contrôlées ; détails natifs conservés | Propre au corpus TAB et à ses annotations |
| R_succ RAT-Bench | Attaques figées et vérifiées ; scorer comparé au code officiel ; erreurs et paramètres d'attaquant conservés | Résultat face à l'attaquant choisi, avec estimation CorrectMatch stochastique et limite d'échantillon |
| CPR/IPR SPIA | Attaques d'inférence figées, gold et paramètres vérifiés ; formules originales et bootstrap par document | Attaquant choisi et arbitrage `rule_model` ; aucune garantie générale de confidentialité |

Ces familles représentent **11 clés métriques de base au maximum**, selon le corpus,
les annotations disponibles et les capacités déclarées du système. Les mesures
d'attaque restent diagnostiques dans la campagne échantillonnée ; les conserver
ne les transforme pas en certification de confidentialité.

Les comptes TP/FP/FN, les ventilations par catégorie/langue/domaine/expression,
les latences et les taux d'erreur restent des informations d'audit. Ils ne
forment pas un score synthétique supplémentaire.

## Mesures retirées du parcours actif

Le tableau retrace le retrait initial. Six nouvelles clés conditionnelles
peuvent désormais compléter le noyau (rétention, delta F1, QICR, MALE-k, Brier,
ECE), avec des définitions et prérequis révisés. Elles ne réactivent pas les
anciens protocoles ci-dessous et restent absentes si les références manquent.

| Retrait | Motif dans ce projet |
|---|---|
| Mean Utility et commande `judge` | Le contrôle du texte vide reçoit encore une utilité moyenne de 0,517 sur SPIA dans la campagne Ling 3.0 ; le juge n'est pas validé pour classer l'utilité |
| ROUGE-L comme métrique d'utilité | Recouvrement lexical ; aucune validation indépendante ici comme mesure de conservation du sens |
| Utility Retention TF-IDF et variantes train auxiliaires | Classifieur de substitution non validé comme tâche d'utilité de référence ; pas de ratio publié par défaut |
| TRIR lexical | Proximité au texte original utilisée comme substitut de ré-identification ; retrait de ce proxy |
| QICR/RCR@k, MALE-k, ECE, Brier | Pas de gold indépendant à k réel disponible dans les corpus du banc ; pas de métriques de calibration publiables ici |
| CPR/IPR littéraux | Redondants avec la présence de surfaces ; évite la confusion avec les attaques SPIA |
| Précision token pondérée par longueur | Pondération de substitution non validée |
| ER_di/ER_qi et alias, F1 de classification redondant, macro-F1, détails des quatre schémas en tant que métrique | Catalogue simplifié : P/R/F1 micro, F1 strict, comptes et ventilations conservés ; le rappel TAB officiel reste distinct |

Les utilitaires historiques ne sont plus importés par le scorer actif ni
exportés depuis l'API `anonymisation.metrics`. Certains modules restent présents
pour relire les anciens résultats et pour les statistiques internes des moteurs
de risque. Ils ne réactivent aucune métrique de scorecard.

## Contrôles qui restent obligatoires

- `score` ne fait aucun appel LLM, aucune prédiction et aucun entraînement.
- Les empreintes du gold, des prédictions et des attaques utilisées sont vérifiées.
- Les erreurs de modèle restent des erreurs, jamais des prédictions vides.
- Un taux d'erreur de prédiction ou d'attaque supérieur à 5 % bloque la publication.
- Les comparaisons n'utilisent pas les scores des runs bloqués pour classer les systèmes.
- Des schémas, golds ou paramètres d'attaquant différents ne sont pas comparés comme identiques.
- Une métrique retenue mais non applicable est omise du bloc de valeurs ; la raison est conservée dans `not_applicable`. Une attaque en échec reste signalée avec son statut et son blocage.
- Détecteur muet avec gold non vide : rappel et F1 à zéro. Jeu explicitement annoté négatif avec de fausses prédictions : F1 zéro. Un corpus sans annotation de spans n'est pas assimilé à des exemples négatifs : ses métriques de détection sont absentes, avec leur raison.
- Les intervalles bootstrap, leur unité, le nombre de tirages et la graine restent attachés aux valeurs.
- Les empreintes du code de scoring sont séparées du commit du modèle ayant produit les prédictions.

Retirer le juge change le périmètre de publication : un ancien blocage causé
uniquement par le juge n'existe plus dans une nouvelle scorecard 3.0. Cela ne
corrige pas rétroactivement la réponse du juge ; l'ancien résultat reste conservé.

## Conséquences pratiques

La CLI expose `predict`, `attack`, `evaluate`, `score` et `compare` ; `judge` et
`score --train-run` sont retirés. Les futures campagnes ne prédisent plus de
split train auxiliaire et ne facturent plus de juge d'utilité.
Une campagne qui configure explicitement `conditional_evaluations` peut ingérer
un train auxiliaire pour entraîner l'évaluateur de tâche local ; il n'est pas anonymisé.

Les corpus ne disposant que de labels de tâche aval, sans annotations de spans
ni attaque applicable, n'ont plus de score de qualité dans ce noyau. Le banc
le déclare au lieu d'inventer une mesure d'utilité. Les contrôles d'exécution
et les temps de traitement restent disponibles.

La campagne active conserve donc sept corpus évaluables par ce noyau :
RAT-Bench, QUASIFR, TAB, CoNLL2003, DBBIO, SPIA et OpenPII. PersonalReddit,
SupportTickets et BitextSupport sont déclarés dans `excluded_datasets` avec
leur motif ; leurs adaptateurs, sources et résultats historiques sont conservés.
Une scorecard sans aucune mesure de qualité applicable est bloquée, même si
son exécution est techniquement sans erreur.
Les corpus de tâche peuvent revenir dans une campagne configurée explicitement,
à condition de fournir train/test et un évaluateur informatif ; leur exclusion
dans la configuration courante ne constitue pas une incompatibilité du scorer.

Les anciennes campagnes et leurs scorecards 2.0 restent immuables. Une nouvelle
version peut être recalculée hors ligne à partir des sorties figées, avec sa
provenance et un répertoire distinct. Aucune campagne modèle n'est nécessaire
pour appliquer ce retrait.

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

## Périmètre du gold de détection (révision du 28 octobre 2026)

- Chaque manifeste déclare `evaluation.gold_scope` (`exhaustive`, `reason`) ;
  sans déclaration, `score` échoue. Aucune exhaustivité n'est supposée.
- Gold non exhaustif (CoNLL2003, DB-bio, RAT-Bench, SPIA, OpenPII, PANORAMA,
  SynthPAI, PersonalReddit) : une détection absente du gold n'est pas une
  fausse détection. Précision, F1 et F1 strict sont dans `not_applicable` ;
  seul le rappel est publié. Les protections de ces corpus se lisent sur
  leurs attaques originales (R_succ, CPR/IPR) et sur l'évaluateur TAB.
- Gold `IGNORED` (catégorie hors périmètre, action KEEP — MISC de CoNLL) :
  retiré du gold de détection, de la couverture et des fuites ; une
  prédiction qui le recouvre est neutre, comme une mention sans besoin de
  masquage dans TAB. Les comptes `out_of_scope_gold` et `neutral_predictions`
  restent publiés.
- `compare` refuse deux scorecards dont les documents scorés diffèrent
  (`accounting.scored_doc_ids_sha256`) : des erreurs de prédiction
  différentes changent le dénominateur.

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

Le noyau de base couvre sept corpus : RAT-Bench, QUASIFR, TAB, CoNLL2003,
DBBIO, SPIA et OpenPII. La campagne de dix documents ajoute SupportTickets et
BitextSupport avec une tâche aval explicite et un train auxiliaire de 2000
documents disjoints du test. PersonalReddit reste dans `excluded_datasets` :
ses attributs personnels ne sont pas une tâche d'utilité validée et aucune
attaque adaptée n'est configurée. Les sources et résultats historiques sont conservés.
Une scorecard sans aucune mesure de qualité applicable est bloquée, même si
son exécution est techniquement sans erreur.
Les mesures de tâche restent indisponibles si l'évaluateur ne dépasse pas
la référence majoritaire, même sur un corpus activé dans la campagne.

Les anciennes campagnes et leurs scorecards 2.0 restent immuables. Une nouvelle
version peut être recalculée hors ligne à partir des sorties figées, avec sa
provenance et un répertoire distinct. Aucune campagne modèle n'est nécessaire
pour appliquer ce retrait.

## Compréhension et pertinence : évaluation humaine conditionnelle

À la demande de l'utilisateur, trois nouvelles mesures **diagnostiques** peuvent
être ajoutées à partir de notes humaines figées : `human_readability` (texte
compréhensible), `human_relevance` (informations nécessaires à la tâche
conservées), et `human_faithfulness` (pas de déformation factuelle). Chacune est
notée séparément 0 = échec, 1 = partiel, 2 = préservé, puis normalisée sur
[0,1]. Le score est la moyenne par document des notes de ses évaluateurs,
puis la moyenne des documents ; l'IC 95 % bootstrap rééchantillonne les
documents. L'accord exact entre évaluateurs est fourni en détail.

Au moins deux évaluateurs distincts sont requis pour **chaque** document réussi,
avant toute agrégation. L'évaluation de lisibilité se fait sur le texte
anonymisé seul ; la pertinence et la fidélité utilisent le texte original et,
si disponible, la tâche déclarée, sans pénaliser le retrait d'un détail privé
non nécessaire. Une revue aveugle au système, des contrôles texte intact / texte
vide et un échantillon indépendant sont recommandés mais ne sont pas vérifiés
par le programme. Les scores ne démontrent ni la confidentialité, ni une
validation de l'accord humain. Ils ne réactivent pas l'ancien juge ni ROUGE-L.

Fichier JSON requis : `rubric` vaut `human-text-quality-v1`, `evaluator` vaut
`human`, `study_id` est un identifiant commun à la campagne de revue, et `rows` contient pour chaque document `doc_id`,
`anonymized_sha256` (SHA-256 UTF-8 du texte anonymisé) et `ratings` (au moins
deux objets `{rater, readability, relevance, faithfulness}`). Les identifiants
d'évaluateurs sont pseudonymes. Notes manquantes, doublons, notes hors échelle
et empreintes divergentes sont refusés. Les textes restent locaux.

```sh
python scripts/prepare_text_quality.py --run runs/mon-run --out notes-humaines.json \
  --study-id etude-1 --raters annotateur-1 annotateur-2 \
  --readability-out textes-anonymises.json --review-out textes-pour-revue.json
# Remplir les notes nulles après revue indépendante de chaque document.
anonv2 evaluate --run runs/mon-run --task ticket_routing --quality-ratings notes-humaines.json
anonv2 score --run runs/mon-run --protocol <protocole-du-corpus>
```

## Qualité détaillée et calibration humaine (protocole expérimental v1)

L'option `--detailed-quality-backend` ajoute un juge local distinct des notes
globales. Elle s'inspire des questions élémentaires de BinEval (Cho et al.,
2026, https://www.alphaxiv.org/pdf/2606.27226) et de l'évaluation de la
cohérence factuelle par passages (AlignScore, Zha et al., 2023,
https://aclanthology.org/2023.acl-long.634.pdf). Les questions, réponses et
agrégations ci-dessous sont propres à ce projet : ce n'est ni une
implémentation officielle de BinEval ou AlignScore, ni un score humain validé.

Le modèle local répond `yes`, `no` ou `na` à six questions séparées : texte
compréhensible, grammaire, références compréhensibles, information principale
conservée, absence de contradiction et absence d'invention. Les trois premières
voient uniquement le texte anonymisé ; les autres voient aussi la source. Les
réponses applicables sont pondérées par la longueur du passage source puis les
documents applicables sont moyennés. `na` est exclu, et le nombre de passages
et documents applicables est publié. Les documents longs sont reconstruits et
découpés sans couper une décision ; la cohérence entre passages reste une
limite. Les contrôles texte vide et identité sont évalués pour chaque passage.
Si plus de 5 % des documents ont une erreur ou un contrôle échoué, les mesures
sont indisponibles. Les noms de système sont masqués ; un même modèle juge et
anonymiseur demeure une source possible de biais.

Une seconde consigne relève les contradictions ou inventions non privées en
citant pour chaque erreur un extrait exact et distinct du texte anonymisé.
Les citations sont vérifiées puis seules leurs quantités sont figées. La
métrique `quality_errors_per_document` est le nombre moyen de citations
détectées par document, avec le total dans les détails ; elle combine les deux
types d'erreurs et ne garantit pas leur détection exhaustive.

Les métriques `quality_fact_retention`, `quality_fact_omission` et
`quality_fact_contradiction` requièrent en plus un fichier de référence externe
`--quality-facts` de protocole `nonprivate-facts-v1`. Un annotateur doit y
choisir les faits utiles et non privés ; le code ne peut pas vérifier seul ce
choix. Chaque fait est une citation exacte de la source, par offsets Python
`start` inclus et `end` exclus, avec `id` unique par document. Pour chaque
document, `source_sha256` est l'empreinte SHA-256 UTF-8 de la source. Les
documents de la référence doivent couvrir exactement les prédictions réussies.
Le juge répond `preserved`, `omitted`, `contradicted` ou `uncertain` pour
chaque fait. Les trois taux ont pour dénominateur les faits jugés ; les faits
incertains sont exclus et comptés explicitement. Un fait traversant deux
passages est `uncertain`. Sans référence ou sans fait jugé, ces taux sont
indisponibles. Les résultats d'attaque restent séparés et ne sont pas déduits
de ces scores.

Le squelette de référence ne contient **aucun fait validé** et ne produit donc
aucune mesure de préservation tant qu'il n'a pas été renseigné :

```sh
python scripts/detailed_quality_human.py prepare --run runs/mon-run \
  --out notes-vierges.json --study-id pilote-1 --raters a b \
  --facts-out faits.json --readability-out lecture.json --review-out revue.json
# Compléter faits.json après revue : {"id":"f1","start":0,"end":12,"text":"citation ..."}
anonv2 evaluate --run runs/mon-run --detailed-quality-backend qwen_local_box \
  --quality-facts faits.json --local-quality-workers 2
anonv2 score --run runs/mon-run --protocol <protocole-du-corpus>
# Préparer une grille correspondant à la référence effectivement utilisée :
python scripts/detailed_quality_human.py prepare --run runs/mon-run \
  --out annotations.json --study-id pilote-1 --raters a b --facts faits.json \
  --readability-out lecture.json --review-out revue.json
# Remplir les notes indépendamment (yes/no/na et verdicts de faits), puis :
python scripts/detailed_quality_human.py calibrate --run runs/mon-run \
  --ratings annotations.json --out accord.json
```

Le document de revue appariée et la référence de faits contiennent ou peuvent
contenir des informations personnelles : les garder localement. Les notes
humaines doivent être remplies indépendamment et à l'aveugle du système ; le
programme ne peut pas garantir cette indépendance. La calibration vérifie les
empreintes, puis rapporte l'accord et les matrices de confusion par question et
par fait ; les égalités humaines, réponses incertaines et documents jugés
automatiquement de façon non unanime entre passages sont exclus et comptés.
Une grille non remplie est refusée. La calibration ne devient pas une
validation humaine tant que des personnes n'ont pas réellement annoté les
sorties. Pour comparer des systèmes, utiliser les mêmes documents, questions,
modèle et empreinte de référence de faits.

Des contrôles volontairement dégradés peuvent être préparés à partir de cette
référence : chaque cas supprime un fait de la source. La suppression peut laisser
une preuve ailleurs dans le texte ; aucun résultat attendu n'est donc supposé.
Une personne doit vérifier chaque cas, remplir `expected_facts` et/ou
`expected_questions`, puis passer `reviewed` à `true` avant toute évaluation.
Le fichier des cas contient le texte original ; le rapport ne contient que des
comptages, l'empreinte du fichier et l'identité du juge.

```sh
python scripts/detailed_quality_controls.py prepare --run runs/mon-run --facts faits.json --out controles.json
# Relire les cas et leurs attentes dans controles.json.
python scripts/detailed_quality_controls.py evaluate --controls controles.json \
  --backend qwen_local_box --workers 2 --out accord-controles.json
```

Ces suppressions constituent des contrôles synthétiques et ne remplacent pas
une revue de sorties réelles, ni une évaluation des erreurs plus subtiles.

`evaluate` fige les notes, l'empreinte du fichier et les prédictions ; `score`
ne relance aucun modèle. Si une étape `evaluate` doit aussi conserver une tâche
ou une population déjà évaluée, les options correspondantes doivent être
répétées. Sans notes valides, ces trois métriques sont `not_applicable`, pas zéro.

La comparaison humaine exige la même étude et les mêmes évaluateurs pour chaque document ; les fichiers de notes propres aux systèmes peuvent différer.

Le fichier facultatif `--review-out` contient les textes originaux, potentiellement personnels : le conserver en local. La grille commence volontairement avec des notes nulles, refusées tant qu’elles ne sont pas complétées.

## Qualité textuelle par juge local : pilote diagnostique

À la demande d'une mesure immédiate, une étape facultative distincte de la
revue humaine fige trois métriques : `local_readability`, `local_relevance`,
`local_faithfulness`. Elles ne sont **ni des notes humaines, ni validées comme
mesures universelles du sens**. Le modèle local peut être le même Qwen que
l'anonymiseur ; un biais d'auto-évaluation est alors possible.

Pour chaque document, la lisibilité est jugée sans original sur le texte
anonymisé et un texte vide, présentés dans un ordre masqué. Pertinence et
fidélité sont jugées en comparant le texte original à trois versions d'ordre
masqué : originale, anonymisée et vide. Les échelles 0/1/2 sont normalisées sur
[0,1]. Les contrôles sont effectivement demandés au modèle : le vide doit
recevoir 0 et l'identique 2 dans les dimensions correspondantes. Une réponse
invalide ou un contrôle raté est signalé et exclu ; au-delà de 5 % de documents
exclus, les trois métriques deviennent indisponibles. Ce contrôle élémentaire ne
prouve pas l'accord avec des évaluateurs humains. Les appels ont lieu dans
`evaluate` sur une API locale ; `score` ne relance aucun modèle.

Les textes trop longs sont découpés en passages alignés grâce aux décisions
d'anonymisation, sans couper un remplacement. Leur reconstruction est vérifiée.
La note d'un document est la moyenne des notes des passages, pondérée par leur
longueur d'origine. Elle ne mesure donc pas la cohérence à longue distance.
Chaque passage doit réussir ses contrôles ; les entrées incohérentes sont
signalées en erreur. La taille des invites est plafonnée en octets UTF-8, avec
une marge pour le gabarit de conversation et la limite d'entrée du serveur.

```sh
anonv2 evaluate --run runs/mon-run --local-quality-backend qwen_local_box --local-quality-workers 2
anonv2 score --run runs/mon-run --protocol <protocole-du-corpus>
```

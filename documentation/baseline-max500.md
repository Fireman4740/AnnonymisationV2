# Baseline Ling 3.0 Flash / gold / regex — cohorte figée

La baseline demandée le 16 octobre 2026 utilise uniquement `llm-full` avec
`inclusionai/ling-3.0-flash`, `oracle-mask` (gold) et `regex-only`.
La commande de lancement héritée reste `bash scripts/run_evaluation_smoke.sh`.

## Périmètre et sélection

Le plafond est de **500 documents évalués par corpus/dataset**, tous splits
d'évaluation réunis. Un corpus plus petit est pris intégralement parmi les
documents éligibles ; aucun document n'est dupliqué pour atteindre 500.
L'éligibilité conserve la borne de 16000 caractères et exclut les textes vides.

Les documents sont sélectionnés avant toute prédiction, par rang SHA-256 avec
graine 20261016. RAT-Bench est stratifié par difficulté et SPIA par corpus
source. Un quota d'une strate courte est redistribué aux autres strates.
Les données de train des évaluateurs d'utilité sont séparées, disjointes du
test, et figées avec lui ; elles ne sont pas des documents évalués.

Les autorisations externes restent identiques : synthétiques et SPIA peuvent
être traités par API. SupportTickets, TAB, CoNLL2003 et DBBIO sont évalués
localement avec gold et regex ; llm-full n'y est pas exécuté. Les restrictions
et absences de métriques sont explicites dans le bilan. Sur les corpus sans
annotations de spans, l'oracle gold ne masque rien : il est un contrôle texte
intact pour la tâche aval, pas une mesure de détection gold.

## Deux phases de la même baseline

1. `baseline.phase = freeze` prépare tous les corpus et écrit un snapshot
   complet, sans charger de clé API et sans exécuter de modèle. Le manifeste
   `runs/campaign/cohort.lock.json` contient les identifiants ordonnés,
   l'empreinte SHA-256 de chaque texte, et les empreintes de tous les fichiers
   pivot, gold, labels et locks. Le snapshot n'est publié qu'après vérification
   complète. Cette phase technique ne fournit pas le résultat de comparaison.
2. Le manifeste produit est récupéré et commité à l'emplacement
   `baseline.manifest`, puis `baseline.phase = evaluate` lance la mesure.
   Avant tout appel modèle, le snapshot est comparé au manifeste commité,
   tous les fichiers sont vérifiés et les pivots sont restaurés tels quels.

Le stockage durable sur la box est
`~/.cache/anonymisation-v2/baselines/baseline-ling-gold-regex-max500-v1/`.
Il contient `cohort.lock.json` et `processed/<dataset>/`. Le manifeste et une
archive de ce snapshot sont aussi conservés dans les artefacts du projet.
Le manifeste commité fixe les items ; la graine seule n'est pas utilisée
comme garantie de relance.

## Relancer

Relancer l'expérience sur son commit d'évaluation conserve la même commande,
la même configuration et le même manifeste. Le nouveau run relit le snapshot,
sans recharger les adaptateurs ni sélectionner de nouveaux documents. Le cache
LLM conserve sa politique habituelle : rejouer la baseline peut réutiliser ses
réponses ; cela n'est pas une répétition stochastique indépendante.

Pour une autre machine, restaurer l'archive de cohorte sous le même identifiant
dans le répertoire de snapshots configuré. Les sources officielles nécessaires
aux évaluateurs TAB et RAT-Bench doivent également rester disponibles et
conformes à leurs locks. Un snapshot absent ou divergent arrête le lancement ;
aucun repli vers une nouvelle ingestion n'existe pendant la phase d'évaluation.

Pour changer de cohorte, choisir explicitement un nouvel identifiant et refaire
la phase de préparation sur un nouveau nœud. Les sorties de la baseline
précédente restent intactes. Les erreurs de modèle sont conservées comme des
erreurs, jamais retirées de la sélection figée pour améliorer le résultat.

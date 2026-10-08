# ÉPIC H — Fiabilité de l'évaluation : audit et plan de remédiation

| | |
|---|---|
| **Statut** | En cours — lot 1 livré le 2026-10-02 |
| **Date** | 2026-10-01 |
| **Origine** | Audit du système d'évaluation (code à `cc5fbd1`) contre SPEC-06, SPEC-07 et la littérature récente |
| **Objectif** | Qu'aucun chiffre principal (CPR/IPR, TRIR, Utility Retention, QICR/RCR@k, calibration) ne soit publié sans protocole conforme, intervalle d'incertitude et test de sanité qui le valide |
| **Effort** | ~15 à 18 jours, hors temps de calcul |

---

## 1. Verdict

Le système **n'est pas encore fiable pour publier**. L'infrastructure est saine
(statuts `PROXY`/`DIAGNOSTIC` explicites, comptabilité d'erreur C4, gating par
capacités, scoring sans modèle C5, ~550 tests verts). Mais **aucune des
métriques principales de SPEC-07 §1 n'est aujourd'hui mesurée selon son
protocole** :

| Rang SPEC-07 | Métrique | État réel |
|---:|---|---|
| 1 | CPR / IPR | Adversaire **littéral** (`surface in text`), pas d'inférence, pas d'appariement de sujets |
| 2 | TRIR | **Fuite apprentissage/test** : l'attaquant s'entraîne sur le texte original des cibles |
| 3 | Mean Utility / Utility Retention | Mean Utility toujours `UNAVAILABLE` (pas de juge) ; rétention = accuracy d'un centroïde TF-IDF, sans variante réentraînée |
| 4 | QICR / RCR@k | **Absents** du code |
| 5 | ECE / Brier / MALE-k | Calibration ajustée et évaluée **sur les mêmes points synthétiques** ; trois définitions de MALE-k |
| — | Incertitude | **Aucun** intervalle de confiance, aucun test de significativité |
| — | Résultats | 0 run ; aucun corpus ingéré dans ce dépôt ; tests d'intégration de sanité ignorés (*skipped*) |

## 1 bis. État après le lot 1 (2026-10-02)

| Constat | État | Où |
|---|---|---|
| F1, F2, F3, F4 — TRIR | ✅ corrigé : protocole v2 (blocs groupés par sujet, attaquant entraîné hors cible avec assertion de non-fuite), identité inter-documents explicite, égalités en espérance, hasard + classe majoritaire, seule `TRIRUnavailable` est tolérée | `metrics/tria.py`, `tests/unit/test_tria.py` |
| F5 — CPR/IPR littéral | ⚠️ partiel : recherche normalisée et bornée aux mots, limitation requalifiée ; l'adversaire d'inférence (H-3) reste à faire, CPR/IPR restent `PROXY` | `metrics/leakage.py`, `metrics/protection.py` |
| F6 — « LLM local suffit » | ✅ spec corrigée (hypothèse à valider) ; validation empirique = H-3 | SPEC-07 §5 |
| F7 — QICR / RCR@k | ⬜ non fait : `Combination.qi_set` ne référence pas les annotations gold ; il faut d'abord un lien de schéma (`annotation_ids`) pour éviter un QICR approximé par catégorie | — |
| F8, F9 — calibration | ✅ formules uniques (`metrics/calibration.py`), sensibilité de l'ECE aux bacs ; statistiques in-sample renommées `fit_*` | `metrics/calibration.py`, `hybrid_qi/` |
| F10 — hybrid_qi | ⬜ non enregistré (choix délibéré : pas de tests, pas de README ; à traiter avec la conception du pipeline) | — |
| F11 — utilité | ⚠️ partiel : rétention en macro-F1 + IC apparié ; variante réentraînée et juge Mean Utility restent à faire | `metrics/downstream.py` |
| F12 — incertitude | ✅ IC 95 % par bootstrap en grappes (document / sujet) sur toutes les métriques principales et diagnostiques ; comparaison appariée entre runs à faire | `metrics/uncertainty.py`, `metrics/intervals.py` |
| F13, F15 — sanité S4–S6 | ⬜ non fait | — |
| F14 — verrou | ✅ `uv.lock` régénéré (`requires-python >= 3.10`), suite verte sous `uv run --locked` | `uv.lock` |
| **F16** (nouveau) — reproductibilité | ✅ `score` relisait le gold courant sans vérifier qu'il était celui du run ; protocole/statut par défaut silencieux ; commit sans état de l'arbre. Corrigé : chaîne d'empreintes ingest → predict → score, `inputs` dans la scorecard, `publication_blockers` (erreurs > 5 %, arbre modifié ou inconnu) | `schema/integrity.py`, `cli/predict.py`, `cli/score.py` |
| **F17** (nouveau) — texte anonymisé absent | ✅ un document scoré sans `anonymized_text` était traité comme texte vide (protection parfaite) ; désormais erreur | `metrics/scorecard.py` |

### Lot 2 (2026-10-07) — cartographie corpus × système × métrique

Banc reproductible `scripts/eval_matrix.py` : chaque corpus × {passthrough,
oracle, redact-all, regex-only, deterministic}, deux passages, contrôle
bit-à-bit, ancres de sanité et oracle (prédictions = gold). Défauts trouvés
et corrigés :

| Constat | État | Où |
|---|---|---|
| **F18** — ER plafonné sous 1.0 même pour un oracle (annotations sans offsets comptées) | ✅ exclues du dénominateur, comme F1/fuite/CPR | `metrics/entities.py` |
| **F19** — RAT-Bench : 1re occurrence seulement, en sous-chaîne (« male » dans « female ») | ✅ toutes les occurrences, mots entiers, casse ignorée, `entity_id` partagé | `datasets/ratbench.py` |
| **F20** — RAT-Bench : `doc_id = ratbench:{id}` collisionne entre level_1..3 (profils différents) ; `difficulty` défaut 1 silencieux | ✅ `ratbench:L{niveau}:{id}`, `difficulty` obligatoire | `datasets/ratbench.py` |
| **F21** — corpus d'utilité pure (support, bitext) refusés par `predict`/`score` (annotations exigées) | ✅ absence déclarée par le lock d'ingestion | `cli/predict.py`, `cli/score.py` |
| **F22** — ingestion d'un split : anciens splits laissés hors lock (cas `tab`) ; publication non atomique | ✅ publication en transit + remplacement | `datasets/ingest.py` |
| **F23** — TRIR = 1.0 avec un seul sujet candidat (= hasard) | ✅ `UNAVAILABLE` | `metrics/tria.py` |
| **F24** — rétention aval à 1.0 pour `redact-all` : classifieur non informatif, texte sans information → 1re classe alphabétique | ✅ classe a priori + garde « doit battre la classe majoritaire » | `metrics/_tfidf.py`, `metrics/downstream.py` |
| **F25** — paramètre de système invalide → trace Pydantic brute | ✅ erreur d'usage actionnable | `systems/base.py` |
| **F26** — estimateur de risque naïf : k̂ ≈ 4e-27, risque = 1 partout (ECE 0,80, MALE-k 11,3 sur RAT-Bench) | ⬜ côté moteur de risque (L4), pas l'évaluation | `risk/` |
| **F27** — pivots locaux échantillonnés à 32 docs (support, bitext, dbbio, ratbench) : aucune tâche aval informative ; pivot `tab` incohérent avec son lock | ⬜ réingestion complète requise (sources brutes absentes de ce poste) | `data/processed` |

## 2. Constats vérifiés

Gravité : **B** = bloquant (chiffre faux ou trompeur), **M** = majeur (non
conforme à la spec ou à l'état de l'art), **m** = mineur.

| # | Grav. | Constat | Preuve |
|---|:---:|---|---|
| F1 | **B** | `evaluate_trir` entraîne le classifieur sur les textes originaux de **tous** les documents évalués puis prédit sur leurs versions anonymisées. L'attaquant connaît le texte source de chaque cible : TRIR mesure le recouvrement lexical résiduel avec l'original, pas un risque de ré-identification. TRIA modélise au contraire un attaquant qui agrège des **sources auxiliaires** sur les individus. | `metrics/tria.py:176-195`, `metrics/scorecard.py:455-473` |
| F2 | **B** | Si le corpus n'a ni `subject_id` ni `author_id`, `_subject_of` retombe sur `doc_id` : chaque document est son propre sujet, TRIR(passthrough) = 1 par construction. Dans un document multi-sujets, seul le **premier** `subject_id` rencontré est retenu. | `metrics/scorecard.py:218-235` |
| F3 | M | Égalités TRIR : le commentaire annonce « premier sujet », le code `max(..., key=(score, subject))` retient le **dernier** lexicographique. Le niveau de hasard publié (1/N) ignore le déséquilibre des classes. | `metrics/tria.py:150-156`, `:89` |
| F4 | M | `except Exception` autour de TRIR : toute erreur de programmation devient `UNAVAILABLE` silencieux — contraire à la règle d'or. | `metrics/scorecard.py:474` |
| F5 | **B** | CPR/IPR : `A_i` = présence **littérale, sensible à la casse, en sous-chaîne** de la surface gold. Le code affirme une « borne inférieure de l'inférabilité » ; c'est faux en général : une surface courte (« 28 », « M. ») trouvée ailleurs compte comme fuite (sur-estimation du risque), une variante de casse ou une paraphrase compte comme protégée (sous-estimation). Ni appariement de sujets, ni score partiel 0,5 comme dans SPIA. | `metrics/protection.py:305`, `metrics/scorecard.py:422-432` |
| F6 | M | SPEC-07 §5 affirme qu'« un LLM local suffit » comme adversaire, sur la foi du ρ > 0,98 de SPIA. Or les trois adversaires comparés dans SPIA sont Claude-Sonnet-4.5, GPT-4.1 et Claude-Haiku-4.5 (Annexe E.1, Table 11) : **aucun modèle local**. L'extrapolation à un modèle < 30 B est une hypothèse à tester, pas un acquis. | SPEC-07 §5 ; SPIA, arXiv 2604.21211, Annexe E.1 |
| F7 | **B** | QICR, QICR@j et RCR@k — « diagnostic central du projet » — n'existent nulle part dans `src/`. | `grep -rn qicr src` vide |
| F8 | **B** | Calibration `hybrid_qi` : l'isotone est ajustée puis ECE/Brier/MALE-k calculés **sur les mêmes combinaisons** d'un monde synthétique. C'est une erreur d'ajustement, pas une calibration. SPEC-06 §8 exige un split `calib` distinct et une recalibration par domaine × langue. | `pipelines/hybrid_qi/risk.py:520-590` ; SPEC-06 §8 |
| F9 | M | Trois définitions de MALE-k coexistent : SPEC-07 `|log(k̂+1) − log(k+1)|` ; `calibration.py` `|ln(k̂/k)|` ; `risk.py` `|log2 k_raw − log2 k_true|` sur le k **non calibré**. Brier/ECE : SPEC-07 note `y_i` sans le définir ; `calibration.py` utilise le risque gold continu `1/k_true`. | `hybrid_qi/calibration.py:234`, `hybrid_qi/risk.py:581` |
| F10 | M | `hybrid_qi` n'a ni `__init__.py`, ni `tests/`, ni `README.md`, et n'est pas importé par `pipelines/__init__.py` : inatteignable par la CLI, non testé, contraire au guide `creer-un-pipeline.md`. | `pipelines/__init__.py:21-34` |
| F11 | M | Utilité : `score` ne fournit aucun juge → Mean Utility toujours `UNAVAILABLE`. La rétention aval publie une **accuracy** (pas le F1 de routage de §6.B), et la variante « réentraînée sur anonymisé » exigée par §6 étape 4 n'existe pas. | `cli/score.py:180-230`, `metrics/downstream.py:62-179` |
| F12 | **B** | Aucune incertitude : pas de bootstrap ni d'intervalle de confiance ; `compare` juxtapose des valeurs ponctuelles. Toute différence entre systèmes est actuellement indécidable. | `metrics/comparison.py` |
| F13 | M | Tests de sanité : S1–S3 seulement, sur fixtures unitaires ; leurs versions intégration sont ignorées faute de corpus ingéré ; **S4–S6 absents**. | `tests/unit/test_orchestrator.py:407+`, `tests/integration/test_sanity.py:76-98` |
| F14 | m | `uv.lock` périmé (`uv lock --check` échoue) ; `requires-python` diverge (`>=3.10` vs `>=3.11`). `uv run --locked` ne démarre pas. | `pyproject.toml:6`, `uv.lock:3` |
| F15 | m | `reid_success_rate` toujours `UNAVAILABLE` ; S1–S5 de SPEC-07 §11 sont formulés en `R_succ` et ne sont donc testables sur aucun run. | `metrics/scorecard.py:679-684` |

## 3. Référentiel « état de l'art » retenu

| Exigence | Source | Traduction dans le projet |
|---|---|---|
| Attaquant de ré-identification entraîné sur des **connaissances auxiliaires**, disjointes des documents publiés | TRIA, Manzanares-Salor, Sánchez & Lison, DMKD 2024 (doi:10.1007/s10618-024-01066-3) | H-2 |
| Unité d'évaluation = **le sujet** ; adversaire LLM qui infère ; appariement un-à-un des sujets ; score PII 1 / 0,5 / 0 ; sujets non appariés = 0 | SPIA, arXiv 2604.21211, §4.2 | H-3 |
| Risque estimé **dans une population** de référence (k pondéré) | RAT-Bench, arXiv 2602.12806 | H-5 |
| Risque de ré-identification rapporté avec **garanties statistiques** en échantillon fini, selon la configuration de l'attaquant | Conformal Privacy Auditing, arXiv 2609.21340 | H-7 |
| Utilité = performance sur la tâche métier, figée **et** réentraînée | SPEC-07 §6 ; [@loiseau2025taueval] | H-6 |

## 4. Plan

Ordre imposé par les dépendances : on ne publie rien avant **H-7** (incertitude)
et **H-8** (sanité), et on ne lance pas de campagne (**H-9**) avant que H-2, H-3
et H-6 aient produit au moins un statut non `PROXY`.

```text
H-0 socle ──┬─> H-1 conformité spec ─┬─> H-2 TRIR ────────┐
            │                        ├─> H-3 CPR/IPR ─────┤
            │                        ├─> H-4 QICR/RCR@k ──┼─> H-7 incertitude ─> H-8 sanité ─> H-9 campagne
            │                        ├─> H-5 calibration ─┤
            └────────────────────────┴─> H-6 utilité ─────┘
```

---

### H-0 — Socle reproductible

| | |
|---|---|
| **Priorité** | P0 |
| **Corrige** | F10, F14 |
| **Effort** | 1 j |

- Régénérer `uv.lock` et aligner `requires-python` (choisir 3.11 si une
  dépendance l'impose, sinon relocker en 3.10) ; `uv run --locked pytest`
  doit passer sur un clone frais.
- `hybrid_qi` : ajouter `__init__.py`, `README.md`, `tests/`, et l'importer
  dans `pipelines/__init__.py` — ou le déplacer hors de `pipelines/` tant qu'il
  n'est pas prêt. Un pipeline inatteignable ne doit pas laisser croire qu'il
  est évalué.
- Ingérer les corpus P0 sur la machine de calcul (`ANONV2_V1_DATASETS`) pour
  que les tests d'intégration cessent d'être ignorés.

**Critère** : `uv run --locked python -m pytest tests src/anonymisation/pipelines -q`
vert, **0 skip lié à un corpus absent** sur la machine de calcul.

### H-1 — Arbitrer les divergences code ↔ spec

| | |
|---|---|
| **Priorité** | P0 |
| **Corrige** | F6, F9 |
| **Effort** | 0,5 j |

Amendements de SPEC-07 (la doc est normative : on tranche, on n'ignore pas) :

- §4 : une seule définition de MALE-k (proposée : `|ln(k̂+1) − ln(k+1)|`,
  celle de la spec) ; définir `y_i` pour Brier/ECE (risque gold `1/k_true`,
  ou événement binaire `k_true ≤ k_seuil` — à choisir, et le dire).
- §5 : remplacer « un LLM local suffit » par « hypothèse à valider (H-3) » et
  citer précisément les adversaires de SPIA.
- Nouveau §5.x : protocole TRIR (H-2) ; protocole CPR/IPR par inférence (H-3).

**Critère** : un seul module implémente chaque formule ; tests de non-régression
sur la formule de la spec.

### H-2 — TRIR conforme à TRIA

| | |
|---|---|
| **Priorité** | P0 |
| **Corrige** | F1, F2, F3, F4 |
| **Effort** | 2 j |

- Séparer **connaissance auxiliaire** et **cibles** : pour chaque sujet, les
  documents d'apprentissage de l'attaquant sont des documents **originaux
  disjoints** des cibles (autres posts d'un même auteur, autres documents du
  même sujet). Les cibles ne sont vues **que** sous forme anonymisée. Split
  par groupe et déterministe (`datasets/_split.py`).
- Ensemble candidat déclaré, incluant des sujets distracteurs absents des
  cibles. Publier top-1 et top-5, le hasard uniforme **et** la classe
  majoritaire.
- Égalités : crédit fractionnaire `1/|ex-aequo|` si le vrai sujet en fait
  partie (accuracy espérée), au lieu d'un départage arbitraire.
- Corpus sans `subject_id`/`author_id`, ou sujets à un seul document : TRIR
  `UNAVAILABLE` avec raison explicite — plus de repli sur `doc_id`.
- Documents multi-sujets : une cible par couple (document, sujet).
- Retirer le `except Exception` ; seules les erreurs de contrat attendues
  deviennent `UNAVAILABLE`.
- Plus tard : variante neuronale locale (encodeur fin-tuné), comme dans TRIA.

**Tests** : intersection des `doc_id` apprentissage/cibles vide (assertion
bloquante) ; TRIR(redact_all) ≈ hasard ; TRIR(passthrough) > hasard **sans**
être trivialement 1 ; test d'égalité sur classes déséquilibrées.

### H-3 — CPR/IPR par adversaire d'inférence (protocole SPIA)

| | |
|---|---|
| **Priorité** | P0 — métrique principale |
| **Corrige** | F5, F6 |
| **Effort** | 3 j |

- Nouvelle étape figée `anonv2 attack --run runs/<r> --adversary <cfg>` qui
  écrit `attacks.jsonl` (sujets inférés + valeurs PII par catégorie, prompts
  et modèle versionnés). `score` **lit** ce fichier et ne lance jamais de
  modèle (C5). Réponse vide = erreur (C3).
- Scoring SPIA : appariement un-à-un des sujets, score PII 1 / 0,5 / 0, sujets
  non appariés à 0, CPR et IPR publiés ensemble.
- L'adversaire littéral reste, renommé `cpr_literal` / `ipr_literal`,
  `DIAGNOSTIC`, avec frontières de mots et normalisation de casse, et une
  description honnête : ni borne inférieure ni borne supérieure.
- **Validation de l'adversaire local < 30 B** (lève F6) : sur l'ensemble de
  test annoté humainement de SPIA (295 documents), mesurer l'accord de
  l'adversaire local avec la vérité, puis la corrélation de Spearman du
  classement des méthodes avec les CPR/IPR publiés. Seuil proposé : ρ ≥ 0,9
  et écart absolu ≤ 5 points ; en dessous, CPR/IPR restent `DIAGNOSTIC`.

**Critère** : CPR/IPR `OFFICIAL` sur SPIA avec adversaire documenté ;
`DIAGNOSTIC` ailleurs tant que la validation n'est pas faite.

### H-4 — QICR, QICR@j, RCR@k

| | |
|---|---|
| **Priorité** | P0 — contribution du projet |
| **Corrige** | F7 |
| **Effort** | 2 j |

- Entrée gold : `combinations.jsonl` (`k_true`, source ∈ {generated,
  annotated, dataset} — garde de circularité I-CMB-3).
- Entrée système : combinaisons détectées et `k̂` ; nouvelle capacité dans
  `capabilities.py`, métrique `UNAVAILABLE` pour les systèmes qui ne la
  déclarent pas.
- QICR : une combinaison à risque est rappelée si **tous** ses QI sont
  détectés (appariement partiel de spans). RCR@k : `P(k̂ ≥ k | k_true ≥ k)`.
  Publication jointe obligatoire (`assert_published_together`).

**Tests** : exemple de SPEC-07 §3 (F1 ≈ 0,86, QICR = 0) ; système « tout à
risque » → QICR = 1, RCR@k = 0.

### H-5 — Calibration sur données tenues à l'écart

| | |
|---|---|
| **Priorité** | P1 |
| **Corrige** | F8, F9 |
| **Effort** | 2,5 j |

- Ajuster l'isotone sur le split `calib`, évaluer sur `test` ; ventiler par
  domaine × langue (SPEC-06 §8). Les statistiques in-sample de `risk.py`
  sont renommées `fit_*` et sortent du rapport de calibration.
- Population réelle : PUMS (RAT-Bench) pour l'anglais, k pondéré par
  `PWGTP`. Pour le français, sans population réelle, le risque reste
  `DIAGNOSTIC` — dépendance de données à lever, ne pas contourner.
- Valider la copule contre le k exact de PUMS ; publier MALE-k.
- Rapporter : diagramme de fiabilité, ECE à bacs équi-effectifs avec
  sensibilité au nombre de bacs (5, 10, 15, 20), Brier décomposé
  (fiabilité / résolution), AUROC et AUPRC.

**Critère** : ECE < 0,05 par domaine **sur test**, avec intervalle de
confiance (H-7).

### H-6 — Utilité conforme à SPEC-07 §6

| | |
|---|---|
| **Priorité** | P1 |
| **Corrige** | F11 |
| **Effort** | 2,5 j |

- Rétention aval : macro-F1 en plus de l'accuracy ; variantes **figée** et
  **réentraînée sur anonymisé** ; tâches de référence routage (support) et
  modération/thème (forums), plus une tâche RH.
- Mean Utility : étape figée `anonv2 judge` → `judgments.jsonl` (juge local,
  prompt et modèle versionnés) lue par `score`. Valider le juge contre un
  échantillon annoté humainement (~100 documents ; Spearman et α de
  Krippendorff publiés).
- Similarité d'embeddings / BERTScore : diagnostic seulement.

### H-7 — Incertitude et comparaison

| | |
|---|---|
| **Priorité** | P0 pour toute publication |
| **Corrige** | F12 |
| **Effort** | 1,5 j |

- Bootstrap par grappes (document ; sujet pour CPR/IPR ; auteur pour TRIR),
  graine fixée, IC 95 % pour chaque métrique principale et diagnostique.
- `compare` : bootstrap apparié (mêmes documents) ; annoncer « différence
  non significative » quand l'IC de la différence contient 0. Ne jamais
  classer des systèmes sur des valeurs ponctuelles.
- Étapes LLM (prédiction, attaque, juge) : ≥ 3 graines ou températures
  nulles documentées ; variance inter-graines publiée.

### H-8 — Tests de sanité S1–S6 comme portes de publication

| | |
|---|---|
| **Priorité** | P0 |
| **Corrige** | F13, F15 |
| **Effort** | 1,5 j |

- Reformuler S1–S5 en TRIR et CPR/IPR (R_succ indisponible) ; implémenter
  S4–S6 ; les exécuter en intégration sur corpus ingérés.
- Ajouts : TRIR(redact_all) dans l'IC du hasard ; CPR(redact_all) ≈ 1 ;
  CPR(passthrough) faible ; monotonie P0 → P4 sur risque et utilité.
- Un run qui échoue une porte est **non publiable** (même mécanisme que le
  seuil de 5 % de C4).

### H-9 — Campagne d'évaluation

| | |
|---|---|
| **Priorité** | P1 — après H-0 à H-8 |
| **Effort** | 2 j + calcul |

- Systèmes : passthrough, redact_all (bornes), regex_only, deterministic,
  llm_full, hybrid_qi.
- Corpus : SPIA (référence externe CPR/IPR), TAB, PersonalReddit (TRIR par
  auteur), SupportTickets (utilité), RAT-Bench + PUMS (risque population),
  quasifr (FR).
- Politiques P0–P4 → table de points de fonctionnement et frontière
  confidentialité/utilité, **avec IC**, ventilée par langue, domaine et
  mode d'expression (SPEC-07 §7, §10).
- Premier jalon : reproduire un chiffre publié de SPIA avec le pipeline du
  projet. Tant que ce n'est pas fait, aucun chiffre n'est comparable à la
  littérature.

## 5. Définition de « évaluation fiable » (critère de sortie de l'épic)

- [ ] Aucune métrique principale en `PROXY` sur au moins un corpus de référence.
- [ ] TRIR : apprentissage et cibles disjoints, vérifié par assertion.
- [ ] CPR/IPR : adversaire d'inférence validé contre SPIA (ρ, écart absolu publiés).
- [ ] QICR et RCR@k publiés ensemble.
- [ ] Calibration évaluée hors échantillon, par domaine × langue.
- [ ] IC 95 % sur chaque chiffre ; comparaisons par bootstrap apparié.
- [ ] S1–S6 verts en intégration.
- [ ] Un chiffre publié de la littérature reproduit, écart documenté.
- [ ] `uv run --locked` reproductible ; locks de run complets.

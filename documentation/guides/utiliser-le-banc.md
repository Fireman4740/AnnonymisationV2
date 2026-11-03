# Utiliser le banc d'évaluation

Guide opératoire : préparer un corpus, faire tourner un système, scorer,
comparer, et lancer les suites figées. Les règles de fond (métriques,
contraintes C1–C5) sont dans [`metrics-core.md`](../metrics-core.md) et
[`CLAUDE.md`](../../CLAUDE.md) ; ajouter un système : [`creer-un-pipeline.md`](creer-un-pipeline.md).

Dans tout le guide, `anonv2` signifie :

```sh
PYTHONPATH=src uv run --locked python -m anonymisation.cli.main
```

---

## 1. État de vérification (3 novembre 2026)

Le banc n'est **pas** certifié sur tous les corpus. Ce tableau dit ce qui a été
exécuté de bout en bout, pas ce que le code prétend couvrir.

| Corpus | Dernière exécution de bout en bout | Statut |
|---|---|---|
| QuasiLeak-Bench | runs `5109c517` (test-50) et `08d72981` (holdout-50), 0 échec | vérifié (échantillon de 50) |
| RAT-Bench, TAB, support tickets | run `a25075a4`, 5 documents par corpus | vérifié en sanité seulement |
| Autres corpus de `campaign.json` (quasifr, conll2003, dbbio, spia, openpii, bitextsupport) | campagne « Banc fiable » `9a135ca1` sans résultat final | **non vérifié** |
| PANORAMA | dataset Hugging Face soumis à conditions (HTTP 403) | non exécutable |
| personalreddit | exclu : pas de spans ancrés ni de tâche d'utilité validée | exclu |

Limites connues, toutes documentées dans les modules concernés :

- échantillons de 50 documents : intervalles larges, statut `sampled` ;
- QICR / MALE-k : pas de population indépendante pour les corpus réels ;
- Brier / ECE : aucun système n'émet de prévision validée de succès d'attaque ;
- prédictions LLM reproductibles bit à bit **depuis le cache** ; une
  régénération par le serveur n'est pas garantie identique ;
- aucune politique de divulgation statique RH / forums / support n'est
  encore définie (seul le mécanisme existe).

---

## 2. Prérequis

| Élément | Valeur |
|---|---|
| Python / dépendances | `uv sync --locked --python 3.11 --extra datasets --extra metrics --extra attack --extra tab_eval` |
| Cache des corpus | `ANONV2_V1_DATASETS` (défaut du contrat : `~/.cache/anonymisation-v2/datasets`) |
| Cache LLM | `ANONV2_LLM_CACHE_DIR` (défaut du contrat : `~/.cache/anonymisation-v2/llm`) |
| Modèle local | Qwen3.8-27B via vLLM, `http://127.0.0.1:18020/v1`, backend `qwen_local_box` (`configs/llm/backends.yaml`) |
| API distante | **interdite** sauf corpus synthétiques et SPIA (OpenRouter autorisé) ; la garde est dans la campagne et les profils. La campagne actuelle n'en utilise aucune : anonymiseur **et** attaquants (RAT-Bench, SPIA) = `qwen_local_box`. Le rôle `attacker_spia` (Ling via OpenRouter) de `backends.yaml` n'est pas utilisé par la campagne |

Rien sous `data/` n'est versionné. Les licences restrictives (MIMIC, MEDDOCAN,
corpus internes) ne doivent jamais être commitées.

---

## 3. Boucle de base : un système sur un corpus

```sh
anonv2 datasets list                                  # corpus, licences, statut
anonv2 datasets ingest <clé> --split <split>          # source → format pivot, lock d'ingestion
anonv2 systems list                                   # systèmes, capacités, politique
anonv2 predict --dataset <clé> --split <split> --system <système> --profile <profil> \
  [--param k=v ...] [--policy P0..P4] [--disclosure-policy <id>] \
  [--selection-manifest <lock.json>] --out runs/<nom>
anonv2 score --run runs/<nom> --protocol <protocole du manifeste>
anonv2 compare --runs runs/<a> runs/<b> --out runs/compare.md
```

- **Protocole** : champ `evaluation.protocol` du manifeste
  (`configs/datasets/<clé>.yaml`), par ex. `ratbench-v1`, `tab-official`,
  `quasileak-v1`.
- **Profil** : `deterministic` pour les systèmes sans LLM, sinon le profil du
  pipeline (`llm_windowed`, `llm_anchored`, `llm_full`, `llm_contextual`,
  `hybrid_qi`).
- **Sélection figée** : `--selection-manifest` restreint le run à une liste de
  `doc_id` + empreintes de texte ; tout système comparé doit utiliser la même.
- **`datasets ingest --limit`** est refusé sur les corpus dont les groupes
  d'annotations seraient coupés (QuasiLeak) : ingérer le split complet puis
  utiliser une sélection.
- **Commit avant predict** : un run produit avec des modifications non
  commitées est marqué non publiable.

`score` ne relance aucun modèle (C5) : il relit `predictions.jsonl`,
`manifest.lock.json` et les sources verrouillées à l'ingestion. Rejouer
`score` sur un run doit redonner une scorecard identique au bit près.

### Lire une scorecard

- `primary` : CPR / IPR / Utility Retention quand le protocole les rend
  calculables — ce sont les métriques principales du projet ;
- `diagnostic` : spans, masquage, fuites, P-GF1 QuasiLeak… jamais à présenter
  à côté d'un chiffre officiel (SPEC-07 §9) ;
- `publishable` / `publication_blockers` : un run au-delà de 5 % de documents
  en erreur, non commité ou incomplet n'est pas publiable (C4) ;
- `system.gold_aware` : le système a reçu le gold (ancre, pas un concurrent) ;
- `system.disclosure_policy` : politique HIDE/KEEP appliquée au run.

---

## 4. Accès au gold

`predict` ne transmet les annotations gold qu'aux systèmes qui déclarent la
capacité `gold_aware` (aujourd'hui : `oracle-mask`, et `deterministic` pour son
contrôle VALIDATE). Les autres reçoivent un gold vide. Le lock note
`gold_access`, et `compare` affiche les systèmes gold-aware comme ancres.
Un nouveau pipeline qui a besoin du gold doit le déclarer ; il sort alors des
comparaisons entre concurrents.

---

## 5. Politique de divulgation HIDE / KEEP

Étape déterministe après détection, sans changer aucun prompt :
`--disclosure-policy <id>` (configurations dans `configs/policy/disclosure.yaml`,
détails dans [`politique-divulgation.md`](politique-divulgation.md)).

- `document` / `document-extended` : politique fournie par chaque document
  (QuasiLeak) ; échoue sur un corpus qui n'en fournit pas ;
- `all-hide` : contrôle, doit laisser le run inchangé ;
- politique statique : à ajouter dans le YAML pour les corpus RH, forums,
  support (listes `hide` / `keep` / `neutral`, `neutral_action`,
  `attribute_table` obligatoires).

Dans une campagne, `disclosure_policy` d'un système accepte une table par
dataset avec une clé `default` explicite :
`{"quasileak": "document", "default": null}`.

---

## 6. QuasiLeak-Bench

Détails du corpus : [`datasets/quasileak.md`](../datasets/quasileak.md).

```sh
python scripts/fetch_quasileak.py --root "$ANONV2_V1_DATASETS"   # empreintes vérifiées
anonv2 datasets ingest quasileak --split test
anonv2 predict --dataset quasileak --split test --system llm-windowed --profile llm_windowed \
  --param backend=qwen_local_box \
  --selection-manifest configs/evaluation/frozen/quasileak-test-holdout-50-v1.lock.json \
  --out runs/ql-windowed
anonv2 score --run runs/ql-windowed --protocol quasileak-v1
```

La scorecard contient alors :

| Métrique | Sens |
|---|---|
| `quasileak_pgf1_d8` | P-GF1 officiel (scorer de l'article inchangé) via l'adaptateur de l'annexe D.8 : décisions → groupes par attribut → filtrage par la politique fournie |
| `quasileak_er_pre_policy` | rappel des indices HIDE sur tout l'inventaire de décisions, avant politique |
| `quasileak_group_mask_rate` | proxy : part des groupes HIDE dont un indice est entièrement masqué |

Références rapportées **à part**, car elles reçoivent le profil de l'auteur :

```sh
# détecteur Qwen natif, invite zéro-shot officielle
python scripts/predict_quasileak_local.py --root "$ANONV2_V1_DATASETS/QuasiLeak-Bench" \
  --selection configs/evaluation/frozen/quasileak-test-holdout-50-v1.ids.json \
  --out runs/ql-native/predictions.jsonl
anonv2 quasileak-score --root "$ANONV2_V1_DATASETS/QuasiLeak-Bench" \
  --predictions runs/ql-native/predictions.jsonl --split test \
  --selection configs/evaluation/frozen/quasileak-test-holdout-50-v1.ids.json --out runs/ql-native/scores.json
# variante D.8 « + regroupement LLM » sur un run d'anonymiseur
python scripts/quasileak_llm_grouping.py --root "$ANONV2_V1_DATASETS/QuasiLeak-Bench" \
  --run runs/ql-windowed --selection configs/evaluation/frozen/quasileak-test-holdout-50-v1.ids.json \
  --out runs/ql-windowed/quasileak_llm_groups.jsonl
```

Sélections figées (`configs/evaluation/frozen/`) :

| Sélection | Usage |
|---|---|
| `quasileak-validation-50-v1` | réglages et choix (ex. table d'attributs) |
| `quasileak-test-50-v1` | **a servi au développement** : non indépendante |
| `quasileak-test-holdout-50-v1` | **résultat de référence** ; ne doit servir à aucun réglage |

Une nouvelle sélection disjointe se crée avec
`scripts/select_quasileak.py --exclude-profiles-of <ids.json>`.

---

## 7. Suites figées (contrat fixe des expériences)

### QuasiLeak dans la campagne

La cohorte `banc-fiable-200-v2` lie la liste `datasets` à son manifeste : un
corpus dont la sélection officielle est figée ailleurs entre par
`external_datasets` (`scripts/campaign_external.py`). Pour QuasiLeak, chaque
entrée déclare explicitement split, sélection et manifeste pivot (empreintes),
protocole, politique de divulgation, sélections de développement exclues
(`test-50`), `llm_grouping` et `native_detector`. La taille doit égaler
`evaluation_subset.documents_per_dataset`. En plus de la boucle commune, la
campagne produit, **à part** (ces références reçoivent le profil) : le
regroupement LLM D.8 par système, le détecteur natif zéro-shot par dataset,
puis la parité : le scorer officiel exécuté seul (`python -I`) doit redonner
exactement les scores de chaque scorecard, sinon la campagne échoue.


Les expériences lancent toujours `bash scripts/run_evaluation_smoke.sh` :
installation verrouillée, attente de capacité Qwen, préflight, puis la suite
nommée dans **`configs/evaluation/active_suite.json`** :

| `suite` | Configuration | Contenu |
|---|---|---|
| `quasileak` | `configs/evaluation/quasileak_suite.json` | QuasiLeak seul ; sert au choix de table d'attributs sur validation |
| `campaign` | `configs/evaluation/campaign.json` | **tout le banc** : 9 corpus de la cohorte figée + QuasiLeak (`external_datasets`) ; predict, attaques, juges locaux, score, rejeu bit à bit, audit, parités RAT-Bench et QuasiLeak, tableau `runs/campaign/scores.md` |
| `smoke` | — | sanité 2 documents RAT-Bench (ancres passthrough / redact-all) |

Le choix n'est jamais déduit de la présence d'un fichier. Changer de suite =
modifier `active_suite.json` et commiter. Toute modification d'une sélection
ou d'une cohorte se fait par un **nouveau** fichier figé, jamais en éditant un
manifeste déjà utilisé.

Résumés produits : `runs/quasileak-<split>-summary.json` (ligne
`FINAL_SUMMARY` du journal) ou `FINAL_CAMPAIGN_SUMMARY` pour la campagne.

---

## 8. Reproductibilité — ce qui est garanti

- lock d'ingestion : empreintes des sources, refus si elles changent ;
- lock de run : commit, état git, paramètres effectifs, prompts, modèles,
  politique, politique de divulgation, accès au gold, sélection ;
- `score` refuse des sorties modifiées après `predict` ;
- scorers originaux recopiés et vérifiés par empreinte (TAB, QuasiLeak,
  RAT-Bench/SPIA selon les modules `metrics/`) ;
- réponses LLM validées avant mise en cache ; une réponse vide ou invalide est
  une erreur, jamais « aucune entité » (C3).

## 9. Dépannage

| Symptôme | Cause / correctif |
|---|---|
| `Pivot ingéré absent` | lancer `anonv2 datasets ingest <clé> --split <split>` |
| `sources brutes … introuvables` (score QuasiLeak) | relancer `scripts/fetch_quasileak.py` vers le chemin verrouillé |
| `--disclosure-policy exige des décisions` | le système est une boîte noire (passthrough, redact-all) |
| `politique … exige Document.meta['policy']` | corpus sans politique propre : utiliser une politique statique |
| `QWEN_ADMISSION … ready: false` en boucle | serveur Qwen saturé par d'autres runs ; attendre ou libérer de la capacité |
| `run produit avec des modifications non commitées` | commiter puis relancer `predict` |

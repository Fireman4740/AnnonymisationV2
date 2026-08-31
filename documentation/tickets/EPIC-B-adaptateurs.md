# ÉPIC B — Adaptateurs de corpus

**Objectif** : les 6 corpus locaux sont normalisés au format SPEC-02 et validés.

**Effort** : ~5 jours · **Dépend de** : A-1, A-2, A-5.

Ordre imposé : chaque ticket n'introduit **qu'une** difficulté nouvelle.
Commencer par TAB ou RAT-Bench ferait affronter simultanément le format, la
taxonomie, la coréférence et le risque.

**Règle commune à tous les tickets de cet épic** : l'adaptateur s'auto-enregistre
via `@register` dans son propre module et **ne modifie pas** `__init__.py`.
Il ne filtre ni ne corrige silencieusement : une donnée source aberrante remonte
telle quelle et est rejetée par la validation, avec son `doc_id`.

---

## B-1 — Adaptateur `quasifr` (corpus QI français)

| | |
|---|---|
| **Priorité** | **P0 — premier adaptateur, sert de patron** |
| **Dépend de** | A-2, A-5 |
| **Fiche** | [`quasifr.md`](../datasets/quasifr.md) |
| **Difficulté nouvelle** | La chaîne complète, sur un cas simple |
| **Effort** | 0,5 j |

### Source

`F:\IA\Anonymisation\eval\datasets\data\{anonymization,hard_quasi_id,max_anonymization}_dataset.json`
— **72 exemples au total** (31 + 40 + 1), 212 Ko.

Format : objet JSON avec une clé `examples`. Chaque exemple :
`id`, `langue`, `original_text`, `annotations[]` avec
`type`, `start`, `end`, `text`, `replacement`, `coref_id`, `risk_note`.

### Pourquoi ce corpus en premier

C'est le plus petit, et c'est la **seule source de QI annotés en français**,
avec offsets réels, coréférence et justification du risque. Le champ
`replacement` fournit en prime une vérité terrain de généralisation.

### Périmètre

- `src/anonymisation/datasets/quasifr.py`
- `configs/datasets/quasifr.yaml`
- `tests/integration/test_quasifr.py`

### Mapping

| Source | Cible |
|--------|-------|
| `original_text` | `Document.text`, `domain="hr"` ou `generic`, `language="fr"` |
| `type` | `label_map` → codes SPEC-01 |
| `coref_id` | `Annotation.entity_id` |
| `risk_note` | `Annotation.meta.risk_note` |
| `replacement` | `Annotation.meta.gold_generalization` |

### Critères d'acceptation

- [ ] 72 documents chargés, répartis sur les 3 fichiers.
- [ ] `text[start:end] == span_text` sur **100 %** des annotations.
- [ ] Aucun type source non mappé (`E-MAP-001`).
- [ ] `anonv2 datasets validate quasifr` : aucune issue de sévérité `error`.
- [ ] Un test vérifie qu'un `coref_id` non nul produit bien un `entity_id`.

### Piège connu

72 exemples, c'est **très peu**. Un F1 calculé dessus a un intervalle de
confiance très large. Le manifeste doit porter
`default_metric_status: DIAGNOSTIC` et la fiche le dit déjà.

---

## B-2 — Adaptateur `personalreddit`

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | B-1 |
| **Fiche** | [`personalreddit.md`](../datasets/personalreddit.md) |
| **Difficulté nouvelle** | Profil latent, split par auteur, annotation sans offsets |
| **Effort** | 0,75 j |

### Source

`PersonalReddit/Reddit_synthetic/{train,test}.jsonl` — **318 + 207 lignes**.

Champs : `personality` (9 attributs), `feature`, `hardness`, `question_asked`,
`response`, `guess`, `guess_correctness`, `label`.

**Statut vérifié** : corpus **synthétique** (issu de `eth-sri/llmprivacy`, via
le dépôt RUPTA). `structure.synthetic: true` — la garde E2 de SPEC-08 ne s'y
applique pas.

### Périmètre

- `src/anonymisation/datasets/personalreddit.py`
- `configs/datasets/personalreddit.yaml`
- `tests/integration/test_personalreddit.py`

### Travail

1. `personality` → `Profile.attributes` (mapper les 9 attributs vers `GEN_AGE`,
   `GEN_GENDER`, `GEN_GEO`, `GEN_EDUCATION`, `GEN_OCCUPATION`, `GEN_SOCIOECON`,
   `GEN_FAMILY`).
2. `response` → `Document`, `domain="forum"`, `language="en"`.
3. `hardness` → `Document.meta.difficulty`.
4. Les attributs inférables **n'ont pas d'offsets** : produire des `Annotation`
   avec `start=end=span_text=None` et `expression_mode=IMPLICIT`. C'est le cas
   légitime prévu par l'invariant I-ANN-2 — le premier corpus à l'exercer.
5. `guess` / `guess_correctness` → `Document.meta.baseline_attack` : c'est une
   **baseline d'attaquant déjà mesurée**, réutilisable comme point de
   comparaison pour l'attaquant A (SPEC-08).

### Critères d'acceptation

- [ ] Chaque `Document` a un `author_id` résolvant vers un `Profile`.
- [ ] `split_by: person_id` dans le manifeste, et **aucun `person_id` présent
      dans deux splits** (`E-VAL-108`).
- [ ] Au moins une annotation sans offsets est produite et validée.
- [ ] Les 9 attributs sont mappés, aucun orphelin.

### Piège connu

Un split par document produirait une fuite massive : les messages d'un même
auteur partagent le profil latent, donc les QI. Le manifeste doit l'interdire
(contrôle de A-1) et `E-VAL-108` doit le confirmer.

---

## B-3 — Adaptateur `tab` (corpus officiel)

| | |
|---|---|
| **Priorité** | **P0 — le corpus de référence du projet** |
| **Dépend de** | B-2 |
| **Fiche** | [`tab.md`](../datasets/tab.md) |
| **Difficulté nouvelle** | Coréférence, multi-annotateurs, texte réel |
| **Effort** | 1,5 j |

### Source

`TAB/official/echr_{train,dev,test}.json` — **127 documents en dev**, 82 Mo.
Le répertoire contient aussi `evaluation.py`, le **script d'évaluation
officiel** (voir D-3).

Format vérifié — chaque document :
```
doc_id, text, task, dataset_type, quality_checked, meta,
annotations: { "annotator1": { "entity_mentions": [ ... ] }, "annotator10": {...} }
```
Chaque mention :
```
entity_type, entity_mention_id, start_offset, end_offset, span_text,
edit_type, identifier_type (DIRECT|QUASI|...), entity_id, confidential_status
```

C'est le corpus le plus riche de la batterie : il porte **nativement**
`identifier_type`, `entity_id` (coréférence) et `confidential_status`.

### Périmètre

- `src/anonymisation/datasets/tab.py`
- `configs/datasets/tab.yaml` (le `label_map` amorcé est à compléter)
- `tests/integration/test_tab.py`

### Travail

1. **N'utiliser que `TAB/official/`.** Le cache `TAB/*.jsonl` de la v1 est
   marqué `converted_no_offsets` / `tab_legacy_proxy` par l'audit : ses spans
   sont reconstruits par recherche textuelle. Les résultats issus de ce cache ne
   sont pas des résultats TAB.
2. Mapper `identifier_type` source directement vers l'enum SPEC-01.
3. Mapper `entity_type` (`PERSON`, `CODE`, `LOC`, `ORG`, `DEM`, `DATETIME`,
   `QUANTITY`, `MISC`) via `label_map`.
4. `entity_id` → `Annotation.entity_id` (indispensable au rappel entity-level).
5. `confidential_status` → `Annotation.sensitivity` (ou `meta` si le mapping
   n'est pas 1:1 — le documenter).
6. **Règle d'agrégation multi-annotateurs**, paramétrable dans le manifeste :
   `union` (défaut, privacy-first) · `majority` · `annotator:<id>`.

### Critères d'acceptation

- [ ] Les volumétries officielles sont chargées (127 en dev ; relever et figer
      train et test).
- [ ] `text[start:end] == span_text` sur **100 %** des mentions.
- [ ] Aucun `entity_type` non mappé.
- [ ] Les clusters de coréférence sont préservés : un test montre que le rappel
      entity-level **diffère** du rappel span-level (sinon la coréférence est
      ignorée).
- [ ] Les trois modes d'agrégation produisent des comptes différents et
      documentés.

### Pièges connus

- La règle d'agrégation **change les chiffres**. Toute mesure publiée doit la
  préciser. Le défaut `union` est un choix privacy-first assumé : tout ce qu'un
  annotateur a jugé identifiant l'est.
- Les personnes citées sont **réelles** : garde E2 de SPEC-08. Aucune sortie
  d'attaquant sur TAB ne doit être journalisée ni publiée.

---

## B-4 — Adaptateurs `supporttickets` et `bitextsupport`

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | B-1 |
| **Fiche** | [`supporttickets.md`](../datasets/supporttickets.md) |
| **Difficulté nouvelle** | Parquet, multilinguisme, tâches d'utilité |
| **Effort** | 0,75 j |

### Sources

- `SupportTicketsReal/train.parquet` — **61 765 tickets**, 16 colonnes :
  `subject`, `body`, `answer`, `type`, `queue`, `priority`, `language`,
  `version`, `tag_1..8`.
- `BitextSupportSynthetic/train.parquet` — **26 872 lignes** : `flags`,
  `instruction`, `category`, `intent`, `response`.

### Pourquoi c'est important

C'est le **seul corpus du domaine support**, il est **réel** et **multilingue**,
et surtout la colonne `queue` fournit la **tâche d'utilité de référence du
projet** : le routage (SPEC-07 §6.B). C'est la tâche qui souffre le plus de
l'anonymisation — masquer le produit et la version détruit le routage — donc
c'est le meilleur révélateur du compromis privacy/utility.

### Périmètre

- `src/anonymisation/datasets/supporttickets.py`
- `src/anonymisation/datasets/bitextsupport.py`
- `configs/datasets/{supporttickets,bitextsupport}.yaml`
- `tests/integration/test_supporttickets.py`

### Travail

1. Lecture parquet en colonnes (pyarrow/pandas), sans charger inutilement.
2. `subject` + `body` → `Document.text` (documenter le choix de concaténation,
   séparateur inclus, car il décale tous les offsets).
3. `language` → `Document.language` ; produire les **comptes par langue**.
4. `queue`, `priority`, `type` → `tasks.jsonl` ; `intent`, `category` pour
   bitext.
5. `version` → conservé en `Document.meta`, et **détectable** comme
   `SUP_VERSION` par la couche `detect/` (déjà livrée).

### Critères d'acceptation

- [ ] 61 765 tickets chargés, comptes par langue produits.
- [ ] `tasks.jsonl` contient les étiquettes `queue` pour 100 % des documents.
- [ ] Le séparateur `subject`/`body` est documenté et testé (un test vérifie un
      offset après le point de jonction).
- [ ] Le manifeste porte `synthetic: false` et la garde E2 est activable.

### Piège connu

**Aucune annotation de spans.** Ce corpus ne peut pas produire de F1 de
détection : c'est un corpus d'**utilité** et de détection non supervisée. Toute
métrique de détection dessus serait vide de sens. Le manifeste doit le refléter.

---

## B-5 — Adaptateur `ratbench` et population PUMS

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | B-3 |
| **Fiche** | [`rat-bench.md`](../datasets/rat-bench.md) |
| **Difficulté nouvelle** | Population de référence, profils, `k` réel |
| **Effort** | 1,5 j |

### Sources

- `RAT-Bench/english.jsonl` — champs vérifiés : `id`, `profile`,
  `direct_identifiers`, `indirect_identifiers`, `features`, `difficulty`,
  `prompt`, `text`, `scenario`.
- `RAT-Bench/cache/pums_population.parquet` — **3 373 378 individus**, colonnes :
  `SERIALNO`, `state of residence`, **`PWGTP`**, `citizenship status`,
  `marital status`, `educational attainment`, `sex`, `employment status`,
  `occupation`, `race`.

### Pourquoi c'est la pièce maîtresse

C'est la **seule source de `k` réel** de tout le projet. PUMS est une vraie
population de référence, ce qui rend mesurables les métriques de niveau 3
(MAE-k, calibration) sans rien générer.

### Périmètre

- `src/anonymisation/datasets/ratbench.py`
- `src/anonymisation/risk/population.py` (chargeur de population)
- `configs/populations/ratbench-us.yaml`
- `configs/datasets/ratbench.yaml`
- `tests/integration/test_ratbench.py`

### Travail

1. `profile` → `Profile.attributes` ; `indirect_identifiers` (codes `CIT`,
   `DOB`, `MAR`, `SEX`, `ST`) → mapping vers SPEC-01.
2. `direct_identifiers` → annotations `DIR_*`, **localisées dans `text`** par
   recherche, avec vérification `text[start:end] == span_text`.
3. `difficulty` → `Document.meta.difficulty` (axe de reporting obligatoire).
4. Chargeur PUMS : lecture colonnes via pyarrow, calcul de `k` par
   regroupement sur les attributs de la combinaison.
5. Produire `combinations.jsonl` avec `k_true`, `risk_true`,
   `risk_model: prosecutor`, `source: dataset`.

### Critères d'acceptation

- [ ] `text[start:end] == span_text` sur 100 % des identifiants directs
      localisés ; les non localisables sont comptés et déclarés, pas ignorés.
- [ ] `k` calculé **en sommant `PWGTP`**, pas en comptant les lignes.
- [ ] Un test de sanité vérifie que `k` d'une combinaison de 3 QI est
      strictement inférieur au `k` de chacun de ses QI pris isolément.
- [ ] La lecture de PUMS ne charge pas les 3,37 M de lignes en mémoire d'un
      bloc (mesurer la RSS dans le test, ou lire par colonnes).
- [ ] `difficulty` est présent sur 100 % des documents.

### Piège connu — le plus coûteux du backlog

`PWGTP` est un **poids de sondage**. PUMS est un échantillon d'environ 1 % de la
population, chaque ligne représentant ~100 personnes. Compter les lignes au lieu
de sommer les poids **sous-estimerait `k` d'environ deux ordres de grandeur**,
donc surestimerait massivement le risque, et fausserait toute la calibration
ultérieure. À vérifier explicitement par un test.

---

## B-6 — Adaptateurs `dbbio` et `conll2003`

| | |
|---|---|
| **Priorité** | P1 |
| **Dépend de** | A-4, B-1 |
| **Fiches** | [`dbbio.md`](../datasets/dbbio.md), [`conll2003.md`](../datasets/conll2003.md) |
| **Effort** | 0,75 j |

### Sources

- `DB-bio/{train,val,test}.jsonl` — **1 938 train, 239 test**. Champs : `text`,
  `l1`/`l2`/`l3` (hiérarchie **ontologie DBpedia**, ex. `Agent` > `Artist` >
  `Photographer`), `wiki_name`, `word_count`, `label`, `people`.
- `cleanconll_cache/` — format BIO, utiliser `_bio.py` (ticket A-4).

### Travail

1. DB-bio : `people` est une **chaîne** (le nom), pas une liste d'offsets → les
   spans `DIR_NAME` doivent être localisés par recherche textuelle.
2. DB-bio : `l1`/`l2`/`l3` → `tasks.jsonl` (utilité aval, 3 granularités).
3. CoNLL : mapping `PER` → `DIR_NAME`, `LOC` → `GEN_GEO` (**QUASI**, pas
   DIRECT), `ORG` → `GEN_AFFILIATION`, `MISC` → `IGNORED`.

### Critères d'acceptation

- [ ] `text[start:end] == span_text` sur 100 % des spans des deux corpus.
- [ ] DB-bio : le taux de noms **non localisables** est compté et déclaré.
- [ ] CoNLL : les 4 types sont mappés, `MISC` explicitement vers `IGNORED`.
- [ ] Les deux manifestes portent `default_metric_status: DIAGNOSTIC`.

### Piège connu

Sur DB-bio, la localisation par recherche textuelle rate les formes fléchies,
les formes courtes et les pronoms. Le rappel sera structurellement imparfait —
c'est exactement la faiblesse que l'audit v1 relève sur la reconstruction de
spans. D'où le statut `DIAGNOSTIC` obligatoire : ces chiffres ne sont pas
comparables à la littérature.

Sur CoNLL : c'est un **contrôle NER**, pas un benchmark d'anonymisation. Ses
métriques ne doivent jamais remonter dans le score principal.

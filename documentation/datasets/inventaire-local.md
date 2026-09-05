# Inventaire des corpus disponibles localement

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date** | 2026-08-30 |

---

## 1. Constat

Le dépôt v1 (`F:\IA\Anonymisation`) contient déjà, sous `eval/datasets/`,
**l'intégralité des corpus nécessaires à un pipeline d'évaluation complet** —
y compris le corpus TAB officiel avec son script d'évaluation, et la population
de référence PUMS de RAT-Bench.

Conséquences directes :

1. **Aucun téléchargement n'est nécessaire** pour démarrer.
2. **L'accès PhysioNet / MIMIC-III est abandonné** — voir §4.
3. Le chemin critique de la roadmap raccourcit : le lot L2 (adaptateurs) et le
   lot L3 (populations) peuvent démarrer immédiatement.

## 2. Inventaire

Racine : `F:\IA\Anonymisation\eval\datasets\`

| Corpus | Chemin | Volume | Contenu vérifié |
|--------|--------|-------:|-----------------|
| **TAB officiel** | `TAB/official/echr_{train,dev,test}.json` + `evaluation.py` | 82 Mo | 127 documents en dev ; annotations par annotateur avec `entity_type`, `start_offset`, `end_offset`, `span_text`, **`identifier_type`** (DIRECT/QUASI), **`entity_id`** (coréférence), `confidential_status` |
| **RAT-Bench** | `RAT-Bench/english.jsonl` | 2,3 Go (avec cache) | `id`, `profile`, `direct_identifiers`, `indirect_identifiers`, `features`, **`difficulty`**, `text`, `scenario` |
| **PUMS** | `RAT-Bench/cache/pums_population.parquet` | — | **3 373 378 individus**, 10 attributs + poids `PWGTP` : state of residence, citizenship status, marital status, educational attainment, sex, employment status, occupation, race |
| **PersonalReddit** | `PersonalReddit/Reddit_synthetic/{train,test}.jsonl` | 2,3 Mo | **525 exemples synthétiques**, 40 profils latents ; `personality` (9 attributs), `feature`, **`hardness`** (1–5), `response`, `guess`, `guess_correctness` |
| **DB-bio** | `DB-bio/{train,val,test}.jsonl` | 20 Mo | `text`, `l1`/`l2`/`l3` (labels d'occupation hiérarchiques), `wiki_name`, `people` |
| **SupportTicketsReal** | `SupportTicketsReal/train.parquet` | 24 Mo | **61 765 tickets**, colonnes `subject`, `body`, `answer`, `type`, **`queue`**, `priority`, **`language`**, **`version`**, `tag_1..8` |
| **BitextSupportSynthetic** | `BitextSupportSynthetic/train.parquet` | 5,8 Mo | 26 872 échanges, `instruction`, `category`, **`intent`**, `response` |
| **CleanCoNLL / CoNLL-2003** | `cleanconll_cache/` | 13 Mo | Annotations NER de contrôle |
| **Corpus QI français** | `data/{anonymization,hard_quasi_id,max_anonymization}_dataset.json` | 212 Ko | Annotations `QUASI_ID` **en français**, avec `coref_id`, `replacement` et `risk_note` |

## 3. Ce que cet inventaire débloque

| Besoin | Corpus | Statut |
|--------|--------|--------|
| Annotation QI de référence, texte réel, avec coréférence | TAB officiel | ✅ **et métriques officielles disponibles** |
| Population de référence pour calculer un vrai `k` | PUMS (3,37 M individus) | ✅ |
| Risque de ré-identification avec difficulté contrôlée | RAT-Bench | ✅ |
| Domaine forums, inférence d'attributs, axe de difficulté | PersonalReddit | ✅ |
| **Domaine support, réel, multilingue** | SupportTicketsReal | ✅ |
| **Tâche d'utilité « routage »** (SPEC-07 §6.B) | colonne `queue` | ✅ |
| **QI en français** | corpus QI français | ✅ |
| Utilité aval (classification d'occupation) | DB-bio `l1/l2/l3` | ✅ |
| Contrôle NER | CleanCoNLL | ✅ |

Les deux tâches d'utilité de référence de SPEC-07 §6.B sont donc immédiatement
mesurables : **routage** via `SupportTicketsReal.queue`, et classification
d'intention via `BitextSupportSynthetic.intent`.

## 4. Abandon de PhysioNet / MIMIC-III

**Décision** : l'accès PhysioNet (formation CITI + DUA, plusieurs semaines) est
abandonné. La fiche [`ipi-mimic.md`](ipi-mimic.md) passe au statut « non retenu ».

Ce que fournissait IPI, et par quoi il est remplacé :

| Apport d'IPI | Remplacement |
|--------------|--------------|
| Taxonomie des identifiants indirects | Les **guidelines** d'IPI restent lisibles dans la publication, sans aucun accès aux données. La taxonomie SPEC-01 s'en inspire — seule la table de réconciliation §9 reste ouverte, et elle ne nécessite pas MIMIC-III. |
| Annotation QI sur texte réel | **TAB officiel**, qui est plus riche (coréférence, `identifier_type`, `confidential_status`) et déjà disponible |
| Stress-test cross-domaine clinique | **MEDDOCAN** (espagnol, licence ouverte Zenodo, sans démarche) |
| Ancrage sur un domaine non-RH | **DB-bio** (biographies) et **CleanCoNLL** |

Aucune capacité du projet n'est perdue. Le chemin critique est raccourci de
plusieurs semaines, et tous les résultats deviennent reproductibles par un tiers
— ce qui n'aurait jamais été le cas avec MIMIC-III, dont la redistribution est
interdite.

## 5. Politique de copie

Les corpus **ne sont pas copiés** dans ce dépôt (règle L1 de SPEC-09 : aucune
donnée versionnée). Chaque manifeste `configs/datasets/*.yaml` déclare :

```yaml
source:
  kind: local
  path: "F:/IA/Anonymisation/eval/datasets/<corpus>"
  # ou, en variable d'environnement pour la portabilité :
  path_env: "ANONV2_V1_DATASETS"
```

Le pipeline lit la source en place et écrit la forme normalisée dans
`data/processed/<clé>/`, qui n'est pas versionné non plus. Un checksum de la
source est calculé et figé dans le manifeste à la première ingestion.

> **Portabilité** : le chemin absolu vers la v1 doit être surchargeable par la
> variable d'environnement `ANONV2_V1_DATASETS`. Sans cela, le dépôt ne
> fonctionnerait que sur cette machine.

## 6. Points de vigilance

| Corpus | Vigilance |
|--------|-----------|
| **TAB** | Le cache `TAB/*.jsonl` de la v1 est marqué `converted_no_offsets` / `tab_legacy_proxy` par l'audit : les spans y sont reconstruits par recherche textuelle. **N'utiliser que `TAB/official/echr_*.json`**, qui porte les offsets réels. Les résultats issus du cache legacy ne sont pas des résultats TAB. |
| **RAT-Bench** | 2,3 Go dont l'essentiel est le cache PUMS. Charger PUMS en colonnes (pyarrow), jamais intégralement en mémoire naïvement. |
| **PUMS** | La colonne `PWGTP` est un **poids de sondage** : `k` doit être calculé en sommant les poids, pas en comptant les lignes. Ignorer ce point sous-estimerait `k` d'un facteur ~100. |
| **SupportTicketsReal** | Tickets **réels** → personnes réelles. Garde E2 de SPEC-08 : l'attaquant avec recherche web y est interdit, et aucune sortie d'attaquant ne doit être journalisée. |
| **PersonalReddit** | Le cache local est la release synthétique ETH SRI ; il ne contient pas les 520 profils Reddit réels de l'article. Licence des exemples : CC BY-NC-SA 4.0 ; garde E2 non applicable. |
| **DB-bio** | Personnes réelles (biographies Wikipedia) → même garde E2. |

## 7. Conséquence sur la priorisation

La table de priorité de [`README.md §1`](README.md) devient :

| Dataset | Priorité | Justification |
|---------|---------:|---------------|
| `tab` | **P0** | Disponible, officiel, avec métriques |
| `ratbench` + PUMS | **P0** | Disponible, seule source de `k` réel |
| `supporttickets` | **P0** | Domaine support réel + tâche d'utilité |
| `quasifr` | **P0** | Seule source de QI annotés en français |
| `personalreddit` | **P0** | Domaine forums + axe de difficulté |
| `dbbio` | P1 | Utilité aval |
| `conll2003` | P1 | Contrôle NER |
| `bitextsupport` | P1 | Tâche d'utilité secondaire |
| `openpii` | P1 | Téléchargement requis ; utile pour le F1 par langue |
| `meddocan` | P2 | Téléchargement requis ; cross-domaine |
| `synthpai` | P2 | Téléchargement requis ; **redondant avec PersonalReddit** à court terme |
| `jobstack` | P2 | Accès sur demande — abandonné sauf besoin avéré |
| `ipi` | ❌ | **Non retenu** (§4) |
| `hr_qi`, `support_qi`, `forum_qi` | **P0** | Corpus générés — inchangé, c'est la contribution |

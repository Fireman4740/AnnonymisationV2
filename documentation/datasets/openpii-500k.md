# OpenPII 500k — AI4Privacy

| | |
|---|---|
| **Clé interne** | `openpii` |
| **Priorité** | **P0** |
| **Benchmark** | B1 (PII Detection) |
| **Statut de la fiche** | Stable · v1.1 · 2026-09-01 — adaptateur livré (ÉPIC B) |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom | `ai4privacy/open-pii-masking-500k-ai4privacy` |
| Référence | [@ai4privacy2024openpii] |
| Type | **Synthétique** |
| Langues | **8**, dont le **français** (112 136 exemples FR mesurés) |
| Classes | **20 classes PII** |
| Volume | **580 227** exemples (464 150 train + 116 077 validation) |
| Domaine | Généraliste |

## 2. Rôle et priorité

**La couche PII multilingue du projet.** C'est le dataset qui permet de traiter
correctement la partie « identifiants directs » — noms, emails, téléphones,
adresses, identifiants divers — et surtout de le faire **en français**, ce
qu'aucun autre corpus P0 ne permet.

C'est aussi le **premier adaptateur à implémenter** : le plus simple, il valide
la chaîne d'ingestion complète sur un cas facile avant d'attaquer TAB et
RAT-Bench.

## 3. Contenu et volumétrie

| | |
|---|---|
| Exemples | **580 227** (464 150 train + 116 077 validation) |
| Langues | 8 |
| Français | **112 136** exemples (19,3 % du corpus) |
| Classes PII | 20 |
| Taille disque brut | 676 Mo (565 790 080 B train + 141 836 910 B validation) |

Volumétrie par langue, **figée** dans le manifeste
(`structure.per_language_counts`) après comptage ligne à ligne de la release
épinglée :

| Langue | Exemples |
|--------|---------:|
| en | 150 693 |
| fr | 112 136 |
| de | 82 384 |
| es | 78 013 |
| it | 68 824 |
| hi | 33 963 |
| te | 27 586 |
| nl | 26 628 |

## 4. Structure brute

Format Hugging Face JSONL, une ligne = un exemple, à la révision épinglée.
**Schéma exact** :

| Champ | Type | Rôle |
|-------|------|------|
| `source_text` | str | texte source |
| `masked_text` | str | texte masqué, spans → `[LABEL_index]` |
| `privacy_mask` | list | `[{label, start, end, value, label_index}]` — offsets **caractères de `source_text`** |
| `split` | str | « train » / « validation » — source de vérité du split |
| `uid` | int | unique sur tout le corpus → `doc_id = "openpii:{uid}"` |
| `language` | str | ISO 639-1 minimal |
| `region` | str | 2 lettres |
| `script` | str | ISO 15924 (parfois inexact pour te/hi, carte HF) |
| `mbert_tokens` / `mbert_token_classes` | lists | artefacts de tokenisation — ignorés |

Résolution des trois points à vérifier :

1. **Offsets** : caractères du `source_text` — `text[start:end] == value`
   vérifié sur 100 % des 1 374 912 entités (validateur, E-VAL-101 : 0 faute).
2. **Alignement du texte masqué** : non caractéristique (les placeholders
   `[LABEL_index]` n'ont pas la longueur des spans), mais **reconstructible**
   depuis `source_text` + `privacy_mask` (0 divergence). Décision :
   `masked_text` **n'est pas dupliqué** dans le pivot — voir §10.
3. **Classes entre langues** : les **20 classes sont présentes dans les 8
   langues** (20/20 chacune) — labelset homogène, macro-F1 par langue
   possible sans classe absente.

## 5. Accès et acquisition

| | |
|---|---|
| Source | `huggingface.co/datasets/ai4privacy/open-pii-masking-500k-ai4privacy` |
| Méthode | `anonv2 datasets download openpii` → `OpenpiiAdapter.download()` — `urllib` stdlib sur le `resolve/<révision>/…` du dépôt (sans librairie HF) ; écriture tmp + rename atomique ; contrôle sha256 ; rapport `.acquisition.json` |
| Révision épinglée | `506996d625ed970a0063432daf6007cf4a3a48e3` (branche `main` au téléchargement du 2026-09-01) |
| Prérequis | Aucun : dépôt non gated, stockage XET, téléchargement direct (~51 s) |
| Cache local | `data/raw/openpii/{train,validation}.jsonl` — sha256 agrégat figé dans le manifeste (`integrity.sha256`) |

## 6. Licence et conformité

- Données **synthétiques** (Llama-3.1-8B-Instruct) → aucune contrainte RGPD
  sur des personnes réelles ; L5 (corpus interne) ne s'applique pas.
- **Licence relevée sur la carte de la révision épinglée** : *Llama Community
  License (3.1 et 3.3)* (fichiers `llama-3.1-community-license.txt` et
  `llama-3.3-community-license.txt` dans le dépôt). La mention `license_name:
  cc-by-4.0` du frontmatter est un vestige de gabarit **contredit par le corps
  de la carte**, qui fait foi.
- La Llama Community License **n'a pas d'identifiant SPDX** →
  `license.spdx = UNKNOWN` ; redistribuable sous conditions (attribution) →
  `redistribution = true` ; pas d'agrément type DUA (téléchargement libre) →
  `restricted = false`.
- Conséquence (L2/G3) : le statut **OFFICIAL est exclu** ; l'ingestion porte
  le statut **`diagnostic`** (cf. lock). À clarifier avec AI4Privacy avant
  toute publication officielle.
- La révision HF est épinglée par **commit hash** dans le manifeste
  (`source.revision`), jamais par nom de dataset.

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs | ✅ |
| **QI indirects** | ❌ |
| QI implicites | ❌ |
| Combinaisons | ❌ |
| Profil latent | ❌ |
| Population de référence | ❌ |
| **Multilingue** | ✅ |
| **Français** | ✅ |
| Domaine RH/support/forum | ❌ |
| Texte réel | ❌ |

## 8. Apport pour le projet

1. **La seule couverture française P0** pour la détection d'identifiants
   directs.
2. Volume suffisant pour **entraîner ou fine-tuner** un détecteur (GLiNER,
   XLM-R), contrairement à TAB ou IPI.
3. Permet de publier un **F1 par langue** sur la partie PII, qui est le
   prérequis de crédibilité avant de parler de QI.
4. Baseline de comparaison avec Presidio (B1 de
   [02-etat-de-l-art §14](../rapport/02-etat-de-l-art.md)).

## 9. Limites et pièges

> ⚠️ **OpenPII ≠ benchmark de QI indirects.**

C'est l'avertissement le plus important de la fiche. Un modèle peut obtenir un
F1 excellent sur OpenPII et échouer complètement sur :

> « je suis le seul doctorant de mon équipe à travailler sur ce sujet »

RAT-Bench [@krco2026ratbench] confirme explicitement ce décalage : de bonnes
performances sur des PII synthétiques ne garantissent en rien une protection
contre la ré-identification par combinaison d'attributs.

| Limite | Conséquence |
|--------|-------------|
| Aucun QI indirect | Ne mesure aucune des questions 2, 3, 4 du cadrage. |
| Synthétique | Formulations régulières, peu de bruit, peu d'implicite. Le F1 y est structurellement surestimé. |
| Généraliste | Aucun signal RH / support / forum. |
| Risque de sur-optimisation | Un modèle entraîné uniquement dessus apprendra des motifs de surface. Toujours l'évaluer aussi sur MultiCoNER II (bruité) et TAB (réel). |

**Règle de communication** : ne jamais présenter un score OpenPII comme un
résultat du projet. Il n'est qu'un contrôle de bon fonctionnement de la couche
basse.

## 10. Mapping vers le schéma interne

| Objet OpenPII | Objet interne | Notes |
|---------------|---------------|-------|
| exemple | `Document` | `doc_id = "openpii:{uid}"`, `domain = GENERIC`, `language` de la ligne, `meta = {uid, region, script}` |
| entité PII | `Annotation` | `annotation_id = "openpii:{uid}:a{i}"` (i = position dans la ligne) ; offsets **tels quels** — la cohérence est contrôlée par le validateur, jamais corrigée |
| classe PII (20) | `Annotation.qi_categories` | via `label_map` vers SPEC-01 : 12 `DIRECT` (noms, email, téléphone, adresse, carte bancaire, n° d'identité) + 8 `QUASI` (AGE, GENDER, SEX, CITY, ZIPCODE, DATE, TIME, TITLE) |
| texte masqué | — | **non stocké** : reconstructible depuis `source_text` + `privacy_mask` (0 divergence) — pas de duplication dans le pivot |
| `mbert_*` | — | ignorés (artefacts de tokenisation) |

> **Décision de mapping non triviale** : 8 des 20 classes OpenPII ne sont pas
> des identifiants directs (âge, genre/sex, ville, code postal, date, heure,
> civilités/titres). Les classer mécaniquement en `DIRECT` fausserait le DILR
> ([SPEC-07 §4](../specifications/SPEC-07-metriques.md)) — le `label_map`
> figé dans `configs/datasets/openpii.yaml` les mape en `QUASI`. `TITLE`
> couvre les civilités (Dr, Hr, श्रिमानी) **et** les titres professionnels ;
> les classes v1 `DATEOFBIRTH` / `JOBTITLE` n'existent pas dans cette release.

## 11. Splits et protocole

- Deux splits HF reprenus tels quels : **train** (464 150) et **validation**
  (116 077) — la release n'a pas de « test ».
- Toute métrique doit être produite **par langue** ; la moyenne toutes langues
  confondues est trompeuse (déséquilibre des volumes) — `datasets stats`
  reporte déjà `by_language`.
- Protocole `openpii-v1` (volumétrie + révision épinglées) ; le statut
  **OFFICIAL reste exclu** par la licence (spdx UNKNOWN) → statut de lock
  `diagnostic` (SPEC-09 L2/G3).

## 12. Plan d'implémentation de l'adaptateur

| # | Étape | Sortie |
|---|-------|--------|
| 1 | ✅ Charger, inspecter le schéma, compter par langue | note §4 + `structure.per_language_counts` |
| 2 | ✅ Épingler la révision HF (commit `506996d…`) | `configs/datasets/openpii.yaml` |
| 3 | ✅ Établir le `label_map` classe par classe (20 classes) | mapping documenté dans le YAML |
| 4 | ✅ Implémenter `OpenpiiAdapter` | `src/anonymisation/datasets/openpii.py` |
| 5 | ✅ Vérifier l'alignement des offsets sur le texte source | `tests/unit/test_openpii.py` + `datasets validate openpii` PASS (1 374 912 entités, 0 faute) |
| 6 | ⏳ Produire les métriques B1 par langue | rapport (travail d'évaluation, hors adaptateur) |
| 7 | ⏳ Comparer à la baseline Presidio | rapport (idem) |

**Cet adaptateur est le premier à écrire.** Il sert de patron aux autres et
valide `DatasetAdapter`, le registre, le manifeste et la validation.

## 13. Critères d'acceptation

- [x] Chargement complet sans erreur, volumétrie conforme au manifeste.
  (ingestion du 2026-09-01 : 580 227 documents, 1 374 912 annotations ;
  `by_language` de `datasets stats` = `per_language_counts` du manifeste)
- [x] `text[start:end] == span_text` pour 100 % des annotations, toutes
  langues. (`datasets validate openpii` : PASS, 0 faute E-VAL-101 sur
  1 374 912 entités)
- [x] Les 20 classes sont mappées explicitement ; aucune classe par défaut.
  (`label_map` du manifeste : 20/20, G4)
- [x] Le comptage par langue est produit et stocké dans le manifeste.
  (`structure.per_language_counts`)
- [x] Le français représente bien > 100 000 exemples (contrôle de l'annonce).
  (112 136 FR mesurés)
- [ ] Une baseline Presidio tourne de bout en bout sur ce dataset.
  (reste à faire — travail d'évaluation B1, pas de l'adaptateur)

## 14. Questions ouvertes

- **Licence exacte de la révision retenue** : Llama Community License
  (3.1 et 3.3) — voir §6. Conséquence : spdx UNKNOWN, statut `diagnostic`.
- **Homogénéité des classes entre langues** : les 20 classes sont présentes
  dans les **8 langues** (20/20 chacune, relevé ligne à ligne) — aucune classe
  absente, pas d'impact sur le macro-F1 par langue.
- **Proportion de classes `QUASI`** : tranchée — **8 des 20** (AGE, GENDER,
  SEX, CITY, ZIPCODE, DATE, TIME, TITLE) mappées `QUASI`, 12 `DIRECT` ;
  figé dans le manifeste.

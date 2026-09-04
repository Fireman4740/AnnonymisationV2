# PersonalReddit

| | |
|---|---|
| **Clé interne** | `personalreddit` |
| **Priorité** | **P0** |
| **Benchmark** | B2 |
| **Statut de la fiche** | Stable · v1.1 · 2026-09-04 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
 Nom complet | PersonalReddit — **synthetic examples** for personal-attribute inference
 Référence | ETH SRI, *Beyond Memorization: Violating Privacy via Inference with Large Language Models* (`staab2024beyond`). La release est publiée dans `https://github.com/eth-sri/llmprivacy/tree/main/data/synthetic` ; le PersonalReddit réel de l'article n'est pas distribué.
 Type | **Synthétique** — exemples générés à partir de profils synthétiques
 Langue | Anglais
 Domaine | **Forums** (style Reddit synthétique)
 Source | Copie locale de la release publique ETH SRI, séparée des données Reddit réelles

## 2. Décision de statut et rôle

**Décision G-6 : le cache local est synthétique.** Il ne s'agit pas des 520 profils
Reddit réels utilisés dans l'étude ICLR. La preuve est convergente :

1. le README local décrit explicitement des « commentaires Reddit synthétiques » et
   pointe vers `eth-sri/llmprivacy/data/synthetic` ;
2. le dépôt ETH SRI indique que le PersonalReddit original n'est pas publié pour
   des raisons de vie privée, mais publie séparément des exemples synthétiques ;
3. les 318 lignes de `train.jsonl` et 207 lignes de `test.jsonl` totalisent 525
   exemples et correspondent, après retrait du champ local `label`, aux 525 lignes
   de `synthetic_dataset.jsonl` publié par ETH SRI ;
4. l'inspection locale trouve 40 profils latents, sans identifiant réel ni nom
   d'utilisateur Reddit.

Le corpus est donc admissible pour un benchmark contrôlé d'inférence d'attributs,
mais **ne constitue pas une validation de l'anonymisation de personnes réelles**.
Il reste prioritaire pour l'axe forums grâce à son profil latent et à sa difficulté
explicite (`hardness`).

La licence des exemples publiés est **CC BY-NC-SA 4.0**. La licence MIT du dépôt
ETH SRI couvre le code, pas automatiquement les exemples ; le manifeste porte
donc la licence des données et interdit d'en déduire un droit d'usage commercial.

## 3. Contenu et volumétrie

| Métrique | Valeur |
|----------|--------|
| Fichier source `train.jsonl` | **318 lignes** |
| Fichier source `test.jsonl` | **207 lignes** |
| Total source | **525 lignes** |
| Split pivot `train` (person_id) | **305 documents / 23 profils** |
| Split pivot `test` (person_id) | **220 documents / 17 profils** |
| Profils latents distincts | **40** |
| Taille des deux splits | **~1,1 Mo** |
| Langue | Anglais |

Les 40 profils sont présents dans chacun des deux fichiers source. Le pivot
reconstruit donc un split auteur-disjoint par `blake2b(f"{seed}:{person_id}")`,
seed **42**, ratios **60/40** ; `source_split` reste dans `Document.meta`.

### Attributs personnels (dans `personality`)

| Attribut | Type | Rôle |
|----------|------|------|
| `age` | numérique ou tranche | GEN_AGE |
| `sex` | catégoriel | GEN_GENDER |
| `city_country` | chaîne | GEN_GEO (lieu actuel) |
| `birth_city_country` | chaîne | GEN_GEO (lieu de naissance) |
| `education` | chaîne | GEN_EDUCATION |
| `occupation` | chaîne | GEN_OCCUPATION |
| `income` | numérique ou chaîne | GEN_SOCIOECON |
| `income_level` | ordinal | GEN_SOCIOECON (grainage) |
| `relationship_status` | catégoriel | GEN_FAMILY |

### Colonnes principales

| Colonne | Type | Contenu |
|---------|------|---------|
| `personality` | `object` | Les 9 attributs latents (voir tableau §3.1) |
| `feature` | `str` | Attribut ciblé ; 8 valeurs observées, `income` n'est pas ciblé |
| `hardness` | `int` | Difficulté observée, exactement de 1 à 5 |
| `question_asked` | `str` | Question présentée au sujet synthétique |
| `response` | `str` | Texte synthétique de la réponse |
| `guess` | `str` | Justification et hypothèse de l'attaquant externe |
| `guess_correctness` | `object` | Scores d'évaluation des hypothèses externes |
| `label` | `str` | Champ présent dans les splits locaux ; absent de la release ETH SRI comparée |

## 4. Structure brute et preuve de provenance

La release ETH SRI contient une ligne par réponse et un profil synthétique
(`personality`) répété sur les lignes d'un même auteur latent. Aucun `person_id`
source n'est fourni : un adaptateur doit dériver un identifiant stable du JSON
canonique de `personality`, sans tenter d'inférer une identité réelle.

La comparaison locale est déterministe : l'union des lignes locales, normalisée
en retirant seulement `label` (champ ajouté par la copie locale), est égale à la
release `data/synthetic/synthetic_dataset.jsonl` d'ETH SRI. Le fichier amont est
identifié dans l'API GitHub par le blob `49b4b7927f8d039eacf5dd48d2545ee5555ef9b1`.

La contradiction avec le PersonalReddit réel est ainsi résolue : les **520 profils
réels** de l'article ne sont pas présents dans le cache et ne doivent pas être
déduits des **525 exemples** synthétiques.

## 5. Accès et acquisition

| | |
|---|---|
| Source | Dépôt V1 local : `F:\\IA\\Anonymisation\\eval\\datasets\\PersonalReddit\\Reddit_synthetic\\` |
| Source publique de référence | `eth-sri/llmprivacy/data/synthetic/synthetic_dataset.jsonl` |
| Fichiers locaux | `train.jsonl`, `test.jsonl` |
| Méthode | Lecture JSONL ligne par ligne |
| Prérequis | Aucun accès réseau ; définir `ANONV2_V1_DATASETS` |
| Empreinte locale | `c2db554a096afdd8eac42e32438d65d5d3efdeb519a24092656ab2382c8c671c` |

## 6. Licence et conformité

- **Synthétique confirmé** : les exemples et profils sont générés ; ils ne sont
  pas le corpus Reddit réel de l'article.
- **Garde E2 de SPEC-08 non applicable** au cache synthétique : l'attaquant avec
  recherche web peut être activé, sous réserve de la politique d'expérience.
- **Aucune conclusion RGPD sur des personnes réelles** ne peut être tirée de ce
  corpus ; cette décision ne s'étend pas au PersonalReddit original non distribué.
- Licence des exemples : **CC BY-NC-SA 4.0**. Le dépôt ETH SRI est sous MIT pour
  son code ; ces deux périmètres ne doivent pas être confondus.

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs | ❌ (profils synthétiques, anonymes) |
| QI indirects | ✅ |
| QI implicites | ✅ |
| Profil latent | ✅ |
| Multi-documents par personne | ✅ |
| **Axe de difficulté explicite** | ✅ |
| **Baseline d'attaquant** | ✅ |
| Population de référence | ❌ |
| Attaquant | ✅ (external guess fourni) |
| Multilingue | ❌ (anglais) |
| Domaine forums | ✅ |
| Texte réel | ❌ (synthétique) |

## 8. Apport pour le projet

1. **Le domaine forums**, et une alternative ou supplément à SynthPAI avec un texte
   plus réaliste.
2. **L'axe de difficulté explicite** (`hardness`), qui permet de mesurer comment le
   risque se dégrade avec la difficulté — un axe d'évaluation central (SPEC-01 §3.2,
   SPEC-03 §4).
3. **Une baseline d'attaquant externe** (`guess`, `guess_correctness`) : permet de
   comparer notre attaquant A (SPEC-08) contre une attaquant externe déjà mesuré —
   benchmark externe inestimable.
4. **Multi-documents par auteur**, qui permet d'évaluer l'agrégation (author-level
   risk) — case absent de SupportTicketsReal et corpus purement annoté.
5. **Nine semantic attributes** déjà mappables vers SPEC-01, sans travail de mapping
   taxinomique.

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| **Petit corpus (525 lignes, 40 profils)** | Corpus d'évaluation contrôlée et de mise au point ; incertitude élevée. |
| Synthétique | Les résultats ne garantissent rien sur la protection de personnes réelles. |
| Pas d'annotations de spans | Aucune F1 de détection ; inférence au niveau document uniquement. |
| Anglais uniquement | Aucune mesure FR. |
| **Train/test partagent les 40 profils** | Les fichiers source ne sont pas utilisables comme split auteur-disjoint ; reconstruire un split par groupe. |
| Pas de population de référence | Le calcul de $k$ nécessite une population externe. |
| `hardness` observé de 1 à 5 | La release expose l'échelle, mais sa sémantique exacte reste celle de la source. |

> Le statut synthétique autorise la publication d'exemples dans les limites de la
> CC BY-NC-SA 4.0. Il ne faut pas présenter ces résultats comme un benchmark
> d'anonymisation opérationnelle sur Reddit réel.

## 10. Mapping vers le schéma interne

| Objet PersonalReddit | Objet interne | Mapping |
|----------------------|---------------|---------|
| ligne (réponse) | `Document` | `domain = "forum"`, `language = "en"`, `author_id` et `subject_ids` dérivés de `personality` |
| `response` | `Document.text` | Texte brut du message |
| `personality` | `Profile.attributes` | 9 attributs → 7 clés SPEC-01 ; les collisions `GEN_GEO` et `GEN_SOCIOECON` regroupent les deux valeurs sans perte |
| `hardness` | `Document.meta.hardness` | Entier validé dans [1, 5] |
| `feature` | `tasks.jsonl` + annotation | `task = "personality_prediction"`, `label = feature_value`, annotation `IMPLICIT` sans offset |
| `guess` / `guess_correctness` | baseline attaquant | Conservés dans `Document.meta` et `TaskLabel.meta` |

### Sous-tableau : mapping des attributs

| Attribut `personality` | Code SPEC-01 | Notes |
|------------------------|--------------|-------|
| `age` | `GEN_AGE` | numérique ou tranches |
| `sex` | `GEN_GENDER` | — |
| `city_country` | `GEN_GEO` | Lieu actuel |
| `birth_city_country` | `GEN_GEO` | Lieu de naissance (variante) |
| `education` | `GEN_EDUCATION` | — |
| `occupation` | `GEN_OCCUPATION` | — |
| `income` | `GEN_SOCIOECON` | Numérique |
| `income_level` | `GEN_SOCIOECON` | Ordinal (grainage) |
| `relationship_status` | `GEN_FAMILY` | — |

## 11. Splits et protocole

- Les fichiers source restent `train.jsonl` et `test.jsonl`, mais ne sont pas les
  splits d'évaluation.
- Le pivot produit `train = 305 documents / 23 profils` et `test = 220 / 17`.
- La séparation est groupée par `person_id`, avec `seed = 42`, ratios `train=0,6`
  et `test=0,4`, via l'algorithme blake2b de SPEC-04 §9.
- Aucun `person_id` ne figure dans les deux splits pivot (E-VAL-108 : aucune
  erreur). La provenance du fichier reste dans `meta.source_split`.
- Les deux granularités restent pertinentes : réponse unique
  (`document-level`) et union des réponses d'un profil (`author-level`).

## 12. Plan d'implémentation de l'adaptateur

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Charger les deux JSONL et vérifier le schéma réel | ✅ 525 lignes, 40 profils, stats §3 et §4 |
| 2 | Confirmer le statut synthétique et la licence | ✅ décision G-6 + manifeste |
| 3 | Dériver les 40 `person_id` par hash canonique de `personality` | ✅ profils stables |
| 4 | Refuser la confusion entre fichiers source et split auteur-disjoint | ✅ re-split pivot + provenance conservée |
| 5 | Fixer splits, checksum, volumétrie et statut | ✅ manifeste v1.1 |
| 6 | Implémenter `PersonalRedditAdapter` | ✅ `src/anonymisation/datasets/personalreddit.py` |
| 7 | Émettre `profiles.jsonl`, `documents.jsonl` et `tasks.jsonl` | ✅ ingestion officielle publiée |
| 8 | Implémenter l'agrégation author-level sur un split groupé | ☐ métriques d'agrégation encore à écrire |
| 9 | Comparer la baseline `guess` sans exposer de données réelles | ☐ protocole de comparaison à figer |

## 13. Critères d'acceptation de l'adaptateur

- [x] Tous les documents et profils sont chargés avec `domain = "forum"`,
      `language = "en"` — validation officielle : 525/40.
- [x] `person_id` est dérivé de façon stable pour chaque profil latent.
- [x] Les 9 attributs de `personality` sont mappés sans orphelin ; les deux
      collisions de code sont regroupées dans les valeurs structurées.
- [x] Un split d'évaluation auteur-disjoint est reconstruit avant la mesure
      author-level ; E-VAL-108 ne signale aucune fuite.
- [x] `hardness` est validé dans l'intervalle observé 1–5 pour chaque document.
- [ ] L'évaluation author-level est comparée à document-level sur le même split
      groupé — métriques à implémenter.
- [x] **Statut synthétique confirmé au manifeste** ; la garde E2 n'est pas
      applicable à ce cache.

## 14. Questions ouvertes

- La stratégie de split groupé est-elle suffisante pour les expériences finales ?
  — **Décidée pour cette release** : seed 42, ratios 60/40, mais une proportion
  finale différente reste possible pour une campagne ultérieure.
- La question `question_asked` ajoute-t-elle du signal ou est-elle déterministe
  depuis `feature` ?
- Existe-t-il une population de référence US/anglophone compatible avec le calcul
  de $k$ ?
- Le champ `guess` et `guess_correctness` provient-il d'un seul attaquant ou de
  plusieurs évaluateurs ?

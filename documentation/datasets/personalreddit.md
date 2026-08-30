# PersonalReddit

| | |
|---|---|
| **Clé interne** | `personalreddit` |
| **Priorité** | **P0** |
| **Benchmark** | B2 |
| **Statut de la fiche** | Stable · v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom complet | PersonalReddit — Inference of Personal Attributes from Reddit |
| Référence | ETH SRI (Vero, Vechev et al.), même famille que SynthPAI. Source : `https://github.com/eth-sri/llmprivacy` et `https://github.com/UKPLab/acl2025-rupta` |
| Type | **Synthétique** — commentaires et profils générés |
| Langue | Anglais |
| Domaine | **Forums** (style Reddit synthétique) |
| Source | Dépôt interne V1 |

## 2. Rôle et priorité

**Le benchmark forums de la batterie P0, remplaçant court terme de SynthPAI.**
Comme SynthPAI, c'est un corpus synthétique, mais construit différemment : profils
explicites + inférence de texte par des modèles. C'est la même famille de travaux
ETH SRI, avec une **structure explicite d'axe de difficulté** (`hardness`) qui
impacte directement le calcul de risque — une dimension rare et précieuse.

**Atout structurel décisif** :
1. **Profil latent** de 9 attributs personnels (`personality`), observable via un
   texte (`response`).
2. **Hardness explicite**, qui se mappe directement sur `Document.meta.difficulty`
   — une dimension de mesure rare dans les corpus existants.
3. **Baseline d'attaquant fournie** (`guess`, `guess_correctness`) — un point de
   comparaison externe pour l'attaquant de SPEC-08.
4. **Domaine forums** — indispensable pour couvrir le tiers forums du périmètre.

## 3. Contenu et volumétrie

| Métrique | Valeur |
|----------|--------|
| Split `train.jsonl` | **318 lignes** |
| Split `test.jsonl` | **207 lignes** |
| Total | **525 lignes** (petit corpus) |
| Taille disque totale | 3,0 Mo (JSONL) |
| Langue | Anglais |

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
| `feature` | `str` | Quel attribut est ciblé dans cette ligne |
| `hardness` | `int` | Axe de difficulté (valeurs : 1, 2, 3, … ?) |
| `question_asked` | `str` | La question posée au sujet |
| `response` | `str` | Le texte de réponse du sujet |
| `guess` | (type ?) | Prédiction externe de l'attribut target |
| `guess_correctness` | `bool` ou score | Exactitude de la prédiction |
| `label` | (type ?) | Valeur vraie de l'attribut |

## 4. Structure brute

**Deux niveaux** :

1. **Profil** : un enregistrement `personality` par personne (à confirmer comment les
   personnes sont identifiées — y a-t-il un `person_id` ?).
2. **Réponse** : un texte (`response`) par ligne, avec
   - `feature` (attribut visé),
   - `hardness` (difficulté de l'inférence),
   - `personality` (le profil de la personne),
   - des prédictions externes (`guess`, `guess_correctness`).

**Point délicat** : même ligne/texte peut cibler plusieurs attributs (`feature`),
ou plusieurs difficultés. À clarifier lors de la première inspection.

Structure similaire à SynthPAI, mais avec un axe de difficulté **explicite et
mesurable**, ce qui est rare et précieux.

## 5. Accès et acquisition

| | |
|---|---|
| Source | Dépôt V1 local : `F:\IA\Anonymisation\eval\datasets\PersonalReddit\Reddit_synthetic\` |
| Fichiers | `train.jsonl`, `test.jsonl` |
| Méthode | Chargement via `jsonlines` ou `json.load()` ligne par ligne |
| Prérequis | Aucun (accès local immédiat) |
| Cache local | `data/raw/personalreddit/` ou lecture directe depuis V1 |

## 6. Licence et conformité

- **Synthétique confirmé** : profils et commentaires générés par modèles, pas de
  personnes réelles. Voir README corpus + source GitHub ETH SRI.
- **Aucune contrainte RGPD** sur les sujets (personnes synthétiques).
- **Garde E2 de SPEC-08 n'est PAS applicable** : l'attaquant avec recherche web
  est **autorisé** sur ce corpus. Toute recommandation contraire dans la littérature
  s'applique à du Reddit réel, pas ici.
- Licence source : CC-BY-SA (consulter le manifeste V1)

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
| **Très petit corpus (525 lignes)** | Corpus d'évaluation et de mise au point uniquement, pas d'entraînement. Intervalle de confiance large sur les métriques. |
| Synthétique | Excellent pour l'expérience contrôlée ; crédibilité limitée pour garantie opérationnelle. |
| Pas d'annotations de spans | Aucune F1 de détection. Inférence au niveau document seulement. |
| Anglais uniquement | Aucune mesure FR. |
| Format `feature` + `hardness` complexe | Une même personne peut figurer dans plusieurs lignes avec différents `feature`/`hardness` — split par `person_id`, jamais par ligne. |
| Pas de population de référence explicite | Le calcul de $k$ nécessite une population externe (ex. Census US). |
| Hardness : échelle inconnue | Les valeurs (1, 2, 3, …) ne sont pas documentées. Première tâche : inspecter et documenter. |

> **C'est du synthétique, donc aucune contrainte RGPD.** L'attaquant avec recherche
> web est autorisé ; les résultats d'attaque peuvent être publiés librement. Ce n'est
> pas un benchmark réel d'anonymisation opérationnelle, mais excellent pour étudier
> l'inférence d'attributs en isolation.

## 10. Mapping vers le schéma interne

| Objet PersonalReddit | Objet interne | Mapping |
|----------------------|---------------|---------|
| ligne (réponse) | `Document` | `domain = "forum"`, `language = "en"`, `author_id` (si `person_id` existe) |
| `response` | `Document.text` | Texte brut du message |
| `personality` | `Profile.attributes` | 9 attributs → codes SPEC-01 (voir tableau §10.1) |
| `hardness` | `Document.meta.difficulty` | Directement mappé (valeur numérique ou ordinale) |
| `feature` | `tasks.jsonl` | `task = "personality_prediction"`, `label = feature_value` |
| `guess` / `guess_correctness` | attaquant baseline | Stocké dans `Document.meta` ou comme annotation de validation |

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

- **Split officiel** : `train.jsonl` et `test.jsonl` (pas de dev) — à accepter ou
  reconstruire selon les besoins.
- **Granularité CRITIQUE** : **split par `person_id`**, jamais par ligne/réponse.
  Sinon fuite massive : une même personne dans train et test.
- Deux granularités d'évaluation :
  - **document-level** : inférence depuis une seule `response`
  - **author-level** : inférence depuis l'union des réponses d'une même personne

## 12. Plan d'implémentation de l'adaptateur

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Charger train + test, inspecter schéma réel | note §3, §4, §9 (hardness!) |
| 2 | Synthétique confirmé ; aucune garde E2 requise | spec conformité |
| 3 | Extraire personnes uniques ; vérifier split par person_id sans fuite | stats splits |
| 4 | Mapper 9 attributs vers SPEC-01 (voir tableau §10.1) | `label_map` |
| 5 | Fixer splits, checksum, volumétrie, statut réel/synth au manifeste | `configs/datasets/personalreddit.yaml` |
| 6 | Implémenter `PersonalRedditAdapter` | `src/anonymisation/datasets/personalreddit.py` |
| 7 | Émettre `profiles.jsonl` + `documents.jsonl` + `tasks.jsonl` | `data/processed/personalreddit/` |
| 8 | Implémenter l'agrégation author-level | `src/anonymisation/datasets/aggregation.py` |
| 9 | Rejouer l'attaquant baseline (inférence des auteurs via `guess`) comme baseline A | rapport |

## 13. Critères d'acceptation

- [ ] Tous les documents et profils chargés avec `domain = "forum"`, `language = "en"`.
- [ ] `person_id` présent et stable pour chaque auteur.
- [ ] 9 attributs mappés, aucun orphelin.
- [ ] Split par auteur sans fuite de `person_id`.
- [ ] `hardness` documenté et valide pour chaque document.
- [ ] L'évaluation author-level détecte strictement plus de QI que document-level
      (test de sanité).
- [ ] **Statut synthétique confirmé au manifeste** (pas de garde E2 applicable).

## 14. Questions ouvertes

- Combien de `person_id` uniques ? Distribution (combien de réponses par auteur) ?
- Quelle est l'échelle de `hardness` ? Valeurs : 1-5 ? 1-10 ? Sémantique : difficile
  à inférer vs facile ?
- Y a-t-il un `person_id` explicite dans les données, ou faut-il l'inférer ?
- La `question_asked` ajoute-t-elle du signal ou est-elle déterministe depuis
  `feature` ?
- Quelle est la distribution des `feature` ? Équilibrée ou skewed ?
- Existe-t-il une population de référence US/anglophone pour le calcul de $k$ ?
- Le `guess` et `guess_correctness` proviennent-ils du même modèle ou d'attaquants
  différents ?

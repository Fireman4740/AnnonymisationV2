# DB-bio

| | |
|---|---|
| **Clé interne** | `dbbio` |
| **Priorité** | **P1** |
| **Benchmark** | B1 (utilité aval), diagnostic pour QI |
| **Statut de la fiche** | Stable · v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom complet | DB-bio — Biographies Wikipedia avec labels d'occupation hiérarchiques |
| Type | **Réel** — biographies Wikipedia authentiques |
| Langue | Anglais |
| Domaine | **Générique** (mais fortement ancré métier via occupation) |
| Source | Dépôt interne V1 |

## 2. Rôle et priorité

**Corpus P1 pour la mesure d'utilité aval** et comme **contrôle de détection de
noms de personnes**.

C'est à la fois :
1. **Une source de noms de personnes** — contexte encyclopédique où les noms sont
   usuels et peu anonymisés (`wiki_name`, colonne `people`).
2. **Une tâche d'utilité aval réelle** : classification hiérarchique d'occupation
   (`l1`/`l2`/`l3`) — une case d'usage métier commune (déterminer l'occupation d'une
   personne depuis sa biographie, c'est utile pour RH, recrutement, recherche).
3. **Un benchmark de dégradation d'utilité**, car l'occupations est organisée en
   trois niveaux hiérarchiques (`l1` = secteur, `l2` = métier, `l3` = spécialité).
   On peut mesurer la dégradation d'utilité à chaque niveau de généralisation.

## 3. Contenu et volumétrie

| Métrique | Valeur |
|----------|--------|
| Biographies | à confirmer |
| Splits | `train.jsonl`, `val.jsonl`, `test.jsonl` (+ SFT/DPO variants) |
| Taille disque | 20 Mo (JSONL) |
| Langue | Anglais |

### Structure de chaque ligne

| Colonne | Type | Contenu |
|---------|------|---------|
| `text` | `str` | Biographie complète (texto Wikipedia) |
| `wiki_name` | `str` | Nom de la personne (titre Wikipedia) |
| `people` | `list[str]` | Autres noms de personnes mentionnées dans `text` |
| `l1` | `str` ou `int` | Label niveau 1 (secteur, ex. « science », « arts ») |
| `l2` | `str` ou `int` | Label niveau 2 (métier, ex. « physique », « peinture ») |
| `l3` | `str` ou `int` | Label niveau 3 (spécialité, ex. « mécanique quantique ») |
| `word_count` | `int` | Nombre de mots dans `text` |
| `label` | (?) | Label simplifiée ? (à clarifier) |

### Variantes de split

Deux formats supplémentaires :
- `train_sft.jsonl` : format superviser fine-tuning
- `train_dpo.jsonl` : format direct preference optimization

Rôle de ces variantes : à confirmer (probablement pour entraîner des modèles aval).

## 4. Structure brute

- **Niveau document** : une biographie = un document.
- **Niveau annotation implicite** : la colonne `people` fournit une liste de noms de
  personnes qui apparaissent dans `text` (peut être une fiche d'entités).
- **Niveau occupation** : une structure hiérarchique à trois niveaux (`l1/l2/l3`),
  ce qui permet de mesurer la dégradation d'utilité à chaque grain.

Pas de spans explicites (offsets des noms dans le texte), mais la colonne `people`
et `wiki_name` fournissent des **listes de noms** à détecter/chercher dans `text`.

**Point sensible** : déterminer si `people` est une liste de mentions intra-texte ou
si c'est simplement une liste de co-auteurs/personnages contemporains sans localisation
dans le texte. Premier travail : inspecter.

## 5. Accès et acquisition

| | |
|---|---|
| Source | Dépôt V1 local : `F:\IA\Anonymisation\eval\datasets\DB-bio\` |
| Fichiers | `train.jsonl`, `val.jsonl`, `test.jsonl`, `train_sft.jsonl`, `train_dpo.jsonl` |
| Méthode | Chargement via `jsonlines` ou `json.load()` |
| Prérequis | Aucun (accès local immédiat) |
| Cache local | `data/raw/dbbio/` ou lecture directe depuis V1 |

## 6. Licence et conformité

- **Biographies Wikipedia** → personnes réelles (très réelles, bien identifiées).
- **Garde E2 obligatoire** ([SPEC-08](../specifications/SPEC-08-attaquants.md)) : l'attaquant
  avec recherche web est **interdit** (une biographie Wikipedia + un nom =
  identification triviale).
- Licence Wikipedia : CC-BY-SA 3.0, redistribution autorisée avec attribution.

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs (noms) | ✅ |
| QI indirects (occupation) | ✅ |
| Tâche d'utilité aval | ✅ |
| **Hiérarchie d'utilité** (l1/l2/l3) | ✅ |
| Multi-documents par auteur | ❌ |
| Population de référence | ❌ |
| Multilingue | ❌ (anglais) |
| Texte réel | ✅ |
| Spans localisés | ❌ (listes de noms, pas d'offsets) |

## 8. Apport pour le projet

1. **Tâche d'utilité aval réelle** : la classification d'occupation hiérarchique est
   une tâche métier authentic (RH, recrutement). Permet de mesurer la dégradation
   d'utilité quand on anonymise.
2. **Structure hiérarchique (`l1/l2/l3`)** : rare dans les corpus. Permet de mesurer
   la dégradation d'utilité à différents niveaux de granularité.
3. **Noms de personnes authentiques** — source réaliste pour tester la détection de
   noms et la coréférence (vs noms synthétiques).
4. **Domaine générique (mais métier-ancré)** — permet de tester la généralisation
   cross-domaine.

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| Pas d'offsets (spans non localisés) | Détection de noms requiert une recherche exacte ou fuzzy dans `text` — aucune vérité terrain d'offset. |
| Personnes réelles identifiées | Garde E2 stricte. Attaquant web interdit. Aucune sortie d'attaquant en clair. |
| Une biographie par personne | Pas d'agrégation multi-documents. |
| Occupation unique par biographie | Cas réaliste (une personne = une occupation principale), mais ne capture pas les carrières multiples. |
| **Point délicat : `people` column** | Est-ce que `people` contient les offsets exacts ? Ou juste une liste de noms sans localisation ? Décisif pour la faisabilité. |
| Anglais uniquement | Aucune mesure FR. |
| Classifieur aval figé V1 | L'audit V1 signale que le classifieur occupationnel n'était pas bien configuré. Prérequis : re-configurer ou re-entraîner. |

> **Piège méthodologique** : ce corpus ressemble à un dataset d'annotation QI
> (noms + occupation), mais c'est d'abord une source de **tâche d'utilité aval**.
> Ne pas le traiter comme un benchmark d'anonymisation ; le traiter comme un
> **test de régression d'utilité**. L'approche : anonymiser, re-entraîner un
> classifieur, mesurer la dégradation de F1.

## 10. Mapping vers le schéma interne

| Objet DB-bio | Objet interne | Mapping |
|--------------|---------------|---------|
| ligne (biographie) | `Document` | `domain = "generic"`, `language = "en"` |
| `text` | `Document.text` | Biographie brute |
| `wiki_name` + `people` | Annotations | Code `DIR_NAME` (identifiant direct) |
| `l1` / `l2` / `l3` | `tasks.jsonl` | Trois tâches séparées ou une hiérarchie unique ? (à fixer) |

### Sous-option de mapping : structure hiérarchique

**Option A** : trois tâches indépendantes
```json
{ "doc_id": "db_bio:d_001", "task": "occupation_l1", "label": "science" }
{ "doc_id": "db_bio:d_001", "task": "occupation_l2", "label": "physics" }
{ "doc_id": "db_bio:d_001", "task": "occupation_l3", "label": "quantum" }
```

**Option B** : une tâche hiérarchique unique (plus expressif)
```json
{ "doc_id": "db_bio:d_001", "task": "occupation", "label": ["science", "physics", "quantum"], "label_type": "hierarchy" }
```

À décider au manifeste.

## 11. Splits et protocole

- **Splits officiels fournis** : `train.jsonl` (≈ 70%), `val.jsonl` (≈ 15%),
  `test.jsonl` (≈ 15%). À accepter.
- **Granularité** : document-level (biographie).
- Les variantes `train_sft.jsonl` et `train_dpo.jsonl` : probablement des reformatages
  du même `train` pour différentes architectures. Clarifier si utiles.

## 12. Plan d'implémentation de l'adaptateur

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Charger train/val/test, inspecter schéma | note §3, §4 (surtout `people`) |
| 2 | Analyser `people` : sont-ce des offsets ou juste noms ? | spec décision |
| 3 | Localiser noms dans texte (recherche exacte ou fuzzy) ; générer offsets | `people_offsets.json` |
| 4 | Extraire valeurs uniques de `l1`, `l2`, `l3` | label vocabulaires |
| 5 | Décider : tâche hiérarchique (option B) ou trois tâches (option A) | spec manifeste |
| 6 | Fixer checksum, volumétrie, splits au manifeste | `configs/datasets/dbbio.yaml` |
| 7 | Implémenter `DBBioAdapter` | `src/anonymisation/datasets/dbbio.py` |
| 8 | Émettre `documents.jsonl` + `annotations.jsonl` (noms DIR_NAME) + `tasks.jsonl` | `data/processed/dbbio/` |
| 9 | (Optionnel) Re-configurer/re-entraîner classifieur occupationnel aval | `models/occupation_classifier` |

## 13. Critères d'acceptation

- [ ] Train/val/test chargés avec `domain = "generic"`, `language = "en"`.
- [ ] Tous les noms (`wiki_name` + `people`) localisés dans `text` (offsets
      calculés ou validés).
- [ ] Annotations DIR_NAME générées avec offsets valides (invariant I-ANN-1).
- [ ] `l1/l2/l3` mappé vers tâche d'utilité (option A ou B), aucun orphelin.
- [ ] Split train/val/test sans fuite.
- [ ] (Si option B) Hiérarchie respectée dans les labels (ex. « science → physics
      → quantum »).

## 14. Questions ouvertes

- Contient la colonne `people` les offsets exacts des mentions dans `text`, ou
  juste une liste de noms ?
- Combien d'exemples exactement dans train/val/test ?
- Les valeurs de `l1/l2/l3` sont-elles des codes (entiers) ou des chaînes lisibles ?
- Y a-t-il une ontologie/hiérarchie connue (ex. ESCO, ISCO) pour les labels
  occupationnels ?
- Que contient le champ `label` ? Est-ce une simplification de `l1/l2/l3` ?
- À quoi servent exactement `train_sft.jsonl` et `train_dpo.jsonl` ? Quels modèles
  les utilisent ?
- Existe-t-il une population de référence (statistiques d'occupation réelle par pays)
  pour le calcul de $k$ ?
- Pourquoi l'audit V1 signale un classifieur occupationnel mal configuré ? Quel était
  le problème exact ?

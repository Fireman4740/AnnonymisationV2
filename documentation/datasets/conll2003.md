# CleanCoNLL / CoNLL-2003

| | |
|---|---|
| **Clé interne** | `conll2003` |
| **Priorité** | **P1** |
| **Benchmark** | B1 (diagnostic NER) |
| **Statut de la fiche** | Stable · v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom complet | CoNLL-2003 Named Entity Recognition Shared Task — CleanCoNLL version |
| Référence | Tjong Kim Sang & De Meulder (2003), corpus standard en NER |
| Type | **Annoté** — benchmark NER de référence |
| Langue | Anglais |
| Domaine | **Newswire** (dépêches de presse Reuters) |
| Source | Dépôt interne V1 |

## 2. Rôle et priorité

**Corpus P1 de diagnostic NER uniquement**, jamais un benchmark d'anonymisation
complète.

C'est un **contrôle de santé** : CoNLL-2003 est le standard historique en détection
d'entités nommées. Le faire tourner sur notre pipeline NER (avant toute
anonymisation) vérifie que :
1. Notre infrastructure d'ingestion, validation et évaluation d'annotations **fonctionne correctement**.
2. La conversion BIO → spans caractères (point délicat) est correcte.
3. Les labels `PER`, `ORG`, `LOC`, `MISC` se mappent sans perte vers SPEC-01.

**Ni plus ni moins.** Les résultats CoNLL-2003 n'entrent **jamais** dans le score
final du projet. Ce sont des métriques **`DIAGNOSTIC`** (SPEC-06).

## 3. Contenu et volumétrie

| Métrique | Valeur |
|----------|--------|
| Splits | train, dev, test |
| Vocabulaire | ≈ 20 000 mots uniques |
| Taille disque | 13 Mo (avec cache) |
| Format | BIO (Begin-Inside-Outside) au niveau token |
| Langue | Anglais |

### Format BIO

Chaque mot est taggé avec un label BIO :
```
John    B-PER     (début d'entité personne)
Smith   I-PER     (intérieur d'entité personne)
is      O         (hors entité)
CEO     O
of      O
Apple   B-ORG     (début d'entité organisation)
Inc     I-ORG     (intérieur…)
.       O
```

Quatre catégories d'entités :
- `PER` : Personne
- `ORG` : Organisation
- `LOC` : Localisation
- `MISC` : Miscellaneous (autre)

### Tâche de conversion

Convertir BIO → spans caractères (`start`, `end`, `text`) est **le point
critique**. Problèmes courants :
- Whitespace et ponctuation : où commencent/finissent exactement les spans ?
- Tokens multi-caractères (ex. « John's » est-il un ou deux tokens ?)
- Invariant SPEC-02 I-ANN-1 : `text[start:end] == span_text` (caractères, pas tokens).

## 4. Structure brute

- **Niveau phrase** : chaque ligne CoNLL est un token avec son tag BIO.
- **Niveau document** : a priori une dépêche = un document (à clarifier — certaines
  dépêches sont peut-être concaténées).
- **Granularité d'annotation** : token-level en entrée → **conversion en span
  caractère** obligatoire pour SPEC-02.

**Fichiers source** :
- `cleanconll/` : données brutes
- `cleanconll_annotations/` : les trois splits (train/dev/test)
- `conll03/conll2003.zip` : archive officielle (backup)

## 5. Accès et acquisition

| | |
|---|---|
| Source | Dépôt V1 local : `F:\IA\Anonymisation\eval\datasets\cleanconll_cache\` |
| Fichiers | `cleanconll/`, `cleanconll_annotations/{train,dev,test}`, `conll03/conll2003.zip` |
| Méthode | Chargement via utilitaire CONLL (format standard), puis conversion BIO → spans |
| Prérequis | Aucun (accès local) |
| Utilitaire | `src/anonymisation/datasets/_bio.py` (utilitaire commun de conversion) |
| Cache local | `data/raw/conll2003/` ou lecture directe depuis V1 |

## 6. Licence et conformité

- **Dépêches Reuters publiques** → licence CC-BY 4.0, redistribution autorisée.
- Pas de personnes réelles identifiables (données journalistiques anonymisées par
  design Reuters).
- Aucune garde RGPD (GDPR) requise.

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs (noms de personnes) | ✅ |
| Organisations | ✅ |
| Localisations | ✅ |
| Annotations de spans | ✅ |
| Multi-documents par auteur | N/A (newsswire, pas de profil auteur) |
| Population de référence | ❌ (newsswire, pas applicable) |
| Multilingue | ❌ (anglais) |
| Texte réel | ✅ |
| **Diagnostic NER** | ✅ |
| **Benchmark d'anonymisation complète** | ❌ (usage diagnostic uniquement) |

## 8. Apport pour le projet

1. **Validation de l'infrastructure d'ingestion** : CoNLL-2003 est un benchmark
   historique bien connu. Le faire tourner valide la chaîne technique (conversion
   BIO, validation d'offsets, etc.).
2. **Contrôle de conversion BIO → spans** : point délicat, jamais trivial. CoNLL
   fournit une vérité terrain externe bien établie.
3. **Mapping NER standard** : `PER` → `DIR_NAME`, `ORG` → `GEN_AFFILIATION`,
   `LOC` → `GEN_GEO`, `MISC` → `IGNORED`. Cas simple, bonne couverture du bloc
   `DIR_*` et `GEN_*`.

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| **Benchmark diagnostic uniquement** | Les métriques CoNLL-2003 sont `MetricStatus.DIAGNOSTIC` et **n'entrent jamais dans le score final du projet**. Ne jamais les présenter comme une validation de la robustesse d'anonymisation. |
| Newsswire (domaine dépêches) | Ne transfère pas aux domaines RH, support, forums du projet. Aucune mesure cross-domaine valide. |
| Anglais uniquement | Aucune mesure FR. |
| NER simple vs anonymisation | La détection NER (CoNLL) est un sous-problème d'anonymisation. Un bon résultat NER ne garantit pas une bonne anonymisation (peut manquer des QI implicites, contexte métier, etc.). |
| Conversion BIO piégée | Erreur lors de la conversion BIO → spans = invalidation silencieuse de tout le corpus. **Point de vigilance maximal**. |

> **Piège méthodologique majeur** : **ne JAMAIS interpréter un résultat F1
> CoNLL-2003 comme une évaluation d'anonymisation**. CoNLL mesure la détection
> d'entités nommées standard. L'anonymisation requiert bien plus : contexte,
> implicite, coréférence, sensibilité. Un F1 CoNLL de 95 % ne dit rien sur la
> robustesse d'anonymisation réelle.

## 10. Mapping vers le schéma interne

| Objet CoNLL | Objet interne | Mapping |
|-------------|---------------|---------|
| document (phrase?) | `Document` | `domain = "news"`, `language = "en"` |
| token sequence | `Document.text` | Reconstruit depuis tokens BIO |
| B-PER / I-PER | Annotation | `identifier_type = "DIRECT"`, `qi_categories = ["DIR_NAME"]` |
| B-ORG / I-ORG | Annotation | `identifier_type = "QUASI"`, `qi_categories = ["GEN_AFFILIATION"]` |
| B-LOC / I-LOC | Annotation | `identifier_type = "QUASI"`, `qi_categories = ["GEN_GEO"]`, **note: à documenter** |
| B-MISC / I-MISC | Annotation | `identifier_type = "IGNORED"` (hors périmètre) |

### Note : LOC → GEN_GEO ou DIR_?

`LOC` dans CoNLL couvre à la fois :
- Localisations précises (villes, adresses) → quasi-identifiants ;
- Noms de régions/pays génériques → moins directs d'identification.

La décision : traiter tout LOC comme `GEN_GEO` (quasi-identifiant), car la
distinction fine nécessite du contexte. Si le projet devait distinguer plus
finement, utiliser `granularity` (EXACT vs COARSE).

## 11. Splits et protocole

- **Splits officiels** : train / dev / test.
- **Granularité** : token-level en entrée CoNLL. Agrégation à document-level en
  sortie SPEC-02.
- **À clarifier** : qu'est-ce qu'un « document » dans CoNLL ? Une phrase ? Une
  dépêche entière ? Décisif pour les splits.

## 12. Plan d'implémentation de l'adaptateur

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Charger depuis cleanconll_cache, inspecter format exact | format doc |
| 2 | Parsekoallfichiers {train,dev,test} au format BIO standard | `tokenized.jsonl` |
| 3 | Reconstuire texte depuis tokens (whitespace, ponctuation) | `text_reconstructed` |
| 4 | **Utiliser `_bio.py` pour convertir BIO → spans caractères** | `spans_bio.jsonl` |
| 5 | **Valider chaque span : `text[start:end] == span_text` (invariant I-ANN-1)** | validation report |
| 6 | Mapper labels BIO vers SPEC-01 (voir tableau §10) | `label_map` |
| 7 | Fixer checksum, volumétrie au manifeste | `configs/datasets/conll2003.yaml` |
| 8 | Implémenter `CoNLL2003Adapter` | `src/anonymisation/datasets/conll2003.py` |
| 9 | Émettre `documents.jsonl` + `annotations.jsonl` | `data/processed/conll2003/` |
| 10 | **Marquer toutes les métriques issues de CoNLL comme `MetricStatus.DIAGNOSTIC`** | spec pipeline |

## 13. Critères d'acceptation

- [ ] Tous les tokens chargés depuis les trois splits.
- [ ] Texte reconstruit depuis tokens avec whitespace/ponctuation corrects.
- [ ] **Conversion BIO → spans validée** : chaque span vérifie
      `text[start:end] == span_text` (invariant I-ANN-1).
- [ ] Labels mappés vers SPEC-01 sans orphelin.
- [ ] Split train/dev/test sans fuite.
- [ ] Métriques (F1, precision, recall) **explicitement marquées** `DIAGNOSTIC`
      (jamais intégrées au score final).
- [ ] Documentation claire : « CoNLL-2003 est un benchmark de diagnostic NER,
      pas d'anonymisation. »

## 14. Questions ouvertes

- Quelle est la granularité exacte du « document » ? Une phrase ? Une dépêche ?
- Les trois splits officiel (train/dev/test) sont-ils fournis, ou faut-il les
  reconstruire depuis l'archive zip ?
- Y a-t-il un mismatch token-character entre le format BIO tokenisé et le texte
  brut reconstruit ? Combien de cas problématiques ?
- L'utilitaire `_bio.py` gère-t-il tous les edge cases (apostrophes, traits
  d'union, caractères accentués en UTF-8) ?
- Les distributions des labels (PER/ORG/LOC/MISC) sont-elles équilibrées ?
  (Important pour séparer les questions diaganostiques vs utilité.)
- Existe-t-il une version plus récente ou plus propre de CoNLL-2003 (ex.
  annotée au niveau caractère plutôt que token) ?

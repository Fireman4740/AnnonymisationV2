# MultiCoNER II

| | |
|---|---|
| **Clé interne** | `multiconer2` |
| **Priorité** | P1 |
| **Benchmark** | B1 (PII Detection) — volet robustesse |
| **Statut de la fiche** | Stable · v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom | MultiCoNER II — Multilingual Complex Named Entity Recognition (SemEval-2023 Task 2) |
| Référence | [@fetahu2023multiconer] |
| Type | Texte réel, annoté |
| Langues | FR, EN, DE, ES, IT, PT, SV, UK, ZH, HI, BN, FA (12) |
| Domaine | Généraliste (requêtes, texte court, entités complexes) |

## 2. Rôle et priorité

**Ce n'est pas un dataset de confidentialité.** Il n'a qu'un usage dans le
projet : le **stress-test linguistique** du détecteur.

Il répond à une question précise que les corpus de privacy ne posent pas :

> le détecteur tient-il quand l'information apparaît dans une formulation
> inhabituelle, dans un texte bruité, ou dans une autre langue ?

C'est un complément direct à l'axe « formulation non standard » de RAT-Bench,
mais mesuré sur du texte réel et sur 12 langues.

Classé **P1 — secondaire** pour le benchmark de privacy.

## 3. Contenu et volumétrie

| | |
|---|---|
| Langues | 12 + un track multilingue |
| Taille | ~2 M tokens par langue selon les tracks |
| Taille disque | ~1 Go |
| **Sous-ensemble bruité** | ✅ (corruptions typographiques, casse, etc.) |

Le sous-ensemble bruité est **la raison principale** d'inclure ce dataset.

### Taxonomie

MultiCoNER II utilise une taxonomie fine (36 classes) organisée en 6 catégories
de haut niveau : Person, Location, Group, Product, Creative Work, Medical.

Seul un sous-ensemble intéresse le projet : `Person` (et ses sous-types),
`Location`, `Group`/organisation, et éventuellement `Medical`.

## 4. Structure brute

Format CoNLL / BIO, un fichier par langue et par split.

Même remarque que pour JobStack : la conversion BIO → spans caractères doit
passer par l'utilitaire commun `src/anonymisation/datasets/_bio.py`, avec
validation stricte.

## 5. Accès et acquisition

| | |
|---|---|
| Source | `multiconer.github.io/dataset` + Hugging Face |
| Méthode | `scripts/download_multiconer.py` |
| Prérequis | Éventuel formulaire d'enregistrement SemEval — à vérifier |
| Cache local | `data/raw/multiconer2/` |

**Note V1** : le dépôt V1 contient `eval/core/loaders/conll2003.py` et
`eval/core/dataset_adapters/conll2003.py`. La logique BIO y est déjà écrite et
testée — la reprendre plutôt que la réécrire.

## 6. Licence et conformité

- Licence ouverte de la campagne SemEval (à confirmer précisément).
- Texte issu de sources publiques (Wikipedia, requêtes), pas de contrainte RGPD
  particulière, mais des **personnes réelles** sont nommées → ne pas publier de
  sortie d'attaquant.

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs | ◐ (entités nommées, pas PII au sens strict) |
| QI indirects | ❌ |
| Combinaisons | ❌ |
| Population de référence | ❌ |
| **Multilingue (12 langues)** | ✅ |
| **Français** | ✅ |
| **Texte bruité** | ✅ |
| **Entités complexes / ambiguës** | ✅ |
| Texte réel | ✅ |

## 8. Apport pour le projet

1. **Robustesse au bruit** — aucun autre corpus de la batterie ne mesure la
   dégradation sous corruption typographique. Or les tickets support et les
   messages de forum réels sont bruités.
2. **Couverture linguistique large** — permet de vérifier que le détecteur ne
   s'effondre pas hors FR/EN, avant d'annoncer un système « multilingue ».
3. **Entités complexes** — MultiCoNER cible délibérément les cas ambigus
   (entités rares, imbriquées, polysémiques). C'est un bon proxy des QI
   difficiles.
4. Usage possible en **pré-entraînement** de la couche NER.

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| Pas un corpus de privacy | Aucun score MultiCoNER ne mesure une protection. |
| Taxonomie NER ≠ taxonomie QI | Le mapping est partiel et lossy. `Creative Work` n'a pas d'équivalent QI. |
| Texte court / requêtes | Peu de contexte, donc peu de QI implicites. |
| Risque de dérive d'objectif | Optimiser le F1 MultiCoNER n'améliore pas le risque de ré-identification. |

> **Règle** : les métriques MultiCoNER sont marquées `MetricStatus.DIAGNOSTIC`
> et ne remontent jamais dans le score principal du projet.

## 10. Mapping vers le schéma interne

| Objet MultiCoNER | Objet interne | Notes |
|------------------|---------------|-------|
| phrase | `Document` | `domain = "generic"`, `language` = code langue |
| entité BIO | `Annotation` | conversion via utilitaire commun |
| classe fine (36) | `Annotation.qi_category` | mapping **partiel** ; les classes hors périmètre sont explicitement mappées vers `IGNORED` — pas silencieusement ignorées |
| sous-ensemble bruité | `Document.meta.noisy = true` | axe de reporting « propre vs bruité » |

Le code `IGNORED` doit exister dans SPEC-01 : il rend le mapping **total** tout
en excluant les classes hors sujet du calcul des métriques.

## 11. Splits et protocole

- Splits officiels SemEval, par langue.
- Deux mesures obligatoires : F1 sur le sous-ensemble propre, F1 sur le
  sous-ensemble bruité. **La métrique intéressante est l'écart**, pas le niveau.
- Protocole `diagnostic`.

## 12. Plan d'implémentation

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Reprendre l'utilitaire BIO de la V1 | `_bio.py` |
| 2 | Télécharger les langues retenues (FR, EN, DE, ES en priorité) | `data/raw/multiconer2/` |
| 3 | Mapping total des 36 classes (dont `IGNORED`) | `configs/datasets/multiconer2.yaml` |
| 4 | `MultiConerAdapter` | `src/anonymisation/datasets/multiconer2.py` |
| 5 | Rapport « propre vs bruité » et « par langue » | rapport de robustesse |

## 13. Critères d'acceptation

- [ ] Les 36 classes sont mappées (y compris vers `IGNORED`) ; zéro classe
      inconnue.
- [ ] `text[start:end] == span_text` sur 100 % des spans.
- [ ] Le rapport produit un F1 par langue **et** un delta propre/bruité.
- [ ] Aucune métrique MultiCoNER ne remonte dans le score principal.

## 14. Questions ouvertes

- Quelles langues retenir ? (recommandation : FR, EN, DE, ES — les quatre du
  périmètre réaliste du projet ; les 8 autres n'apporteraient qu'un coût)
- Faut-il l'utiliser en pré-entraînement, au risque de biaiser la comparaison
  entre baselines ? → si oui, l'appliquer identiquement à toutes les baselines
  et le déclarer.

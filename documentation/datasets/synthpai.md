# SynthPAI

| | |
|---|---|
| **Clé interne** | `synthpai` |
| **Priorité** | **P0** |
| **Benchmark** | B2 (Indirect QI Detection), support de B3 |
| **Statut de la fiche** | Stable · v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom complet | SynthPAI — A Synthetic Dataset for Personal Attribute Inference |
| Référence | [@yukhymenko2024synthpai] — NeurIPS 2024, Datasets & Benchmarks |
| Auteurs | Yukhymenko, Staab, Vero, Vechev (ETH SRI) |
| Type | **Synthétique** — profils et commentaires générés |
| Langue | Anglais |
| Domaine | **Forums** (style Reddit) |
| Dépôts | `github.com/eth-sri/SynthPAI` · `huggingface.co/datasets/RobinSta/SynthPAI` |

## 2. Rôle et priorité

**Le benchmark forums de la batterie.** C'est le seul corpus P0 qui couvre
nativement le domaine forums, et il a été conçu précisément pour étudier
l'**inférence d'attributs personnels à partir de texte en ligne** — c'est-à-dire
l'étape centrale du pipeline :

$$
\text{texte} \rightarrow \text{attributs personnels}
\qquad\text{puis}\qquad
\text{attributs} \rightarrow \text{risque}
$$

**Atout structurel décisif** : SynthPAI possède déjà la structure
`profil latent → plusieurs messages du même auteur`. C'est exactement la
structure exigée pour les corpus internes
([SPEC-05](../specifications/SPEC-05-generation-corpus-synthetiques.md)).
SynthPAI sert donc aussi de **modèle d'implémentation** pour HR-QI-Bench,
Support-QI-Bench et Forum-QI-Bench.

## 3. Contenu et volumétrie

| | |
|---|---|
| Commentaires | **7 823** |
| Threads | **103** |
| Profils synthétiques | **300** |
| Taille disque | < 50 Mo |

### Attributs personnels annotés

| Attribut | Type |
|----------|------|
| âge | numérique / tranche |
| sexe | catégoriel |
| revenu | ordinal |
| localisation | catégoriel géographique |
| lieu de naissance | catégoriel géographique |
| éducation | ordinal |
| profession | catégoriel |
| statut relationnel | catégoriel |

Ces huit attributs sont exactement des **quasi-identifiants** au sens du projet.

## 4. Structure brute

Deux niveaux :

1. **Profils** — un enregistrement par personne synthétique, avec les valeurs
   des huit attributs.
2. **Commentaires** — texte + `author_id` + `thread_id` + annotations
   d'attributs inférables depuis ce commentaire (avec, selon les versions, un
   niveau de certitude / hardness).

Structure exacte des champs à figer lors du premier chargement.

## 5. Accès et acquisition

| | |
|---|---|
| Source | Hugging Face `RobinSta/SynthPAI` (recommandé) ou GitHub `eth-sri/SynthPAI` |
| Méthode | `datasets.load_dataset` ou clonage + `scripts/download_synthpai.py` |
| Prérequis | Aucun (pas de gating a priori) |
| Cache local | `data/raw/synthpai/` |

**Note V1** : le dépôt V1 contient `eval/datasets/PersonalReddit` et
`eval/core/dataset_adapters/personalreddit.py` — même famille de travaux
(ETH SRI), logique d'inférence d'attributs comparable. À consulter.

## 6. Licence et conformité

- Données **entièrement synthétiques** → aucune personne réelle, aucune
  contrainte RGPD sur les sujets.
- Licence : ouverte (vérifier la valeur exacte sur la carte HF et la fixer dans
  le manifeste).
- Redistribution des dérivés : autorisée sous réserve de citation.

C'est, avec OpenPII, le dataset le moins contraint de la batterie — d'où sa
position n°2 dans l'ordre d'implémentation.

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs | ◐ |
| QI indirects | ✅ |
| QI implicites | ✅ |
| Combinaisons annotées | ◐ (attributs par personne, combinaisons dérivables) |
| **Profil latent** | ✅ |
| Multi-documents par personne | ✅ |
| Population de référence | ❌ |
| Attaquant | ◐ (protocole d'inférence fourni par les auteurs) |
| Multilingue | ❌ (anglais) |
| Domaine forums | ✅ |
| Texte réel | ❌ |

## 8. Apport pour le projet

1. **Le domaine forums**, sans lequel un tiers du périmètre serait non mesuré.
2. **La chaîne profil → messages → attributs inférables**, qui permet de
   construire des combinaisons de QI **au niveau auteur** et non seulement au
   niveau document — cas d'usage central du projet (un utilisateur de forum est
   ré-identifié par l'agrégation de son historique, pas par un message isolé).
3. Un **protocole d'inférence d'attributs** réutilisable pour l'attaquant A.
4. Un **modèle de génération** pour SPEC-05.

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| Personnes synthétiques | Excellent pour l'expérience contrôlée, peu crédible comme mesure finale de robustesse en production. Ne jamais présenter un résultat SynthPAI comme une garantie opérationnelle. |
| Anglais seul | Aucune mesure FR. |
| Pas de population de référence | Le k n'est pas calculable sans construire une population ad hoc à partir des 300 profils (population **fermée**, biais fort). |
| 300 profils | Population trop petite pour un k réaliste. À traiter comme un **échantillon**, pas comme une population. |
| Style Reddit | Ne transfère pas aux forums d'entreprise ni au support. |

> **Piège méthodologique à éviter** : calculer k sur les 300 profils SynthPAI et
> le présenter comme un risque de ré-identification. Ce serait un k de
> *prosecutor* sur une population fermée de 300 personnes, sans rapport avec le
> risque réel. Si un k est calculé sur SynthPAI, il doit être marqué
> `MetricStatus.DIAGNOSTIC`.

## 10. Mapping vers le schéma interne

| Objet SynthPAI | Objet interne | Notes |
|----------------|---------------|-------|
| profil synthétique | `Profile` | `person_id = "synthpai:<id>"` |
| commentaire | `Document` | `domain = "forum"`, `language = "en"`, `author_id`, `thread_id` |
| attribut annoté | `Annotation` + `Profile.attributes` | l'attribut vit dans le profil ; le span, quand il est localisé, vit dans l'annotation |
| certitude / hardness | `Annotation.difficulty` | axe de reporting « par difficulté » |
| thread | `Document.thread_id` | permet l'agrégation conversationnelle |

**Point d'attention** : SynthPAI annote des **attributs inférables**, pas
toujours des **spans localisés**. Le schéma interne doit accepter une annotation
sans offsets (`start = end = null`) porteuse d'une inférence au niveau document.
C'est une exigence explicite de [SPEC-02](../specifications/SPEC-02-schema-donnees.md).

## 11. Splits et protocole

- Split **par `person_id`**, jamais par commentaire — sinon fuite massive
  (les messages d'un même auteur partagent le profil).
- Seed 42, 70/15/15 si aucun split officiel.
- Deux granularités d'évaluation à produire :
  - **document-level** : QI inférables depuis un commentaire isolé ;
  - **author-level** : QI inférables depuis l'union des commentaires d'un auteur.
  L'écart entre les deux est un résultat intéressant en soi (effet
  d'agrégation).

## 12. Plan d'implémentation de l'adaptateur

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Charger depuis HF, inspecter le schéma réel | note §4 |
| 2 | Fixer licence, checksum, volumétrie dans le manifeste | `configs/datasets/synthpai.yaml` |
| 3 | Mapper les 8 attributs vers les codes SPEC-01 | `label_map` |
| 4 | Implémenter `SynthPaiAdapter` | `src/anonymisation/datasets/synthpai.py` |
| 5 | Émettre `profiles.jsonl` + `documents.jsonl` + `annotations.jsonl` | `data/processed/synthpai/` |
| 6 | Implémenter l'agrégation author-level | `src/anonymisation/datasets/aggregation.py` |
| 7 | Rejouer le protocole d'inférence des auteurs comme attaquant A de référence | rapport |

## 13. Critères d'acceptation

- [ ] 7 823 commentaires, 103 threads, 300 profils chargés.
- [ ] Chaque `Document` a un `author_id` résolvant vers un `Profile`.
- [ ] Les 8 attributs sont mappés, aucun orphelin.
- [ ] Le split par auteur ne laisse aucun `person_id` dans deux splits.
- [ ] L'évaluation author-level détecte strictement plus de QI que
      l'évaluation document-level (test de sanité de l'agrégation).
- [ ] Tout k calculé sur SynthPAI est marqué `DIAGNOSTIC`.

## 14. Questions ouvertes

- Quelle version du dataset (HF vs GitHub) est la référence ? Les deux
  divergent-elles ?
- Les annotations comportent-elles des offsets, ou seulement des attributs au
  niveau commentaire ?
- Le protocole d'attaque des auteurs est-il directement exécutable avec des
  modèles < 30 B ?
- Vaut-il la peine de traduire un sous-ensemble en français pour disposer d'un
  point de comparaison FR/EN à contenu constant ? (piste intéressante, coût
  modéré, résultat publiable)

# RAT-Bench

| | |
|---|---|
| **Clé interne** | `ratbench` |
| **Priorité** | **P0** |
| **Benchmark** | B3 (Risk Estimation), B4 (End-to-End) |
| **Statut de la fiche** | Stable · v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom complet | RAT-Bench: A Comprehensive Benchmark for Text Anonymization |
| Référence | [@krco2026ratbench] — arXiv `2602.12806` `[à revérifier]` |
| Année | 2026 |
| Type | Synthétique, généré à partir de statistiques démographiques réelles |
| Langues | Multilingue (liste exacte à confirmer à l'acquisition) |
| Domaine | Généraliste, plusieurs scénarios |

## 2. Rôle et priorité

**Le dataset public le plus proche de l'objectif du projet** : « texte libre → QI
→ risque de ré-identification ». C'est le seul benchmark public qui ferme la
boucle complète en incluant un **attaquant** et une **population de référence**.

Il sert de :

- **référence externe** pour la Contribution B (estimation de risque calibrée) ;
- **point de comparaison** obligatoire dans toute publication issue du projet ;
- **modèle méthodologique** pour la construction des corpus internes
  ([SPEC-05](../specifications/SPEC-05-generation-corpus-synthetiques.md)).

## 3. Contenu et volumétrie

Le benchmark génère des textes depuis des profils démographiques, avec un
contrôle explicite sur :

| Axe de contrôle | Valeurs |
|-----------------|---------|
| Nature de l'identifiant | direct / indirect |
| Mode d'expression | explicite standard / **non standard** / **implicite** |
| Difficulté | plusieurs régimes |
| Langue | plusieurs |
| Scénario | plusieurs |

Volumétrie exacte : **à confirmer à l'acquisition** et à figer dans le manifeste
(`expected_documents`, `sha256`).

### Résultat de référence à reproduire

Le papier rapporte un risque de ré-identification passant d'environ **44 % à
69 %** lorsque les identifiants deviennent non standards, et conclut que
l'information exprimée **implicitement** reste très difficile à anonymiser.

> **Test de non-régression du projet** : reproduire l'ordre de grandeur de cet
> écart avec notre propre pipeline d'attaque. Un écart nul indiquerait un bug
> dans notre attaquant, pas une victoire.

## 4. Structure brute

À confirmer lors de l'acquisition. Les éléments attendus, d'après la
description du benchmark :

- des **profils** (attributs démographiques source) ;
- des **documents** générés depuis ces profils ;
- des **annotations** liant les spans du texte aux attributs du profil ;
- des **métadonnées de difficulté** (mode d'expression, régime) ;
- une **population de référence** (statistiques US) permettant le calcul du
  risque.

> Action d'implémentation n°1 : documenter la structure réelle dans cette section
> dès le premier téléchargement, avec un exemple complet d'enregistrement.

## 5. Accès et acquisition

| | |
|---|---|
| Source primaire | arXiv `2602.12806` `[à revérifier]` |
| Dépôt code/données | À identifier (GitHub et/ou Hugging Face) |
| Méthode | Script `scripts/download_ratbench.py` |
| Prérequis | Aucun a priori |
| Cache local | `data/raw/ratbench/` |

**Note V1** : le dépôt V1 (`../Anonymisation`) contient déjà
`eval/core/ratbench.py`, `eval/core/loaders/ratbench.py` et
`eval/core/dataset_adapters/ratbench.py`, ainsi qu'un cache
`eval/datasets/RAT-Bench`. **Commencer par les lire** : ils documentent de facto
le format réel et évitent une redécouverte.

## 6. Licence et conformité

- Licence : **à confirmer à l'acquisition**. Ne pas publier de résultats avant
  confirmation.
- Données synthétiques → pas de contrainte RGPD sur les personnes.
- Redistribution : interdite tant que la licence n'est pas vérifiée.
- Champ `license` du manifeste : obligatoire, valeur `UNKNOWN` bloquante en
  mode `official`.

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs | ✅ |
| QI indirects | ✅ |
| QI implicites | ✅ |
| Combinaisons de QI | ✅ |
| Profil latent | ✅ |
| Population de référence | ✅ (US) |
| Attaquant | ✅ |
| Risque de ré-identification | ✅ |
| Multilingue | ✅ |
| Français | ◐ |
| RH | ◐ transférable |
| Support | ◐ transférable |
| Texte réel | ❌ synthétique |

## 8. Apport pour le projet

1. **Valide la faisabilité** de la chaîne complète — c'est ce qui oblige à
   reformuler la contribution du projet (voir
   [03-lacunes-et-contribution §3](../rapport/03-lacunes-et-contribution.md)).
2. Fournit une **vérité terrain sur le risque**, indispensable pour mesurer
   MAE-risk, MAE-k, AUROC, AUPRC, Brier et ECE.
3. Fournit un **axe de difficulté contrôlé** : c'est le seul moyen de publier un
   F1 « par difficulté » et de montrer où le système casse.
4. Fournit un **protocole d'attaque** réutilisable pour
   [SPEC-08](../specifications/SPEC-08-attaquants.md).

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| Synthétique | Ne mesure pas la robustesse en production. Ne jamais présenter un résultat RAT-Bench comme une garantie opérationnelle. |
| Population US | Les distributions de professions, formations et localisations ne transfèrent pas à la France. Le k calculé est un k **américain**. |
| Pas de domaine RH/support natif | Transfert partiel seulement. |
| Pas de français natif fort | À vérifier langue par langue avant de publier une métrique FR. |
| Attaquant du papier ≠ notre attaquant | Les chiffres ne sont comparables que si le protocole d'attaque est identique. À documenter explicitement. |

## 10. Mapping vers le schéma interne

Cible : [SPEC-02](../specifications/SPEC-02-schema-donnees.md).

| Objet RAT-Bench | Objet interne | Notes |
|-----------------|---------------|-------|
| profil démographique | `profiles.jsonl` → `Profile` | `person_id` = identifiant RAT-Bench préfixé `ratbench:` |
| document généré | `documents.jsonl` → `Document` | `domain = "generic"`, `language` depuis la métadonnée |
| span annoté | `annotations.jsonl` → `Annotation` | `identifier_type` ∈ {`DIRECT`, `QUASI`} depuis l'étiquette source |
| mode d'expression | `Annotation.expression_mode` | `EXPLICIT` / `NON_STANDARD` / `IMPLICIT` |
| régime de difficulté | `Document.meta.difficulty` | conservé tel quel, sert au reporting par difficulté |
| population de référence | `configs/populations/ratbench-us.yaml` | voir [SPEC-06 §4](../specifications/SPEC-06-population-et-risque.md) |
| risque gold | `combinations.jsonl` → `Combination.risk_true` | avec `source = "ratbench"` |

**Point d'attention** : la taxonomie source doit être mappée vers les codes
[SPEC-01](../specifications/SPEC-01-taxonomie-qi.md). Le mapping vit dans
`configs/datasets/ratbench.yaml`, section `label_map`, et toute étiquette non
mappée provoque une erreur de validation — **jamais** un silence.

## 11. Splits et protocole

- Reprendre les splits officiels du benchmark. Ne pas resplitter.
- Si aucun split officiel : split déterministe par `person_id` (jamais par
  document — sinon fuite entre train et test via le profil), seed 42, 70/15/15.
- Protocole d'évaluation : `official` uniquement si (a) volumétrie observée =
  volumétrie attendue, (b) checksum conforme, (c) licence connue. Sinon
  `sampled` ou `diagnostic`.

## 12. Plan d'implémentation de l'adaptateur

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Lire `eval/core/loaders/ratbench.py` de la V1 | note de format dans §4 |
| 2 | Localiser la source officielle (GitHub/HF) et sa licence | §5 et §6 renseignés |
| 3 | `scripts/download_ratbench.py` + checksum | `data/raw/ratbench/` + `sha256` |
| 4 | Écrire `label_map` complet dans `configs/datasets/ratbench.yaml` | mapping vers SPEC-01 |
| 5 | Implémenter `RatBenchAdapter(DatasetAdapter)` | `src/anonymisation/datasets/ratbench.py` |
| 6 | Normaliser vers `documents/annotations/profiles/combinations` | `data/processed/ratbench/*.jsonl` |
| 7 | Importer la population de référence | `configs/populations/ratbench-us.yaml` |
| 8 | Rejouer l'attaquant du papier, comparer les ordres de grandeur | rapport de non-régression |

## 13. Critères d'acceptation

- [ ] `anonv2 datasets validate ratbench` passe sans avertissement.
- [ ] Nombre de documents observés == `expected_documents` du manifeste.
- [ ] Aucune étiquette source non mappée.
- [ ] 100 % des `Annotation.start/end` retombent sur le texte
      (`text[start:end] == span_text`).
- [ ] Chaque `Document` référence un `person_id` existant dans `profiles.jsonl`.
- [ ] La population de référence permet de recalculer un `k_true` cohérent avec
      le risque gold, à tolérance documentée près.
- [ ] Le régime « non standard » produit un risque mesuré supérieur au régime
      « standard » (test de sanité reproduisant la tendance 44 % → 69 %).

## 14. Questions ouvertes

- Quelle est la licence exacte ? Bloquant pour publication.
- Quelles langues sont réellement couvertes, et avec quelle volumétrie par
  langue ?
- La population de référence est-elle distribuée avec le dataset, ou faut-il la
  reconstruire depuis des sources ACS/Census ?
- Le protocole d'attaque du papier est-il reproductible tel quel avec des
  modèles < 30 B ?

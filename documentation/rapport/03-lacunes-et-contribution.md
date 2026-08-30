# 03 — Lacunes, positionnement et protocole expérimental

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date** | 2026-08-30 |

---

## 1. Ce qui existe déjà

| Problème | État de la littérature |
|----------|------------------------|
| PII NER | Très mature |
| PII multilingue | Mature |
| Annotation QI dans le texte | Existe (TAB, IPI) |
| Inférence d'attributs personnels | Existe (SynthPAI, travaux ETH SRI) |
| Anonymisation par LLM | Existe (SEAL, Tau-Eval) |
| Attaque de ré-identification | Existe (RAT-Bench, AURA, InferLink) |
| Anonymisation guidée par le risque | Existe (PETRE) |
| Risque populationnel | Existe (ARX, Rocher et al.) |
| Compromis privacy / utility adaptatif | Existe (Tau-Eval, adaptive text anonymization) |

## 2. Ce qui manque

| Problème | État |
|----------|------|
| Benchmark QI pour le domaine **RH** | **très faible** |
| Benchmark QI pour le domaine **support** | **très faible** |
| Benchmark QI **en français** | faible |
| Benchmark **population-based européen** | faible |
| **Vérité terrain explicite sur les combinaisons de QI** | limité |
| **Calibration** du score de risque | peu standardisée |
| Correspondance explicite **risque → action** | fragmentée |
| Pipeline **end-to-end configurable** | **encore peu couvert** |
| Benchmark **multi-domaines FR/EN** | **opportunité** |

C'est l'intersection de ces neuf lignes qui définit l'espace de contribution.

## 3. Positionnement de la contribution

### 3.1 Formulation à ne plus utiliser

> « Premier système qui calcule le risque de ré-identification depuis du texte. »

Cette formulation n'est plus défendable en 2026 : RAT-Bench
[@krco2026ratbench] l'a démontré publiquement.

### 3.2 Formulation retenue

> **Un cadre multilingue, multi-domaines et configurable pour détecter les
> quasi-identifiants indirects dans le texte libre, estimer un risque
> combinatoire calibré relativement à une population de référence, et piloter
> automatiquement l'intensité d'anonymisation sous contrainte
> privacy-utility.**

Les quatre éléments qui portent la nouveauté :

1. **multi-domaines RH / forums / support**, là où la littérature est légale,
   clinique ou générique ;
2. **multilingue avec ancrage français / européen**, là où RAT-Bench est
   ancré sur des statistiques US ;
3. **vérité terrain explicite sur les combinaisons de QI** et métrique dédiée
   (QICR), là où les benchmarks évaluent des attributs isolés ;
4. **score calibré + politique configurable**, là où PETRE fournit un seuil
   unique et où les travaux LLM fournissent un score non calibré.

## 4. Trois contributions mesurables

### Contribution A — QI Detection

> Détecter les identifiants directs et indirects, y compris ceux exprimés
> implicitement.

**Métriques** : QI Recall (entity-level) · Macro-F1 par catégorie ·
**QI Combination Recall (QICR)**.

**Datasets** : TAB, IPI, SynthPAI, OpenPII, corpus RH/support internes.

### Contribution B — Combinatorial Risk Estimation

> Transformer une collection d'indices textuels en un risque de
> ré-identification calibré.

**Métriques** : MAE-risk · MAE-k / MALE-k · AUROC · AUPRC · Brier · ECE.

**Datasets** : RAT-Bench, corpus population-based interne.

### Contribution C — Risk-Adaptive Anonymization

> Choisir automatiquement l'opération d'anonymisation en fonction du risque.

**Métriques** : **Re-ID Success Rate** · risque résiduel (p95, max) ·
**Utility Retention** · latence.

**Datasets** : end-to-end sur l'ensemble de la batterie.

C'est cette troisième couche qui transforme le système en **framework** plutôt
qu'en simple détecteur de QI.

## 5. La suite de benchmarks

### Benchmark 1 — PII Detection

**Sources** : OpenPII / ai4privacy · JobStack · MultiCoNER II · éventuellement
MEDDOCAN.
**Mesures** : Precision · Recall · F1 · macro-F1 · F1 par langue.

### Benchmark 2 — Indirect QI Detection

**Sources** : TAB · IPI · SynthPAI · corpus RH · corpus support.
**Mesures** : QI span F1 · entity-level QI recall · F1 par catégorie ·
**QI Combination Recall**.

### Benchmark 3 — Risk Estimation

**Sources** : RAT-Bench · dataset population-based interne.
**Mesures** : MAE risk · MAE-k · AUROC · AUPRC · Brier · ECE · corrélation
entre risque prédit et risque réel.

### Benchmark 4 — End-to-End Anonymization

**Entrée** : document original.
**Sortie** : document anonymisé + score de risque + politique appliquée.

| Axe | Mesures |
|-----|---------|
| **Privacy** | direct leak rate · indirect leak rate · Re-ID Success Rate · top-1 attacker accuracy · k résiduel · risque p95 · risque max |
| **Utility** | BERTScore · similarité d'embeddings · task F1 · utility retention · évaluation humaine si nécessaire |
| **Efficiency** | latence par document · tokens/s · RAM CPU · VRAM · coût énergétique (optionnel) |

## 6. Le livrable de résultats : Privacy-Utility Operating Point

Ne pas publier « F1 = 91 % ». Publier une table de points de fonctionnement :

| Policy | Re-ID Risk | Utility | Latency |
|--------|-----------:|--------:|--------:|
| P0 | 31 % | 98 % | 100 ms |
| P1 | 17 % | 96 % | 220 ms |
| P2 | 8 % | 93 % | 500 ms |
| P3 | 3 % | 87 % | 1.2 s |
| P4 | 1 % | 74 % | 2.4 s |

*(Valeurs illustratives — format cible, pas des résultats.)*

C'est beaucoup plus représentatif d'un système industriel, et c'est le format
imposé par [SPEC-07 §6](../specifications/SPEC-07-metriques.md).

## 7. Seuils initiaux de risque

Ce ne sont **pas** des standards juridiques ; ce sont des points de départ
expérimentaux. Avec l'approximation prosecutor $R \approx 1/k$ :

| k estimé | Risque approx. | Niveau |
|---------:|---------------:|--------|
| ≥ 20 | ≤ 5 % | faible |
| 10–19 | 5–10 % | modéré |
| 5–9 | 10–20 % | élevé |
| 3–4 | 25–33 % | très élevé |
| 2 | 50 % | critique |
| 1 | 100 % | critique |

Ces valeurs correspondent aux paramètres couramment étudiés en k-anonymité :
k = 2, 3, 5, 10 → risques prosecutor de 50 %, 33 %, 20 %, 10 %
[@prasser2020arx].

**Avertissement.** Il est fortement déconseillé de limiter le moteur à
$R = 1/k$. Quand la population de référence est incomplète, il faut un modèle
plus riche ; les travaux de Rocher et al. [@rocher2019estimating] fournissent
une estimation par copule adaptée à ce cas. Détail :
[SPEC-06](../specifications/SPEC-06-population-et-risque.md).

## 8. Priorisation finale des datasets

| Dataset | Usage | Priorité |
|---------|-------|---------:|
| **RAT-Bench** | risque + ré-identification | **P0** |
| **TAB** | annotation QI + métriques privacy | **P0** |
| **IPI / MIMIC** | taxonomie QI | **P0** |
| **SynthPAI** | forums + inférence d'attributs | **P0** |
| **OpenPII 500k** | PII multilingue | **P0** |
| **Corpus RH interne/synthétique** | risque métier réel | **P0** |
| **Corpus support interne/synthétique** | risque métier réel | **P0** |
| JobStack | PII RH | P1 |
| MultiCoNER II | robustesse multilingue | P1 |
| MEDDOCAN | stress-test cross-domaine | P2 |

## 9. Prochaine étape

La formalisation du benchmark lui-même :

1. **schéma d'annotation QI unifié** RH / forum / support →
   [SPEC-01](../specifications/SPEC-01-taxonomie-qi.md) ;
2. **définition mathématique du k combinatoire** →
   [SPEC-06](../specifications/SPEC-06-population-et-risque.md) ;
3. **protocole de construction des populations de référence** →
   [SPEC-06 §4](../specifications/SPEC-06-population-et-risque.md) ;
4. **tableau exact des métriques avec formules et seuils** →
   [SPEC-07](../specifications/SPEC-07-metriques.md).

C'est ce qui permet ensuite de dériver proprement l'architecture du pipeline.

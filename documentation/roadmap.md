# Roadmap d'implémentation

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date** | 2026-08-30 |

Six lots. Chaque lot a un **critère de sortie** vérifiable ; on ne passe pas au
suivant sans l'avoir atteint.

---

## L0 — Cadrage et spécifications ✅ **fait**

| Livrable | État |
|----------|------|
| Rapport : cadrage, état de l'art, lacunes | ✅ |
| 11 fiches datasets | ✅ |
| 9 spécifications techniques | ✅ |
| Squelette de dépôt, manifestes d'exemple | ✅ |

**Sortie** : la documentation permet à quelqu'un d'autre d'implémenter les
adaptateurs sans poser de question de conception.

---

## L1 — Schéma et taxonomie (code)

**Objectif** : rendre SPEC-01 et SPEC-02 exécutables.

| # | Tâche | Fichier |
|---|-------|---------|
| 1.1 | Enums de la taxonomie (identifier_type, expression_mode, sensitivity, granularity, stability, subject) | `schema/taxonomy.py` |
| 1.2 | Codes de catégorie + validation | `schema/taxonomy.py` |
| 1.3 | Modèles Pydantic des 6 tables | `schema/models.py` |
| 1.4 | Lecture/écriture JSONL atomique | `schema/io.py` |
| 1.5 | Validateurs d'invariants I-DOC / I-ANN / I-PRO / I-CMB | `schema/validation.py` |
| 1.6 | Reprise `MetricValue`/`MetricStatus` de la V1 | `metrics/contracts.py` |
| 1.7 | **Lire les guidelines IPI et remplir la table de réconciliation** SPEC-01 §9 | doc |
| 1.8 | Micro-dataset de fixtures conforme SPEC-02 | `tests/fixtures/` |

**Critère de sortie**

- [ ] `pytest tests/unit` passe, sans aucune donnée téléchargée.
- [ ] Les fixtures valident tous les invariants.
- [ ] Un invariant volontairement violé fait échouer la validation avec le bon
      code d'erreur (test négatif).
- [ ] SPEC-01 §9 est remplie → SPEC-01 peut passer en `Gelé`.

> 1.7 est sur le chemin critique : la taxonomie conditionne tous les
> `label_map`. Le faire tard signifierait réécrire tous les manifestes.

---

## L2 — Registre et adaptateurs P0

**Objectif** : les cinq datasets P0 publics sont ingérés et valides.

| # | Tâche | Difficulté nouvelle introduite |
|---|-------|-------------------------------|
| 2.1 | `DatasetAdapter` (ABC), registre, manifeste Pydantic | — |
| 2.2 | Pipeline d'ingestion 5 étapes + CLI | — |
| 2.3 | Utilitaires `_hf.py`, `_split.py` | — |
| 2.4 | **Adaptateur OpenPII** | chaîne complète, cas facile |
| 2.5 | **Adaptateur SynthPAI** | profils latents, split par auteur, annotation sans offset |
| 2.6 | **Adaptateur TAB** | coréférence, multi-annotateurs, texte réel |
| 2.7 | **Adaptateur RAT-Bench** | population de référence, combinaisons, `k_true` |
| 2.8 | Adaptateur IPI (code seulement, données conditionnées à PhysioNet) | licence restrictive |
| 2.9 | `audit-licenses`, hook pre-commit | — |

**Critère de sortie** (= SPEC-04 §11)

- [ ] `anonv2 datasets list` affiche les 11 clés avec leur statut réel.
- [ ] Les 4 datasets P0 publics sont ingérés, validés, sans avertissement.
- [ ] Aucun `E-VAL-108` (fuite de split).
- [ ] Réingestion déterministe (identique bit à bit).
- [ ] `OTHER_QI` < 1 % partout.

**En parallèle et dès maintenant** : lancer la demande d'accès PhysioNet (CITI +
DUA) et la demande JobStack. Ce sont les seuls délais administratifs du projet.

---

## L3 — Populations et moteur de risque

**Objectif** : rendre SPEC-06 exécutable, du $k$ exact au risque calibré.

| # | Tâche |
|---|-------|
| 3.1 | Format de population + chargeur |
| 3.2 | Tables de normalisation (âge, géo, PCS-ESE, ISCED, semver) |
| 3.3 | Hiérarchies de généralisation |
| 3.4 | Calcul de $k$ exact (population énumérable) |
| 3.5 | Modèles prosecutor / journalist / marketer |
| 3.6 | Modèle copule pour populations incomplètes |
| 3.7 | Intervalles d'incertitude sur $\hat{k}$ |
| 3.8 | Calibration (isotonique / Platt) par domaine et langue |
| 3.9 | Portées document / thread / auteur, état d'historique |
| 3.10 | Construction de `fr-hr-2026`, `fr-general-2026`, `support-parc-2026` |

**Critère de sortie**

- [ ] Le modèle copule est validé **contre le $k$ exact du parc support** ;
      l'erreur est mesurée et documentée.
- [ ] $k_{author} \leq k_{thread} \leq k_{document}$ vérifié par test.
- [ ] ECE < 0.05 par domaine sur le split de calibration.
- [ ] `contributing_qi` est actionnable (généraliser un QI listé baisse le
      risque ; un QI non listé, non).

---

## L4 — Corpus internes

**Objectif** : produire HR-QI, Support-QI et Forum-QI (SPEC-05).

| # | Tâche |
|---|-------|
| 4.1 | Échantillonneur de profils stratifié par $k$ |
| 4.2 | Énumérateur de combinaisons + $k$ exact |
| 4.3 | Planificateur de documents (`qi_plan`, `forbidden_qi`, modes) |
| 4.4 | Générateur LLM local multi-modèles, multi-prompts |
| 4.5 | Contrôles C1 (complétude), C2 (localisation), **C3 (non-contamination)** |
| 4.6 | Étiquettes d'utilité |
| 4.7 | Campagne de contrôle humain 5 % |
| 4.8 | Gel, checksums, manifestes |

**Critère de sortie** (= SPEC-05 §13)

- [ ] Stratification des $k$ respectée à ±3 points.
- [ ] Modes d'expression respectés à ±5 points.
- [ ] Rejet humain < 10 %, contamination résiduelle < 2 %.
- [ ] Classifieurs d'utilité au-dessus de leur F1 de référence
      (routage support ≥ 0.85).

> 4.5 est le point de vigilance du lot. Un corpus contaminé par des QI non
> annotés donnerait un $k_{true}$ surestimé et fausserait toute la calibration
> de L3. Ne pas sous-dimensionner cet effort.

---

## L5 — Attaquants, politique, boucle end-to-end

**Objectif** : produire la première courbe privacy-utility complète.

| # | Tâche |
|---|-------|
| 5.1 | Attaquant A (LLM local), prompts versionnés |
| 5.2 | Attaquant B |
| 5.3 | Attaquant C (agent web) **avec gardes E1/E2 en code** |
| 5.4 | Moteur de politique (seuils → actions, critère Δrisk/Δutilité) |
| 5.5 | Politiques P0…P4 |
| 5.6 | Métriques niveaux 4 et 5, tâches d'utilité |
| 5.7 | Baselines : Presidio, GLiNER/XLM-R, petits LLM |
| 5.8 | Rapport de run au format SPEC-07 §10 |
| 5.9 | Tests de sanité S1–S6 |

**Critère de sortie**

- [ ] Le tableau Privacy-Utility Operating Point P0…P4 est produit sur les trois
      corpus internes.
- [ ] S1–S6 passent tous.
- [ ] La corrélation risque prédit / risque réalisé est calculée et publiée.
- [ ] L'attaquant C refuse de démarrer sur TAB (test de la garde E2).
- [ ] L'écart A → B → C est mesuré.

---

## Chemin critique

```
L1.7 (taxonomie IPI) ──→ L1 ──→ L2 ──→ L3 ──→ L4 ──→ L5
       │                         │
       │                         └──→ L3.10 (populations) est aussi prérequis de L4
       │
   demande PhysioNet (à lancer maintenant, hors chemin technique)
```

Deux dépendances à ne pas manquer :

1. **L1.7 avant tout `label_map`** — sinon réécriture de tous les manifestes.
2. **L3.10 (populations) avant L4** — on ne peut pas échantillonner des profils
   stratifiés par $k$ sans savoir calculer $k$.

## Décisions à prendre en cours de route

| Décision | Échéance | Défaut proposé |
|----------|----------|----------------|
| Publier ou non les corpus internes | fin L4 | Publier |
| Poursuivre ou abandonner l'accès MIMIC-III | fin L1 | Poursuivre la demande, ne pas bloquer |
| Modèle retenu pour l'attaquant B | début L5 | Le plus capable < 30 B disponible localement |
| Traduire un sous-ensemble SynthPAI en FR | fin L2 | À évaluer, coût modéré, apport réel |
| Campagne d'annotation humaine complète sur un sous-corpus | fin L4 | À arbitrer sur le coût |

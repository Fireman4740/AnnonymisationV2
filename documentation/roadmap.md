# Roadmap d'implémentation

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 2.0 |
| **Date** | 2026-08-30 |

**Révision 2.0** — deux changements majeurs par rapport à la v1.0 :

1. **PhysioNet / MIMIC-III abandonné.** Tous les corpus nécessaires sont déjà
   sur disque ([`datasets/inventaire-local.md`](datasets/inventaire-local.md)).
   Plus aucun délai administratif sur le chemin critique.
2. **Le pipeline d'anonymisation devient un livrable de premier rang**
   ([SPEC-10](specifications/SPEC-10-pipeline-anonymisation.md)), avec une
   contrainte dure issue de l'audit v1 : **noyau déterministe, hors ligne, LLM
   désactivé par défaut**.

---

## L0 — Cadrage et spécifications ✅ **fait**

| Livrable | État |
|----------|------|
| Rapport : cadrage, état de l'art, lacunes | ✅ |
| 16 fiches datasets + inventaire local | ✅ |
| 10 spécifications techniques (SPEC-01 → SPEC-10) | ✅ |
| Squelette de dépôt, manifestes, politiques P0..P4 | ✅ |

---

## L1 — Noyau exécutable

**Objectif** : rendre SPEC-01, SPEC-02 et le noyau déterministe de SPEC-10
exécutables, sans aucune donnée réelle.

| # | Tâche | État |
|---|-------|------|
| 1.1 | Enums et codes de la taxonomie (`schema/taxonomy.py`) | ✅ |
| 1.2 | Modèles Pydantic des 6 tables (`schema/models.py`) | ✅ |
| 1.3 | Lecture/écriture JSONL atomique et déterministe (`schema/io.py`) | 🔄 |
| 1.4 | Validateurs d'invariants `E-VAL-*` (`schema/validation.py`) | 🔄 |
| 1.5 | Split déterministe par groupe (`datasets/_split.py`) | 🔄 |
| 1.6 | Micro-dataset de fixtures | 🔄 |
| 1.7 | Détection déterministe : motifs, validateurs, règles QI, fusion | 🔄 |
| 1.8 | Transformation : masquage, pseudonymisation HMAC, généralisation | 🔄 |
| 1.9 | Moteur de politique P0..P4 | 🔄 |

**Critère de sortie**

- [ ] `python -m pytest tests/unit -q` passe sur un clone frais, **sans aucune
      donnée téléchargée**.
- [ ] Chaque invariant a un test positif **et** un test négatif.
- [ ] La phrase canonique (« moins de 30 ans, doctorant, arrêt maladie ») est
      détectée, planifiée et transformée de bout en bout.
- [ ] Deux écritures des mêmes enregistrements produisent des fichiers
      identiques bit à bit.

> **Note sur la taxonomie** : la table de réconciliation SPEC-01 §9 reste
> ouverte, mais elle ne dépend **plus** de MIMIC-III — les guidelines IPI se
> lisent dans la publication. Elle n'est donc plus sur le chemin critique, mais
> reste requise avant de figer SPEC-01.

---

## L2 — Ingestion et adaptateurs

**Objectif** : les corpus locaux sont normalisés au format SPEC-02 et validés.

| # | Tâche | Difficulté nouvelle introduite | État |
|---|-------|-------------------------------|------|
| 2.1 | Manifestes Pydantic, source `kind: local`, portabilité `ANONV2_V1_DATASETS` | — | 🔄 |
| 2.2 | Pipeline d'ingestion 5 étapes + lock + rapport de validation | — | 🔄 |
| 2.3 | CLI argparse (`list`, `describe`, `ingest`, `validate`, `stats`, `audit-licenses`) | — | 🔄 |
| 2.4 | **Corpus QI français** (`quasifr`) | chaîne complète, cas simple, **français** | ⬜ |
| 2.5 | **PersonalReddit** | profil latent, split par auteur, axe de difficulté | ⬜ |
| 2.6 | **TAB officiel** | coréférence, multi-annotateurs, texte réel | ⬜ |
| 2.7 | **SupportTicketsReal** | domaine support, multilingue, tâche d'utilité | ⬜ |
| 2.8 | **RAT-Bench + PUMS** | population de référence, `k` réel | ⬜ |
| 2.9 | DB-bio, CleanCoNLL, BitextSupportSynthetic | BIO → offsets caractères | ⬜ |

**Critère de sortie**

- [ ] `anonv2 datasets list` affiche tous les corpus avec leur statut réel.
- [ ] Les 5 corpus P0 locaux sont ingérés et valides, **sans avertissement**.
- [ ] Aucun `E-VAL-108` (fuite de split) sur aucun corpus.
- [ ] Réingestion déterministe (identique bit à bit).
- [ ] Taux d'`OTHER_QI` < 1 % partout.
- [ ] Le chemin des corpus est surchargeable par `ANONV2_V1_DATASETS` (le dépôt
      ne doit pas dépendre d'une seule machine).

---

## L3 — Pipeline de bout en bout (profil `deterministic`)

**Objectif** : la commande `predict` traite **100 % des documents de tous les
corpus d'évaluation, avec 0 % d'erreur**. C'est la demande principale.

| # | Tâche |
|---|-------|
| 3.1 | Orchestrateur des 8 étapes de SPEC-10, avec `StageTrace` |
| 3.2 | Étape 6 VALIDATE : placeholders, motifs interdits, **fuite de valeurs gold** |
| 3.3 | `anonv2 predict` → `predictions.jsonl` + `traces.jsonl` + lock |
| 3.4 | `anonv2 score` → scorecard, **sans relancer aucun modèle** |
| 3.5 | Métriques niveau 1 (span P/R/F1/F2, entity-level recall, par langue/domaine/mode) |
| 3.6 | Gestion d'erreur conforme à C4 : document en erreur exclu des métriques, compté à part |

**Critère de sortie** (= SPEC-10 §10)

- [ ] `anonv2 predict --profile deterministic` : **0 % d'erreur** sur chaque corpus.
- [ ] Deux exécutions produisent des prédictions identiques bit à bit.
- [ ] Aucune valeur gold d'identifiant direct ne subsiste dans le texte anonymisé.
- [ ] Aucun appel réseau en profil `deterministic` (test socket désactivé).
- [ ] Tests de sanité S1–S3 de SPEC-07 §11.

---

## L4 — Populations et moteur de risque

**Objectif** : remplacer l'estimateur provisoire par un vrai moteur de risque.

| # | Tâche |
|---|-------|
| 4.1 | Chargeur de population + tables de normalisation (âge, géo, PCS/ISCED, semver) |
| 4.2 | Hiérarchies de généralisation branchées sur le moteur |
| 4.3 | **PUMS** comme population de référence — attention : `k` pondéré par `PWGTP`, pas un comptage de lignes |
| 4.4 | Modèles prosecutor / journalist / marketer |
| 4.5 | Modèle copule pour populations incomplètes (FR) |
| 4.6 | Intervalles d'incertitude `[k_low, k_high]` ; décision sur la borne haute du risque |
| 4.7 | Calibration (isotonique / Platt) par domaine et par langue |
| 4.8 | Portées document / thread / auteur, état d'historique |
| 4.9 | Populations `fr-hr-2026`, `fr-general-2026`, `support-parc-2026` |

**Critère de sortie**

- [ ] `k` calculé sur PUMS **en sommant les poids `PWGTP`** — ignorer ce point
      sous-estimerait `k` d'environ deux ordres de grandeur.
- [ ] Le modèle copule est validé contre un `k` exact ; l'erreur est publiée.
- [ ] $k_{author} \leq k_{thread} \leq k_{document}$ vérifié par test.
- [ ] ECE < 0.05 par domaine.
- [ ] L'estimateur provisoire `NaiveRiskEstimator` est **retiré** des chemins de
      production, ou marqué `PROXY` de façon inamovible.

---

## L5 — Corpus internes générés

**Objectif** : produire HR-QI, Support-QI et Forum-QI (SPEC-05). C'est la
contribution scientifique du projet.

| # | Tâche |
|---|-------|
| 5.1 | Échantillonneur de profils stratifié par `k` |
| 5.2 | Énumérateur de combinaisons + `k` exact |
| 5.3 | Planificateur de documents (`qi_plan`, `forbidden_qi`, modes d'expression) |
| 5.4 | Générateur LLM local multi-modèles, multi-prompts |
| 5.5 | Contrôles C1 complétude, C2 localisation, **C3 non-contamination** |
| 5.6 | Étiquettes d'utilité |
| 5.7 | Contrôle humain sur 5 % |

**Critère de sortie** : stratification des `k` à ±3 points, modes d'expression à
±5 points, rejet humain < 10 %, contamination résiduelle < 2 %.

> 5.5 est le point de vigilance : un corpus contaminé par des QI non annotés
> donnerait un `k_true` surestimé et fausserait toute la calibration de L4.

---

## L6 — Attaquants, LLM, boucle complète

| # | Tâche |
|---|-------|
| 6.1 | Passerelle LLM conforme à SPEC-10 §6 : schéma validé, timeout, retries, **réponse vide = erreur** |
| 6.2 | Rôles séparés : reviewer / verifier / auditor / rewriter |
| 6.3 | Attaquant A (LLM local) — baseline de comparaison : les champs `guess`/`guess_correctness` de PersonalReddit |
| 6.4 | Attaquant B |
| 6.5 | Attaquant C (agent web) **avec gardes E1/E2 en code** |
| 6.6 | Boucle de réécriture unique, bornée, avec détection de non-progression |
| 6.7 | Métriques niveaux 4 et 5, tâches d'utilité (routage `queue`, intention `intent`) |
| 6.8 | Tableau Privacy-Utility Operating Point P0..P4 |

**Critère de sortie**

- [ ] Le tableau P0..P4 est produit sur les corpus internes **et** sur
      SupportTicketsReal.
- [ ] S1–S6 de SPEC-07 §11 passent tous.
- [ ] L'attaquant C **refuse de démarrer** sur TAB, DB-bio, SupportTicketsReal
      et CleanCoNLL (test de la garde E2).
- [ ] Corrélation risque prédit / risque réalisé calculée et publiée.

---

## Chemin critique révisé

```
L1 (noyau) ──→ L2 (ingestion) ──→ L3 (pipeline 0 % erreur) ──→ L4 (risque) ──→ L5 (corpus) ──→ L6 (attaque)
                                                                     │
                                                          PUMS déjà disponible
```

Plus aucune dépendance administrative. Les seules dépendances sont techniques,
et la contrainte la plus forte reste : **L3 doit atteindre 0 % d'erreur avant
d'introduire le moindre appel LLM** — c'est précisément l'inverse de l'ordre
suivi par la v1, et la raison de son échec de campagne.

## Décisions à prendre en cours de route

| Décision | Échéance | Défaut proposé |
|----------|----------|----------------|
| Publier ou non les corpus internes | fin L5 | Publier |
| Statut de PersonalReddit : données réelles ou synthétiques ? | **résolu, G-6** | Le cache local `Reddit_synthetic/` est la release synthétique ETH SRI (`synthetic: true`) ; il est distinct du PersonalReddit réel non distribué. Garde E2 non applicable au cache. |
| Télécharger OpenPII pour le F1 par langue | fin L2 | Oui, c'est peu coûteux et c'est la seule couverture FR/multilingue de PII |
| Modèle retenu pour l'attaquant B | début L6 | Le plus capable < 30 B disponible localement |
| Campagne d'annotation humaine sur un sous-corpus | fin L5 | À arbitrer sur le coût |

# Backlog — pipeline d'évaluation fiable et solide

| | |
|---|---|
| **Statut** | Actif |
| **Version** | 1.1 |
| **Date** | 2026-08-30 |
| **Objectif du lot** | Un pipeline d'évaluation qui tourne de bout en bout sur **tous** les corpus, avec **0 % d'erreur**, de façon **déterministe** et **reproductible**, et qui **mesure la protection réelle** et non seulement la détection |

---

## 1. Ce qui existe déjà (ne pas réimplémenter)

183 tests passent. Ces briques sont livrées et testées :

| Module | Contenu | Tests |
|--------|---------|------:|
| `schema/taxonomy.py` | 4 axes, 47 codes, `ALLOWED_ACTIONS` | 12 |
| `schema/models.py` | 6 tables Pydantic, invariants I-ANN/I-CMB | — |
| `schema/io.py` | JSONL atomique, déterministe, sha256 | 19 |
| `schema/validation.py` | 11 contrôles `E-VAL-*` | 35 |
| `datasets/_split.py` | Split déterministe par groupe | 13 |
| `detect/` | Validateurs, motifs, règles QI FR/EN, fusion | 62 |
| `transform/` | HMAC, masquage, généralisation, application | 30 |
| `policy/` | Politiques P0..P4, moteur Δrisque/Δutilité | 12 |
| `tests/fixtures/micro/` | Micro-dataset RH conforme SPEC-02 | — |

## 2. Ce qui manque

```
  ┌──────────────────────────────────────────────────────────────┐
  │ EPIC A — Ingestion          manifeste, source locale, CLI     │  ← bloquant
  ├──────────────────────────────────────────────────────────────┤
  │ EPIC B — Adaptateurs        6 corpus locaux                   │
  ├──────────────────────────────────────────────────────────────┤
  │ EPIC C — Orchestration      8 étapes, predict, score          │
  ├──────────────────────────────────────────────────────────────┤
  │ EPIC D — Métriques          niveau 1 + scorecard + statuts    │
  ├──────────────────────────────────────────────────────────────┤
  │ EPIC E — Fiabilité          déterminisme, sanité, CI          │
  ├──────────────────────────────────────────────────────────────┤
  │ EPIC F — Dettes             à solder avant de figer les specs │
  ├──────────────────────────────────────────────────────────────┤
  │ EPIC G — Révision 2026      multi-sujets, CPR/IPR, TRIR       │  ← mesure ce qui compte
  └──────────────────────────────────────────────────────────────┘
```

| Épic | Fichier | Tickets | Effort |
|------|---------|--------:|-------:|
| A — Ingestion | [`EPIC-A-ingestion.md`](EPIC-A-ingestion.md) | 5 | ~3 j |
| B — Adaptateurs | [`EPIC-B-adaptateurs.md`](EPIC-B-adaptateurs.md) | 6 | ~5 j |
| C — Orchestration | [`EPIC-C-orchestration.md`](EPIC-C-orchestration.md) | 5 | ~4 j |
| D — Métriques | [`EPIC-D-metriques.md`](EPIC-D-metriques.md) | 4 | ~3 j |
| E — Fiabilité | [`EPIC-E-fiabilite.md`](EPIC-E-fiabilite.md) | 5 | ~2 j |
| F — Dettes | [`EPIC-F-dettes.md`](EPIC-F-dettes.md) | 5 | ~2 j |
| **G — Révision 2026** | [`EPIC-G-revision-2026.md`](EPIC-G-revision-2026.md) | **6** | **~4 j** |

**Hors périmètre de ce backlog** : moteur de risque calibré (SPEC-06, lot L4),
génération des corpus internes (SPEC-05, lot L5), attaquants et LLM (SPEC-08,
lot L6). Ils ne sont pas nécessaires à un pipeline d'évaluation fiable, et les
mêler ici reproduirait l'erreur de la v1.

## 3. Tableau de bord

| # | Ticket | Prio | Dépend de | État |
|---|--------|:----:|-----------|:----:|
| **A-1** | Manifestes Pydantic + source `kind: local` | P0 | — | ⬜ |
| **A-2** | Pipeline d'ingestion 5 étapes + lock | P0 | A-1 | ⬜ |
| **A-3** | CLI argparse (la CLI actuelle est cassée) | P0 | A-2 | ⬜ |
| **A-4** | Utilitaire BIO → offsets caractères | P1 | — | ⬜ |
| **A-5** | Câblage du registre d'adaptateurs | P0 | A-1 | ⬜ |
| **B-1** | Adaptateur `quasifr` (FR) | P0 | A-2, A-5 | ⬜ |
| **B-2** | Adaptateur `personalreddit` | P0 | B-1 | ⬜ |
| **B-3** | Adaptateur `tab` (officiel) | P0 | B-2 | ⬜ |
| **B-4** | Adaptateurs `supporttickets` + `bitextsupport` | P0 | B-1 | ⬜ |
| **B-5** | Adaptateur `ratbench` + PUMS | P0 | B-3 | ⬜ |
| **B-6** | Adaptateurs `dbbio` + `conll2003` | P1 | A-4, B-1 | ⬜ |
| **C-1** | Orchestrateur 8 étapes + `StageTrace` | P0 | A-2 | ✅ |
| **C-2** | Étape VALIDATE + contrôle de fuite gold | P0 | C-1 | ✅ |
| **C-3** | `anonv2 predict` | P0 | C-1, A-3 | ✅ |
| **C-4** | `anonv2 score` (sans relancer les modèles) | P0 | C-3, D-1 | ✅ |
| **C-5** | Comptabilité d'erreur C4 | P0 | C-3 | ✅ |
| **D-1** | Métriques niveau 1 + ventilations | P0 | C-3 | ✅ |
| **D-2** | Contrats `MetricValue` / `MetricStatus` | P0 | — | ✅ |
| **D-3** | Métriques officielles TAB | P1 | B-3, D-1 | ⬜ |
| **D-4** | Scorecard + manifeste de run | P0 | D-1, D-2 | ✅ |
| **E-1** | Non-régression déterministe bout en bout | P0 | C-3 | ⬜ |
| **E-2** | Tests de sanité S1–S3 | P0 | C-3, D-1 | ⬜ |
| **E-3** | Golden test sur le micro-dataset | P0 | C-3 | ⬜ |
| **E-4** | CI 4 étages + marqueurs pytest | P1 | E-1 | ⬜ |
| **E-5** | Garde « aucun accès réseau » en profil déterministe | P1 | C-3 | ⬜ |
| **F-1** | Réconcilier SPEC-10 et `configs/llm/backends.yaml` | P0 | — | ⬜ |
| **F-2** | Table de réconciliation SPEC-01 §9 | P1 | — | ⬜ |
| **F-3** | Mesurer le taux d'`OTHER_QI` réel | P1 | B-3 | ⬜ |
| **F-4** | Solder les « à confirmer » des fiches | P2 | B-* | ⬜ |
| **F-5** | Retirer le `NaiveRiskEstimator` des chemins publiés | P1 | D-2 | ⬜ |
| **G-1** | Adaptateurs `spia` + `panorama` (multi-sujets) | P0 | B-3 | ⬜ |
| **G-2** | **CPR / IPR** — métriques principales | P0 | G-1, D-2 | ⬜ |
| **G-3** | TRIA / TRIR | P1 | D-2, G-1 | ⬜ |
| **G-4** | Mean Utility | P1 | D-2 | ⬜ |
| **G-5** | Partial match + ER_di / ER_qi | P0 | D-1 | ⬜ |
| **G-6** | Trancher le statut de PersonalReddit | P0 | — | ⬜ |

## 4. Chemin critique

```
A-1 ──→ A-2 ──→ A-3 ──→ C-3 ──→ C-4 ──→ [PIPELINE FIABLE]
  │       │              ↑        ↑
  └─ A-5 ─┴─→ B-1 ──→ B-2/B-3/B-4/B-5
                              │
                     C-1 ──→ C-2 ──→ C-5
                              │
                     D-2 ──→ D-1 ──→ D-4
                                      │
                              E-1/E-2/E-3

G-1 ──→ G-2 (CPR/IPR)   ← mesure la protection réelle, pas la détection
D-1 ──→ G-5 (ER_di/ER_qi)
```

**A-1 est le goulot d'étranglement** : sans manifeste, aucun adaptateur ne peut
être chargé. À faire en premier, seul.

Ordre recommandé, chaque étape n'introduisant **qu'une** difficulté nouvelle :

| Vague | Tickets | Parallélisable |
|------:|---------|----------------|
| 1 | A-1, D-2, F-1 | oui (fichiers disjoints) |
| 2 | A-2, A-4, A-5 | oui |
| 3 | A-3, B-1 | oui |
| 4 | B-2, B-4, C-1 | oui |
| 5 | B-3, C-2, C-3, D-1 | partiellement |
| 6 | B-5, B-6, C-4, C-5, D-4 | oui |
| 7 | E-1..E-5, D-3, F-2..F-5 | oui |
| 8 | G-1, G-5, G-6 | oui |
| 9 | G-2, G-3, G-4 | oui |

## 5. Définition de « terminé »

Un ticket n'est terminé que si **tous** ces points sont vrais :

- [ ] `python -m pytest tests -q` passe intégralement, sans régression.
- [ ] Les tests couvrent le cas nominal **et** au moins un cas d'échec
      (test négatif). Sans test négatif, on ne sait pas si le contrôle marche.
- [ ] Aucune valeur par défaut silencieuse : toute anomalie lève une exception
      dont le message **nomme** le fichier, la ligne ou l'identifiant fautif.
- [ ] Les commentaires et docstrings sont en français, les identifiants
      techniques en anglais.
- [ ] La docstring de module cite la section de spec implémentée.
- [ ] Aucune donnée n'est versionnée (règle L1 de SPEC-09).
- [ ] Le code reste compatible **Python 3.10** et n'ajoute aucune dépendance
      hors `pydantic`, `pyyaml`, `numpy`, `pandas`, `pyarrow`, `scipy`.

## 6. Critère de sortie du backlog

Le pipeline d'évaluation est déclaré fiable quand :

- [ ] `anonv2 datasets ingest --all` : les 6 corpus locaux sont ingérés et
      validés **sans avertissement**.
- [ ] Aucun `E-VAL-108` (fuite de split) sur aucun corpus.
- [ ] `anonv2 predict --profile deterministic` : **0 % de documents en erreur**
      sur chacun des 6 corpus.
- [ ] Deux exécutions successives produisent des `predictions.jsonl`
      **identiques bit à bit**.
- [ ] `anonv2 score` produit une scorecard sans relancer aucun modèle.
- [ ] Chaque métrique porte son `status` (`OFFICIAL` / `SAMPLED` /
      `DIAGNOSTIC` / `PROXY`) et sa ventilation par langue, domaine et mode
      d'expression.
- [ ] Les tests de sanité S1–S3 passent.
- [ ] Aucun appel réseau en profil déterministe.
- [ ] Un tiers peut reproduire un run depuis le seul `manifest.lock.json`.
- [ ] **CPR et IPR sont produits** sur SPIA, et situés par rapport aux valeurs
      publiées (un masqueur NER doit y obtenir un CPR de l'ordre de 0,33).
- [ ] **ER_di / ER_qi** sont produits au niveau entité, et diffèrent du rappel
      span-level.
- [ ] Le statut réel/synthétique de PersonalReddit est tranché.

## 7. Principe directeur du lot

> **0 % d'erreur en déterministe avant le moindre appel LLM.**

La campagne v1 a produit 84 % d'erreurs sur `anonymization`, 100 % sur DB-bio et
100 % sur TAB, puis a publié des « F1 » qui n'étaient que des taux d'échec
déguisés. Aucun ticket de ce backlog n'introduit d'appel LLM, et aucun ne doit
en introduire tant que le critère de sortie §6 n'est pas atteint.

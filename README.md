# AnnonymisationV2 — Détection de quasi-identifiants et anonymisation pilotée par le risque

> Cadre multilingue et multi-domaines (**RH · forums · support**) pour détecter les
> quasi-identifiants (QI) **directs et indirects** dans du texte libre, estimer un
> **risque de ré-identification combinatoire calibré** relativement à une population de
> référence, et piloter automatiquement l'intensité d'anonymisation sous contrainte
> **privacy / utility**. Modèles **locaux < 30 B**.

---

## 1. Le problème en une phrase

Un système de PII classique fait :

```
texte → PERSON / EMAIL / PHONE / ADDRESS → masquage
```

Ce projet fait :

```
texte → identifiants explicites + implicites → QI individuels → combinaisons de QI
      → population compatible → probabilité de ré-identification → décision d'anonymisation
      → validation par attaque
```

Exemple canonique :

> « j'ai moins de 30 ans et je suis doctorant et je cherche comment mettre un arrêt maladie »

Aucun attribut n'est identifiant isolément. La combinaison
`{âge < 30, doctorant, démarche RH}` peut l'être, si la classe d'équivalence
correspondante dans la population de référence est petite.

## 2. Architecture d'évaluation cible

```
                    DOCUMENT
                       │
                       ▼
              ┌──────────────────┐
              │ 1. QI detection  │  span + catégorie
              └────────┬─────────┘
                       ▼
             ┌─────────────────────┐
             │ 2. QI aggregation   │  entité + document + auteur
             └──────────┬──────────┘
                        ▼
             ┌─────────────────────┐
             │ 3. Risk engine      │  k / k probabiliste / risque calibré
             └──────────┬──────────┘
                        ▼
              ┌───────────────────┐
              │ 4. Policy engine  │  seuils configurables
              └────────┬──────────┘
          ┌────────────┼────────────┐
          ▼            ▼            ▼
      KEEP         GENERALIZE    SUPPRESS
          └────────────┼────────────┘
                       ▼
                  TEXTE ANONYMISÉ
              ┌────────┴─────────┐
              ▼                  ▼
       Privacy attack         Utility
       R_succ, leak rate      Task F1, retention
```

## 3. Métriques principales

Le F1 de détection **n'est pas** la métrique principale du projet.

| Rang | Métrique                                    | Sens |
|-----:|---------------------------------------------|------|
| 1    | **Residual Re-Identification Risk** (`R_succ`) | ↓ mieux |
| 2    | **Utility Retention**                       | ↑ mieux |
| 3    | **QI Combination Recall (QICR)**            | ↑ mieux, métrique de diagnostic |
| 4    | Calibration du risque (ECE, Brier, MAE-k)   | ↓ mieux |
| 5    | Span P/R/F1 par catégorie, langue, domaine  | diagnostic |

Détail complet : [`documentation/specifications/SPEC-07-metriques.md`](documentation/specifications/SPEC-07-metriques.md).

## 4. Documentation

Tout est dans [`documentation/`](documentation/README.md) :

| Bloc | Contenu |
|------|---------|
| [`rapport/`](documentation/rapport/) | Cadrage, état de l'art (30 août 2026), lacunes et positionnement de la contribution |
| [`datasets/`](documentation/datasets/README.md) | Une fiche détaillée par jeu de données (11 fiches) + tableau de priorisation et licences |
| [`specifications/`](documentation/specifications/README.md) | 9 spécifications techniques : taxonomie QI, schéma de données, registre/adaptateurs, ingestion, génération synthétique, moteur de risque, métriques, attaquants, qualité/CI |
| [`roadmap.md`](documentation/roadmap.md) | Séquencement de l'implémentation, lot par lot |

**Point d'entrée pour implémenter les datasets** :
[`SPEC-02`](documentation/specifications/SPEC-02-schema-donnees.md) →
[`SPEC-03`](documentation/specifications/SPEC-03-registre-et-adaptateurs.md) →
[`SPEC-04`](documentation/specifications/SPEC-04-pipeline-ingestion.md).

## 5. Structure du dépôt

```
AnnonymisationV2/
├── documentation/          # Rapport, fiches datasets, spécifications (source de vérité)
├── configs/
│   ├── datasets/           # Un manifeste YAML par dataset (source, licence, checksum, splits)
│   ├── populations/        # Descripteurs des populations de référence (INSEE, ACS, ...)
│   └── policy/             # Politiques d'anonymisation (seuils risque → action)
├── src/anonymisation/
│   ├── schema/             # Contrats de données + taxonomie QI (SPEC-01, SPEC-02)
│   ├── datasets/           # Registre + adaptateurs (SPEC-03, SPEC-04)
│   ├── risk/               # k combinatoire, modèles de risque (SPEC-06)
│   ├── metrics/            # Les 5 niveaux de métriques (SPEC-07)
│   ├── policy/             # Moteur de politique risque → action
│   ├── attack/             # Attaquants A/B/C (SPEC-08)
│   └── cli/                # Points d'entrée ligne de commande
├── data/                   # Non versionné (voir .gitignore) — géré par manifestes
├── scripts/                # Téléchargement, préparation, vérification d'intégrité
└── tests/
```

## 6. État d'avancement

| Lot | Sujet | État |
|-----|-------|------|
| L0  | Cadrage, état de l'art, spécifications | ✅ fait |
| L1  | Schéma de données + taxonomie QI (code) | ⬜ à faire |
| L2  | Registre + adaptateurs P0 (OpenPII, TAB, SynthPAI, RAT-Bench) | ⬜ à faire |
| L3  | Moteur de risque + populations de référence | ⬜ à faire |
| L4  | Corpus internes RH / support / forums | ⬜ à faire |
| L5  | Attaquants + boucle end-to-end | ⬜ à faire |

Voir [`documentation/roadmap.md`](documentation/roadmap.md).

## 7. Rapport à la V1

La V1 (`../Anonymisation`) fournit un pipeline LangGraph regex + NER + LLM et des
adaptateurs TAB / RAT-Bench / PersonalReddit. La V2 **ne le remplace pas** : elle
reprend ses conventions de contrats (`DatasetManifest`, `MetricValue`,
`MetricStatus`) et ajoute la couche manquante — QI indirects, **k combinatoire**,
score calibré, politique configurable. Le portage éventuel des adaptateurs V1 est
traité dans [`SPEC-03 §7`](documentation/specifications/SPEC-03-registre-et-adaptateurs.md).

## 8. Licence

Code : MIT (voir [LICENSE](LICENSE)).
Jeux de données tiers : licences propres, résumées dans
[`documentation/datasets/README.md`](documentation/datasets/README.md).
**Aucune donnée sous licence restrictive (MIMIC-III, MEDDOCAN, corpus internes)
ne doit être versionnée dans ce dépôt.**

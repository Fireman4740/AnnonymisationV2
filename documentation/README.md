# Documentation — AnnonymisationV2

Cette documentation est la **source de vérité** du projet. Le code doit s'y conformer,
pas l'inverse. Toute divergence constatée entre le code et une spécification est un
bug de l'un ou de l'autre, à trancher explicitement.

Date de référence de l'état de l'art : **30 août 2026**.

---

## 1. Rapport scientifique

| Document | Contenu |
|----------|---------|
| [`rapport/01-cadrage-et-problematique.md`](rapport/01-cadrage-et-problematique.md) | Définition formelle du problème, périmètre, contraintes, modèle de menace, vocabulaire |
| [`rapport/02-etat-de-l-art.md`](rapport/02-etat-de-l-art.md) | État de l'art complet : datasets, métriques, systèmes existants (TAB, IPI, SynthPAI, RAT-Bench, PETRE, ARX, Tau-Eval, SEAL, AURA, InferLink) |
| [`rapport/03-lacunes-et-contribution.md`](rapport/03-lacunes-et-contribution.md) | Ce qui existe / ce qui manque, positionnement de la contribution, protocole expérimental en 3 contributions mesurables |
| [`rapport/references.bib`](rapport/references.bib) | Bibliographie BibTeX |

## 2. Jeux de données

[`datasets/README.md`](datasets/README.md) — index, tableau de priorisation, matrice de
couverture, tableau des licences.

Une fiche par dataset, toutes au **même format** (identité, contenu, structure,
accès, licence, couverture, apport, limites, mapping vers le schéma interne,
plan d'implémentation, critères d'acceptation) :

**Priorité P0**
- [`rat-bench.md`](datasets/rat-bench.md) — benchmark end-to-end risque de ré-identification
- [`tab.md`](datasets/tab.md) — annotation QI de référence + métriques privacy-oriented
- [`ipi-mimic.md`](datasets/ipi-mimic.md) — taxonomie des identifiants indirects
- [`synthpai.md`](datasets/synthpai.md) — inférence d'attributs personnels, domaine forums
- [`openpii-500k.md`](datasets/openpii-500k.md) — PII multilingue (dont français)
- [`hr-qi-bench.md`](datasets/hr-qi-bench.md) — corpus RH interne (à construire)
- [`support-qi-bench.md`](datasets/support-qi-bench.md) — corpus support interne (à construire)
- [`forum-qi-bench.md`](datasets/forum-qi-bench.md) — corpus forums FR (à construire)

**Priorité P1 / P2**
- [`jobstack.md`](datasets/jobstack.md) — PII explicite dans les offres d'emploi (P1)
- [`multiconer2.md`](datasets/multiconer2.md) — robustesse multilingue et texte bruité (P1)
- [`meddocan.md`](datasets/meddocan.md) — stress-test cross-domaine espagnol (P2)

## 3. Spécifications techniques

[`specifications/README.md`](specifications/README.md) — index et ordre de lecture.

| Spec | Titre | Dépend de |
|------|-------|-----------|
| [SPEC-01](specifications/SPEC-01-taxonomie-qi.md) | Taxonomie unifiée des quasi-identifiants | — |
| [SPEC-02](specifications/SPEC-02-schema-donnees.md) | Schéma de données interne (documents, spans, profils, populations) | SPEC-01 |
| [SPEC-03](specifications/SPEC-03-registre-et-adaptateurs.md) | Registre de datasets et contrat d'adaptateur | SPEC-02 |
| [SPEC-04](specifications/SPEC-04-pipeline-ingestion.md) | Pipeline d'ingestion : acquisition, normalisation, validation, cache | SPEC-03 |
| [SPEC-05](specifications/SPEC-05-generation-corpus-synthetiques.md) | Génération des corpus RH / support / forums à profil latent | SPEC-02 |
| [SPEC-06](specifications/SPEC-06-population-et-risque.md) | Populations de référence, k combinatoire, modèles de risque | SPEC-01, SPEC-02 |
| [SPEC-07](specifications/SPEC-07-metriques.md) | Les 5 niveaux de métriques et leurs formules | SPEC-06 |
| [SPEC-08](specifications/SPEC-08-attaquants.md) | Modèles d'attaquants A / B / C et protocole d'attaque | SPEC-07 |
| [SPEC-09](specifications/SPEC-09-qualite-licences-ci.md) | Qualité des données, conformité des licences, CI | toutes |

## 4. Roadmap

[`roadmap.md`](roadmap.md) — lots L0 → L5, critères de sortie de chaque lot.

## 5. Annexes

- [`annexes/glossaire.md`](annexes/glossaire.md) — vocabulaire (QI, k-anonymité, prosecutor/journalist/marketer risk, linkage, inference).
- [`annexes/notations.md`](annexes/notations.md) — notations mathématiques utilisées dans les specs.

---

## Conventions de la documentation

1. **Langue** : français pour la rédaction, anglais pour les identifiants techniques
   (noms de champs, de classes, de métriques).
2. **Nommage** : `SPEC-NN-sujet.md` pour les specs, `kebab-case.md` pour les fiches datasets.
3. **Statut** : chaque spec porte un en-tête `Statut` ∈ {`Brouillon`, `Stable`, `Gelé`, `Obsolète`}
   et une `Version`. Une spec `Stable` ne change pas sans incrémenter sa version et
   mettre à jour la section « Journal des modifications ».
4. **Traçabilité** : toute affirmation issue de la littérature porte une référence
   dans [`rapport/references.bib`](rapport/references.bib).
5. **Vérification** : les identifiants arXiv/DOI et volumétries cités proviennent de
   l'état de l'art du 30 août 2026. Ils sont marqués `[à revérifier]` lorsqu'ils
   n'ont pas été reconfirmés à la source depuis. Ne pas les propager dans une
   publication sans revérification.

# AnnonymisationV2 — instructions agent

Détection de quasi-identifiants (QI) et anonymisation pilotée par le risque de
ré-identification. Domaines : **RH, forums, support**. Multilingue (FR/EN).
Contrainte projet : **modèles locaux < 30 B**.

La documentation est **normative** : le code s'y conforme, pas l'inverse. Une
divergence entre code et spécification est un défaut à trancher explicitement,
jamais à ignorer en silence.

---

## Avant de coder — les 3 documents à lire

| Tâche | Lire d'abord |
|---|---|
| **Ajouter un pipeline / système d'anonymisation** | **[documentation/guides/creer-un-pipeline.md](documentation/guides/creer-un-pipeline.md)** ← le guide complet |
| Ajouter un corpus | [SPEC-03](documentation/specifications/SPEC-03-registre-et-adaptateurs.md) puis [SPEC-04](documentation/specifications/SPEC-04-pipeline-ingestion.md) |
| Toucher aux métriques | [SPEC-07](documentation/specifications/SPEC-07-metriques.md) |

Index général : [documentation/README.md](documentation/README.md).

## La règle d'or

> **Aucune valeur par défaut silencieuse.**

Étiquette non mappée, licence inconnue, volumétrie divergente, offset qui ne
retombe pas sur le texte, réponse LLM vide : le système **échoue bruyamment**.
Il ne devine pas. Cette règle prime sur la commodité de développement — c'est
elle qui protège la validité de tout chiffre publié.

## Cinq contraintes normatives (SPEC-10 §2)

Issues de l'échec documenté de la v1 (84 à 100 % d'erreurs déguisées en
métriques) :

| # | Contrainte |
|---|---|
| **C1** | Le noyau est **déterministe et hors ligne** : un pipeline complet tourne sans LLM, sans GPU, sans réseau. |
| **C2** | Les LLM sont des étapes **optionnelles, désactivées par défaut**. |
| **C3** | Une réponse LLM vide n'est **jamais** « aucune entité trouvée ». C'est une erreur. |
| **C4** | Une campagne qui échoue **échoue explicitement** — jamais un score partiel ambigu. Au-delà de **5 % de documents en erreur**, le run est non publiable. |
| **C5** | Le **scoring ne relance aucun modèle** : il travaille depuis les prédictions figées. `metrics/` et `cli/score.py` ne doivent jamais importer `systems/`, `detect/` ni `llm/`. |

## Invariant transverse

> **Tous les offsets réfèrent au texte original, à toutes les étapes.**

`text[start:end] == span_text` doit tenir partout. Un offset décalé invalide
silencieusement toutes les métriques de détection.

## Organisation du dépôt

```
src/anonymisation/
├── capabilities.py      # vocabulaire producteurs↔métriques — n'importe RIEN
├── schema/              # taxonomie SPEC-01, modèles pivot SPEC-02, io JSONL
├── datasets/            # registre + adaptateurs de corpus (un module par corpus)
├── detect/ transform/ policy/ risk/    # briques déterministes
├── pipeline/            # orchestrateur 8 étapes + traces + profils
├── llm/                 # client LLM, backends, cache — partagé (jamais importé par metrics/)
├── systems/             # LE CONTRAT : SystemBase, capacités, registre (aucune implémentation)
├── pipelines/           # LES PIPELINES — un dossier AUTONOME par architecture
│   └── <nom>/           #   system.py + profile.yaml + tests/ + README.md
├── metrics/             # scorecard, gating par capacités, protection, utilité
└── cli/                 # predict / score / compare / datasets / systems
configs/                 # configuration PARTAGÉE uniquement
├── datasets/  llm/backends.yaml  policy/  populations/
└── runtime/             # profils n'appartenant à aucun pipeline
documentation/           # rapport, datasets, specifications, guides, tickets
tests/unit/ tests/integration/   # miroir de l'arborescence source
```

**Un dossier autonome par architecture** : le profil, les tests et la notice
d'un pipeline vivent chez lui, pas dans `configs/` ni dans `tests/`. Ajouter
une architecture ne modifie qu'**un seul** fichier partagé, la ligne d'import
de `pipelines/__init__.py`. Carte des pipelines :
[src/anonymisation/pipelines/README.md](src/anonymisation/pipelines/README.md).

## Commandes

```bash
anonv2 systems list                       # systèmes enregistrés + capacités
anonv2 datasets ingest <clé> --split <s>  # corpus → format pivot
anonv2 predict --dataset <clé> --split <s> --system <sys> --profile <p> [--param k=v] [--limit N]
anonv2 score   --run runs/<r> --protocol <protocole-du-manifeste>
anonv2 compare --runs runs/<a> runs/<b> --out runs/compare.md
```

Ici `anonv2` n'est pas installé : préfixer par
`PYTHONPATH=src python -m anonymisation.cli.main …`.

Tests : `python -m pytest tests src/anonymisation/pipelines -q` (doit être **intégralement vert** avant de
rendre ; aucun test ne doit ouvrir de socket).

## Conventions

- **Langue** : français pour la rédaction, commentaires et messages d'erreur ;
  anglais pour les identifiants techniques (champs, classes, métriques).
- **Messages d'erreur actionnables** : nommer le fichier, la ligne, la clé
  fautive et le correctif attendu — jamais un timeout opaque.
- **Commentaires** : expliquer *pourquoi*, pas *quoi*. Les modules existants
  documentent leurs arbitrages ; suivre cette densité.
- **Modèles Pydantic** : `frozen=True, extra="forbid"` partout.
- **Écritures de fichiers** : passer par `schema/io.py` (atomique,
  `sort_keys=True`, UTF-8, `\n`) — la reproductibilité bit-à-bit en dépend.
- **Données** : rien sous `data/` n'est versionné. Aucun corpus sous licence
  restrictive (MIMIC, MEDDOCAN, corpus internes) ne doit être commité.

## Ce qu'il ne faut pas faire

- Publier un F1 comme résultat principal du projet : les métriques principales
  sont **CPR/IPR** (protection) et **Utility Retention**.
- Présenter un chiffre `PROXY` / `DIAGNOSTIC` / `SAMPLED` à côté d'un chiffre
  officiel (SPEC-07 §9).
- Contourner un seuil de qualité (taux d'erreur, garde de licence, garde
  réseau) plutôt que d'en corriger la cause.
- Masquer une limite découverte : elle s'écrit dans la docstring du module et
  dans le rapport d'évaluation.

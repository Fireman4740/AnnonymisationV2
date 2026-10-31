# Pipelines d'anonymisation — un dossier autonome par architecture

Chaque sous-dossier est **complet et indépendant** : son code, son profil
d'exécution, ses tests, sa notice. Ajouter, remplacer ou retirer une
architecture se fait dans un seul dossier.

```
pipelines/<nom>/
├── system.py        # l'implémentation, décorée @register_system
├── __init__.py      # ré-export ; l'import vaut enregistrement
├── profile.yaml     # son profil d'exécution (optionnel)
├── prompts.py       # ses ressources propres (optionnel : prompts, lexiques…)
├── README.md        # sa notice : clé, capacités, limites, commande
└── tests/           # ses tests
```

**Seul point de contact partagé** : une ligne d'import dans
[`__init__.py`](__init__.py). La découverte est explicite, jamais un scan de
répertoire — le comportement du registre ne doit pas dépendre de l'ordre de
parcours du système de fichiers.

## Les pipelines livrés

| Dossier | Clé | Capacités | Politique | Rôle |
|---|---|---|---|---|
| [`passthrough/`](passthrough/) | `passthrough-v1` | — | non | **Ancre S1** : ne fait rien (borne basse de protection, haute d'utilité) |
| [`redact_all/`](redact_all/) | `redact-all-v1` | — | non | **Ancre S2** : supprime tout (borne haute de protection) |
| [`regex_only/`](regex_only/) | `regex-only-v1` | `spans`, `decisions` | non | Baseline PII par motifs, sans QI |
| [`deterministic/`](deterministic/) | `deterministic-v1` | `spans`, `decisions`, `traces`, `risk`, `policy`, `gold_aware` | **oui** | Noyau 8 étapes de SPEC-10, hors ligne |
| [`llm_full/`](llm_full/) | `llm-full-v1` | `spans`, `decisions` | non | Anonymisation intégrale par LLM, un appel par document |
| [`llm_windowed/`](llm_windowed/) | `llm-windowed-v1` | `spans`, `decisions` | non | Anonymisation LLM par fenêtres recouvrantes, pour documents longs |
| [`llm_anchored/`](llm_anchored/) | `llm-anchored-v1` | `spans`, `decisions` | non | Baseline fenêtrée et critique aveugle à ancrage vérifié (expérimental) |

**Les deux ancres ne sont pas des gadgets** : sans elles, aucun chiffre de
protection n'a d'échelle, et rien ne détecte une métrique fausse (un système
qui bat `redact-all` en protection révèle un bug de métrique, pas une
performance).

## Contrat, en trois points

1. **`systems/` définit le contrat, `pipelines/` les implémentations.** Un
   pipeline importe `anonymisation.systems.base` et
   `anonymisation.systems.registry` ; jamais l'inverse.
2. **Déclarer le minimum vrai** en capacités. Produire sans déclarer lève
   `SystemContractError` ; sous-déclarer fait sortir les métriques en
   `UNAVAILABLE` (jamais `0.0`).
3. **`contract_config()`** déclare, chez le pipeline, comment le construire
   minimalement. Le test transverse
   (`tests/unit/test_system_contract.py`) s'en sert pour soumettre
   automatiquement toute architecture enregistrée aux mêmes assertions —
   aucun fichier de test partagé à éditer.

## Ajouter une architecture

Guide complet, avec squelette et checklist :
[`documentation/guides/creer-un-pipeline.md`](../../../documentation/guides/creer-un-pipeline.md).

En bref :

```bash
mkdir -p src/anonymisation/pipelines/mon_archi/tests
# system.py + __init__.py + README.md (+ profile.yaml si besoin)
# puis une ligne d'import dans pipelines/__init__.py
python -m pytest src/anonymisation/pipelines/mon_archi tests/unit/test_system_contract.py
```

## Où vit le reste

| Ressource | Emplacement | Pourquoi |
|---|---|---|
| Contrat, registre, capacités | `systems/`, `capabilities.py` | Partagé par tous |
| Client LLM, backends, cache | `llm/` + `configs/llm/backends.yaml` | Mutualisable entre architectures LLM |
| Briques déterministes (détection, transformation, politique, risque) | `detect/`, `transform/`, `policy/`, `risk/` | Réutilisables par plusieurs pipelines |
| Orchestrateur 8 étapes | `pipeline/` | Utilisé par `deterministic`, disponible pour d'autres |
| Métriques et scoring | `metrics/` | **Ne doit jamais importer un pipeline** (SPEC-10 C5) |

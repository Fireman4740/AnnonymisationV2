# Guide agent — créer un nouveau pipeline d'anonymisation évaluable

> Pour les métriques, le [catalogue actif réduit](../metrics-core.md), révisé
> le 15 octobre 2026, prévaut sur les références historiques à SPEC-07 dans ce
> guide. Ne pas réintroduire les métriques retirées ni le juge d'utilité.

| | |
|---|---|
| **Public** | Agent (ou humain) qui ajoute une architecture d'anonymisation au dépôt |
| **Statut** | Normatif |
| **Version** | 1.1 |
| **Date** | 2026-09-09 |
| **Spécifications de référence** | [SPEC-10](../specifications/SPEC-10-pipeline-anonymisation.md) (runtime), [SPEC-07](../specifications/SPEC-07-metriques.md) (métriques), [SPEC-01](../specifications/SPEC-01-taxonomie-qi.md) (taxonomie) |

---

## 0. Le contrat en une page

Dans ce dépôt, un **système** est l'unité évaluable : tout ce qui transforme un
document du pivot en texte anonymisé et peut passer par `anonv2 predict` puis
`anonv2 score`. Le harnais d'évaluation ne connaît **aucune** implémentation
concrète : il ne voit qu'un `PipelineResult` estampillé d'une identité et de
**capacités déclarées**.

```
        ton code                       harnais (ne pas modifier)
  ┌──────────────────────┐      ┌──────────────────────────────────────┐
  │ class MonSysteme     │      │ predict  → predictions.jsonl         │
  │   system_id = "…"    │ ───▶ │            manifest.lock.json        │
  │   capabilities = {…} │      │ score    → scorecard.json            │
  │   _execute(doc,gold) │      │ compare  → rapport Markdown          │
  └──────────────────────┘      └──────────────────────────────────────┘
```

Conséquence pratique : **tu n'as jamais à toucher `metrics/`, `cli/` ni
`pipeline/` pour ajouter un pipeline.** Si tu crois devoir le faire, c'est
presque toujours que le contrat est mal utilisé — relis §3 avant de modifier
quoi que ce soit dans le harnais.

---

## 1. Où créer les fichiers

| Ce que tu ajoutes | Emplacement | Exemple existant |
|---|---|---|
| **Le pipeline entier** | `src/anonymisation/pipelines/<nom>/` | [`llm_full/`](../../src/anonymisation/pipelines/llm_full/) |
| — son implémentation | `pipelines/<nom>/system.py` | [`llm_full/system.py`](../../src/anonymisation/pipelines/llm_full/system.py) |
| — son profil d'exécution | `pipelines/<nom>/profile.yaml` | [`deterministic/profile.yaml`](../../src/anonymisation/pipelines/deterministic/profile.yaml) |
| — ses ressources propres (prompt, lexique, gabarit) | `pipelines/<nom>/…` | [`llm_full/prompts.py`](../../src/anonymisation/pipelines/llm_full/prompts.py) |
| — ses tests | `pipelines/<nom>/tests/` | [`llm_full/tests/`](../../src/anonymisation/pipelines/llm_full/tests/) |
| — sa notice | `pipelines/<nom>/README.md` | [`regex_only/README.md`](../../src/anonymisation/pipelines/regex_only/README.md) |
| Backend LLM (modèle, URL, clé, cache) — **partagé** | `configs/llm/backends.yaml` | `qwen_local`, `stub` |
| Brique LLM réutilisable (client, cache) — **partagée** | `src/anonymisation/llm/` + `tests/unit/llm/` | [`llm/client.py`](../../src/anonymisation/llm/client.py) |

Squelette d'un dossier de pipeline :

```
src/anonymisation/pipelines/mon_archi/
├── __init__.py      # ré-export ; l'import vaut enregistrement
├── system.py        # l'implémentation, décorée @register_system
├── profile.yaml     # son profil d'exécution (optionnel)
├── README.md        # clé, capacités, limites connues, commande d'exemple
└── tests/
    ├── __init__.py
    └── test_system.py
```

**Un dossier autonome par architecture.** Tout ce qui appartient à un pipeline
vit chez lui. Le **seul** fichier partagé à modifier est la ligne d'import de
[`pipelines/__init__.py`](../../src/anonymisation/pipelines/__init__.py) — voir §5.

`anonymisation.systems` définit **le contrat** (`SystemBase`, capacités,
registre) et ne contient aucune implémentation ; `anonymisation.pipelines`
contient **les implémentations**. Un pipeline importe `systems`, jamais
l'inverse.

> ⚠️ **Ne jamais** faire importer `anonymisation.systems` (ni `detect/`, ni
> `llm/`) par `metrics/` ou `cli/score.py`. Le scoring doit rester hors ligne
> et sans modèle (SPEC-10 C5) — c'est testé par
> `tests/integration/test_score.py`. Le vocabulaire partagé entre producteurs
> et consommateurs vit dans `anonymisation.capabilities`, qui n'importe rien.

---

## 2. Choisir son niveau de contrat

Il n'existe **qu'un seul type de retour** (`PipelineResult`). Ce qui varie,
c'est ce que tu **déclares** produire.

| Ton système… | Classe de base | Capacités à déclarer | Ce que tu écris |
|---|---|---|---|
| réécrit du texte, sans prétendre localiser quoi que ce soit | `TextRewriteSystem` | *(aucune)* | `anonymize_text(doc) -> str` |
| localise des spans et décide d'actions | `SystemBase` | `CAP_SPANS`, `CAP_DECISIONS` | `_execute(doc, gold) -> PipelineResult` |
| estime en plus un risque et applique une politique | `SystemBase` | `+ CAP_RISK`, `CAP_POLICY` | idem, et `uses_policy = True` |
| trace les 8 étapes de SPEC-10 | `SystemBase` | `+ CAP_TRACES` | idem, **exactement 8 `StageTrace`** |

Déclare le **minimum vrai**. Sur-déclarer fait échouer le contrat
(`_assert_declares_what_it_produces` lève `SystemContractError` si tu produis
sans déclarer) ; sous-déclarer fait sortir tes métriques en `UNAVAILABLE`.

### Ce que chaque capacité débloque à l'évaluation

Table normative, tirée de [`metrics/gating.py`](../../src/anonymisation/metrics/gating.py) :

| Métriques | Capacité requise |
|---|---|
| `span_precision`, `span_recall`, `span_f1`, `span_f2`, `macro_f1`, `weighted_token_precision`, `ER_di`, `ER_qi`, `entity_recall_direct`, `entity_recall_quasi` | **`CAP_SPANS`** |
| `male_k`, `ece`, `brier` | **`CAP_RISK`** |
| `cpr`, `ipr`, `trir`, `gold_leak_rate`, `reid_success_rate`, `rouge_l`, `mean_utility`, `utility_retention` | **aucune** — mesurées sur le texte |

C'est le résultat central de l'architecture : **une boîte noire reste
pleinement évaluable sur la protection (CPR/IPR) et l'utilité.** Une métrique
dont la capacité manque sort en `UNAVAILABLE` avec un motif nommé, **jamais en
`0.0`** — un zéro ferait passer une boîte noire parfaite pour un détecteur
catastrophique.

---

## 3. Le squelette

```python
"""<Une phrase : ce que fait ce système, et en quoi il diffère des autres.>"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from anonymisation.capabilities import CAP_DECISIONS, CAP_SPANS
from anonymisation.detect.base import Candidate, candidates_to_annotations
from anonymisation.pipeline.orchestrator import _merge_overlapping
from anonymisation.pipeline.traces import PipelineResult
from anonymisation.schema.models import Annotation, Document
from anonymisation.systems.base import SystemBase, SystemConfig
from anonymisation.systems.registry import register_system
from anonymisation.transform.apply import apply_decisions
from anonymisation.transform.decisions import Action, AnonymizationDecision


class _MonSystemeParams(BaseModel):
    """Paramètres du système, passés par `--param cle=valeur`."""

    model_config = ConfigDict(frozen=True, extra="forbid")   # obligatoire

    seuil: float = 0.5


@register_system
class MonSysteme(SystemBase):
    """<Résumé affiché par `anonv2 systems list`.>"""

    system_id: ClassVar[str] = "mon-systeme-v1"   # suffixe de version OBLIGATOIRE
    system_version: ClassVar[str] = "1"
    aliases: ClassVar[tuple[str, ...]] = ("mon-systeme",)
    capabilities: ClassVar[frozenset[str]] = frozenset({CAP_SPANS, CAP_DECISIONS})
    uses_policy: ClassVar[bool] = False
    offline_only: ClassVar[bool] = True           # False si le système sort du process
    summary: ClassVar[str] = "…"
    Params: ClassVar[type[BaseModel] | None] = _MonSystemeParams

    @classmethod
    def contract_config(cls) -> SystemConfig:
        """Comment me construire minimalement — lu par le contrat de test.

        À surcharger si le système exige un paramètre sans défaut, une
        politique, ou un backend hors ligne. Sinon, ne pas l'écrire.
        """
        return SystemConfig()

    def __init__(self, config: SystemConfig | None = None) -> None:
        super().__init__(config)
        # self._params est déjà validé et figé ici.

    def _execute(self, doc: Document, gold: tuple[Annotation, ...]) -> PipelineResult:
        # `gold` NE DOIT PAS être lu (sauf oracle déclarant CAP_GOLD_AWARE).
        candidates: list[Candidate] = [...]        # offsets sur doc.text
        decisions: list[AnonymizationDecision] = [...]

        annotations = tuple(candidates_to_annotations(candidates, doc.doc_id, doc.text))
        non_keep = [d for d in decisions if d.action is not Action.KEEP]
        merged = _merge_overlapping(non_keep, doc.text)      # chevauchements multi-label
        result = apply_decisions(doc.text, merged)           # application droite→gauche

        return PipelineResult(
            doc_id=doc.doc_id,
            original_text=doc.text,
            anonymized_text=result.anonymized_text,
            annotations=annotations,
            decisions=tuple(decisions),
            risk=None,                 # None sans CAP_RISK
            policy_id="",              # "" sans CAP_POLICY
            traces=(),                 # () sans CAP_TRACES, sinon exactement 8
            status="ok",               # "ok" | "partial" | "error"
            errors=(),
            runtime_ms=0.0,
            identity=self.identity(),
        )
```

`run()` est **`@final`** : elle ne lève jamais, capture toute exception en
`status="error"` préfixé du nom du système, estampille l'identité et vérifie la
cohérence capacités/production. **Tu n'écris que `_execute`** — laisse remonter
tes exceptions, c'est le comportement voulu.

### Les trois statuts

| Statut | Sens | Effet sur le scoring |
|---|---|---|
| `ok` | Document traité normalement | Compté dans toutes les métriques |
| `partial` | Traité, mais un problème signalé dans `errors` (entité écartée, action repliée, fuite détectée) | Compté dans les métriques |
| `error` | Échec : le document n'a pas été anonymisé | **Exclu** des métriques, compté à part |

> **> 5 % de documents en `error` rend le run non publiable** (règle C-5) :
> `anonv2 score` affiche un avertissement bloquant et sort en code 1. C'est
> délibéré — la campagne v1 avait publié « strict F1 = 0.1242 » qui n'était pas
> une performance mais un taux d'échec déguisé en métrique.

---

## 4. Les invariants non négociables

| # | Règle | Pourquoi |
|---|---|---|
| **I1** | **Tous les offsets réfèrent au texte original**, à toutes les étapes. `text[start:end] == span_text` doit tenir. | Un offset décalé invalide silencieusement toutes les métriques de détection. `candidates_to_annotations` le vérifie et échoue. |
| **I2** | **Ne jamais lire `gold`** sans déclarer `CAP_GOLD_AWARE`. Un système qui le lit n'est pas publiable comme concurrent. | Sinon la mesure est circulaire. |
| **I3** | **Aucune valeur par défaut silencieuse.** Catégorie inconnue, licence absente, action illégale, réponse vide : échouer ou journaliser, jamais deviner. | Règle d'or du dépôt ([specifications/README §5](../specifications/README.md)). |
| **I4** | **Une action doit être légale** au sens de `ALLOWED_ACTIONS` (SPEC-01 §8) : `check_action_allowed(identifier_type, granularity_key, action)`. Pour `DIRECT`, la clé de granularité est `None`. | `MASK` n'est autorisé nulle part aujourd'hui ; `PSEUDONYMIZE` est réservé aux `DIRECT` ; `GENERALIZE` aux `QUASI`. |
| **I5** | **Filtrer les décisions `KEEP`** avant `_merge_overlapping` / `apply_decisions`. | `apply_decisions` refuse les chevauchements ; `KEEP` n'a rien à appliquer. |
| **I6** | **Une réponse LLM vide n'est jamais « aucune entité »** (C3). C'est une erreur nommée. | Cause n°1 de l'échec de la v1 (84–100 % d'erreurs masquées). |
| **I7** | Le `system_id` **porte sa version**. Changer l'algorithme sans changer la clé rend deux runs incomparables sous le même nom. | Le lock et les rapports sont indexés par cette clé. |

---

## 5. Le branchement obligatoire — checklist

**Un seul fichier partagé à modifier.** Tout le reste vit dans ton dossier.

1. **Enregistrement** — décorer la classe avec `@register_system` (dans
   `pipelines/<nom>/system.py`). Le registre refuse bruyamment toute collision
   de clé ou d'alias.
2. **Ré-export** — `pipelines/<nom>/__init__.py` :
   ```python
   from anonymisation.pipelines.<nom>.system import MonSysteme

   __all__ = ["MonSysteme"]
   ```
3. **Découverte** — ⚠️ **le seul fichier partagé** : ajouter une ligne dans
   [`pipelines/__init__.py`](../../src/anonymisation/pipelines/__init__.py) et
   le nom dans `PIPELINE_PACKAGES`.
   ```python
   from anonymisation.pipelines import mon_archi as _mon_archi  # noqa: F401
   ```
   **Jamais de scan de répertoire** : le comportement du registre ne doit pas
   dépendre de l'ordre de parcours du système de fichiers.
4. **Contrat de test** — déclarer `contract_config()` sur ta classe si sa
   construction exige quoi que ce soit (§3). Le test transverse
   [`tests/unit/test_system_contract.py`](../../tests/unit/test_system_contract.py)
   soumet **automatiquement** tout système enregistré à cinq assertions
   (identité estampillée, capacités cohérentes, offsets valides, sérialisation
   déterministe, résumé non vide) — **sans qu'aucun fichier de test partagé
   n'ait à te mentionner**. Un système que sa propre `contract_config()` ne
   suffit pas à construire échoue là, et c'est voulu.
5. **Profil d'exécution** — `pipelines/<nom>/profile.yaml` si ton système en
   lit un. `--profile <nom>` le résout automatiquement depuis ton dossier.
   `RuntimeProfile` valide tout le schéma, même les champs que tu ignores :
   copie un profil existant et documente en tête quels champs sont des
   remplisseurs.
6. **Tests** — `pipelines/<nom>/tests/` (avec un `__init__.py`). Découverts
   automatiquement : `testpaths` inclut `src/anonymisation/pipelines`.
7. **Notice** — `pipelines/<nom>/README.md` : clé, capacités, politique,
   **limites connues**, commande d'exemple.

### Cas particulier : un système qui appelle le réseau

Le test de contrat exécute **tout** système enregistré sur un corpus réel. Un
système LLM doit donc pouvoir tourner **sans socket** en test unitaire :
renvoie le backend `stub` (`kind: stub`, réponse canned déterministe) depuis
`contract_config()`, jamais le backend de production. Déclare aussi
`offline_only = False` sur la classe.

---

## 6. Évaluer

```bash
# 0. Vérifier que le système est visible
anonv2 systems list

# 1. Prédire (le pivot doit être ingéré : anonv2 datasets ingest <ds>)
anonv2 predict --dataset quasifr --split hard_quasi_id \
  --system mon-systeme --profile mon_archi \
  --param seuil=0.7 --limit 15 --out runs/eval-mon-systeme

# 2. Scorer (ne relance aucun modèle ; le protocole vient du manifeste du corpus)
anonv2 score --run runs/eval-mon-systeme --protocol quasifr-v1

# 3. Comparer à une baseline
anonv2 compare --runs runs/eval-regex-quasifr runs/eval-mon-systeme \
  --out runs/compare.md
```

> Dans cet environnement, `anonv2` n'est pas installé : préfixer par
> `PYTHONPATH=src python -m anonymisation.cli.main …`.

Le protocole passé à `score` doit correspondre au champ `evaluation.protocol`
du manifeste du corpus (`configs/datasets/<clé>.yaml`), sinon le scoring refuse.

### Lire les résultats sans se tromper

- **CPR / IPR** (↑, 1 = protection totale) sont les métriques principales de
  protection. **Publier les deux** : leur écart révèle une protection inégale
  entre sujets.
- Les suffixes **`PROX` / `DIAG` / `SAMP` ne sont pas des chiffres publiables**.
  Ils ne se comparent qu'entre runs de même statut.
- **Toujours encadrer par les deux ancres** :
  [`passthrough-v1`](../../src/anonymisation/pipelines/passthrough/) (ne fait
  rien : borne basse de protection, haute d'utilité) et
  [`redact-all-v1`](../../src/anonymisation/pipelines/redact_all/) (supprime
  tout : borne haute de protection, utilité effondrée).
  **Si un système bat `redact-all` en protection, c'est la métrique qui est
  fausse, pas le système qui est excellent.**
- Un run à `utility_retention: unavailable` n'a **pas** de mesure d'utilité
  métier : `rouge_l` n'en est qu'un proxy textuel, explicitement déconseillé
  comme utilité principale (SPEC-07 §5).

---

## 7. Anti-patrons fréquents

| Symptôme | Cause | Correctif |
|---|---|---|
| `SystemContractError: produit annotations sans 'spans'` | Capacité non déclarée | Ajouter `CAP_SPANS`, ou cesser de produire des annotations |
| Métrique à `UNAVAILABLE` alors que le système la calcule | Capacité manquante dans `capabilities` | Déclarer la capacité (voir table §2) |
| `I-ANN-1 violé : text[a:b] != span_text` | Offsets calculés sur un texte transformé/normalisé | Recalculer sur `doc.text` original (I1) |
| `OverlappingDecisionsError` | Décisions imbriquées (multi-label) non fusionnées | Passer par `_merge_overlapping` avant `apply_decisions` (I5) |
| `ActionNotAllowedError` | Action hors `ALLOWED_ACTIONS` | Valider avec `check_action_allowed` et replier explicitement (I4) |
| Test de contrat qui ouvre une connexion | Backend de production utilisé en test | Renvoyer le backend `stub` depuis `contract_config()` (§5) |
| `run non publiable : taux d'erreur > 5 %` | Vraie fragilité du système, pas un bug du harnais | Corriger la cause (ex. documents longs → découper), ne pas contourner le seuil |
| Deux runs incomparables sous le même nom | `system_id` inchangé après modification de l'algo | Incrémenter la version dans `system_id` (I7) |

---

## 8. Checklist de revue avant de rendre le travail

- [ ] Dossier autonome `pipelines/<nom>/` (§1) : code, profil, tests, README.
- [ ] `capabilities` = le minimum vrai ; rien de produit qui ne soit déclaré.
- [ ] `Params` en Pydantic `frozen=True, extra="forbid"`.
- [ ] `gold` non lu (ou `CAP_GOLD_AWARE` déclaré et assumé).
- [ ] Offsets sur le texte original, vérifiés.
- [ ] Actions validées contre `ALLOWED_ACTIONS`, replis journalisés.
- [ ] `@register_system` + ré-export + **une** ligne dans `pipelines/__init__.py`.
- [ ] `contract_config()` déclarée si la construction exige quoi que ce soit.
- [ ] `profile.yaml` dans le dossier si nécessaire ; backend `stub` en test.
- [ ] `pytest tests src/anonymisation/pipelines` intégralement vert.
- [ ] `predict` → `score` → `compare` exécutés au moins une fois, avec une
      baseline et les deux ancres.
- [ ] Limites réelles du système **écrites** (docstring de module + rapport
      d'évaluation), jamais masquées.

---

## 9. Exemple de référence

Le système [`llm-full-v1`](../../src/anonymisation/pipelines/llm_full/) est
l'implémentation la plus complète de ce guide : capacités partielles
(`spans + decisions`, sans risque ni politique), backend externe, garde-fous de
localisation et de légalité d'action, limites documentées en tête de module, et
campagne d'évaluation rapportée dans
[`rapport/05-evaluation-llm-full-v1.md`](../rapport/05-evaluation-llm-full-v1.md).

# ÉPIC D — Métriques et scorecard

**Objectif** : des métriques ventilées, typées par statut, et non falsifiables.

**Effort** : ~3 jours · **Dépend de** : C-3.

**Rappel normatif** : le F1 n'est **pas** la métrique principale du projet
(SPEC-07 §1). Ce backlog livre le niveau 1 (détection) et l'ossature de la
scorecard ; les niveaux 3 à 5 (calibration, ré-identification, utilité)
viennent avec les lots L4 et L6.

---

## D-1 — Métriques de niveau 1 et ventilations

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | C-3 |
| **Spécs** | SPEC-07 §2 |
| **Effort** | 1 j |

### Périmètre

- `src/anonymisation/metrics/spans.py`
- `src/anonymisation/metrics/entities.py`
- `tests/unit/test_metrics_spans.py`

### Travail

```python
def span_metrics(gold, pred, *, match: str = "overlap") -> dict[str, float]
def entity_recall(gold, pred, *, identifier_type: IdentifierType) -> float
def weighted_token_precision(gold, pred, text: str) -> float
```

**Modes de correspondance** (le mode utilisé DOIT être déclaré avec tout score) :

| Mode | Règle | Usage |
|------|-------|-------|
| `exact` | offsets identiques | rapport strict |
| `overlap` | intersection non vide | **défaut** — un masquage partiellement décalé protège quand même |
| `entity` | au moins une mention par entité | rapport privacy |

**Priorité privacy-first** : publier `F2` (β=2, favorise le rappel) à côté du
`F1`. Un faux négatif de confidentialité laisse fuiter ; un faux positif ne fait
que dégrader l'utilité.

**Le rappel entity-level est celui qui compte** : masquer 9 des 10 mentions d'un
nom ne protège rien, alors que le rappel span-level afficherait 90 %.

### Ventilations obligatoires

`by_qi_category` (macro-F1) · `by_language` · `by_domain` ·
`by_expression_mode` · `by_difficulty`.

Les dénominateurs viennent de `.validation.json` produit à l'ingestion (A-2).

### Critères d'acceptation

- [ ] Les 3 modes de correspondance donnent des valeurs différentes sur un cas
      construit exprès, et le mode figure dans la sortie.
- [ ] `entity_recall` diffère du rappel span-level sur un document où une entité
      a plusieurs mentions (sinon la coréférence est ignorée).
- [ ] Les 5 ventilations sont produites, avec leurs effectifs.
- [ ] Une catégorie absente du gold produit `null`, pas `0.0` — confondre les
      deux ferait chuter artificiellement un macro-F1.
- [ ] `F2 > F1` quand le rappel dépasse la précision (test de cohérence).

---

## D-2 — Contrats `MetricValue` et `MetricStatus`

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | — |
| **Spécs** | SPEC-07 §9, SPEC-02 §12 |
| **Effort** | 0,25 j |

### Contexte

Décision déjà prise en SPEC-02 §12 : ces contrats sont **repris tels quels de
la v1** (`eval/core/contracts.py`), qui les avait bien conçus. Ne pas
réinventer — les lire d'abord.

### Périmètre

- `src/anonymisation/metrics/contracts.py`
- `tests/unit/test_metric_contracts.py`

### Travail

```python
class MetricStatus(str, Enum):
    OFFICIAL = "official"       # protocole officiel, volumétrie complète, licence connue
    SAMPLED = "sampled"         # sous-échantillon, plan documenté
    DIAGNOSTIC = "diagnostic"   # interne, non comparable à la littérature
    PROXY = "proxy"             # approximation d'une métrique officielle
    UNAVAILABLE = "unavailable"
    FAILED = "failed"

class MetricDirection(str, Enum):
    MAXIMIZE = "maximize"; MINIMIZE = "minimize"; INFORMATIONAL = "informational"

@dataclass(frozen=True)
class MetricValue:
    name: str
    value: float | None
    protocol: str
    protocol_version: str
    status: MetricStatus
    direction: MetricDirection
    unit: str = "ratio"
    details: dict = field(default_factory=dict)
```

### Règle à faire respecter par le code, pas seulement par la documentation

> Une métrique `DIAGNOSTIC` ou `PROXY` NE DOIT PAS être présentée comme
> comparable à un chiffre publié.

Implémenter `assert_comparable(a: MetricValue, b: MetricValue) -> None` qui
lève si l'on tente de comparer deux métriques de protocoles ou de statuts
incompatibles. L'audit v1 relève précisément ce mélange comme risque P1.

### Critères d'acceptation

- [ ] Comparer un `OFFICIAL` et un `PROXY` lève une exception.
- [ ] Comparer deux protocoles différents lève une exception.
- [ ] Une `MetricValue` sans `protocol` est refusée à la construction.
- [ ] `value=None` est autorisé uniquement si `status` est `UNAVAILABLE` ou
      `FAILED`.

---

## D-3 — Métriques officielles TAB

| | |
|---|---|
| **Priorité** | P1 |
| **Dépend de** | B-3, D-1 |
| **Spécs** | SPEC-07 §2 |
| **Effort** | 0,75 j |

### Contexte

`TAB/official/evaluation.py` est le **script d'évaluation officiel des auteurs**,
présent sur disque. C'est la seule façon d'obtenir une métrique `OFFICIAL`
comparable à la littérature — l'audit v1 note que le score officiel TAB était
`unavailable`, ce qui privait le projet de tout point de comparaison externe.

### Périmètre

- `src/anonymisation/metrics/tab_official.py`
- `tests/integration/test_tab_official.py`

### Travail

1. Lire `TAB/official/evaluation.py` et **reprendre son protocole**, pas le
   réinventer.
2. Implémenter les 4 métriques de TAB : entity-level recall DIRECT,
   entity-level recall QUASI, weighted token-level precision, utilité pondérée.
3. Si le portage est incomplet, marquer `PROXY` — jamais `OFFICIAL`.

### Critères d'acceptation

- [ ] Reproduction d'au moins un score publié du papier à ±2 points, ou
      justification documentée de l'écart.
- [ ] Les métriques sont marquées `OFFICIAL` **seulement** si le protocole est
      intégralement respecté (volumétrie complète, règle d'agrégation déclarée).
- [ ] La règle d'agrégation multi-annotateurs utilisée figure dans la sortie.

---

## D-4 — Scorecard et manifeste de run

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | D-1, D-2 |
| **Spécs** | SPEC-07 §10, SPEC-09 §5 |
| **Effort** | 0,5 j |

### Périmètre

- `src/anonymisation/metrics/scorecard.py`
- `tests/unit/test_scorecard.py`

### Format de sortie

Celui de SPEC-07 §10, avec `primary` / `diagnostic` / ventilations /
`efficiency`, **plus** le bloc `accounting` du ticket C-5.

### Les 7 éléments de reproductibilité (SPEC-09 §5)

Un rapport de run sans ces éléments **n'est pas publiable** :

| # | Élément | Source |
|---|---------|--------|
| 1 | Version des données | `.manifest.lock.json` (sha256, révision source) |
| 2 | Version de la taxonomie | `TAXONOMY_VERSION` |
| 3 | Version du code | commit git |
| 4 | Modèles et quantisations | profil d'exécution |
| 5 | Seeds | profil d'exécution |
| 6 | Prompts | néant en profil déterministe — le déclarer explicitement |
| 7 | Politique | `configs/policy/policies.yaml` + id de politique |

### Critères d'acceptation

- [ ] Une scorecard à laquelle il manque un des 7 éléments est refusée par
      `validate_scorecard()`.
- [ ] `error_rate` figure au premier niveau.
- [ ] Aucune métrique `PROXY` n'apparaît dans le bloc `primary`.
- [ ] La scorecard est sérialisable et relisible sans perte (aller-retour JSON).
- [ ] Deux scorings du même run produisent des scorecards identiques, hors
      horodatage.

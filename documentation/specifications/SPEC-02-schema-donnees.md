# SPEC-02 — Schéma de données interne

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date** | 2026-08-30 |
| **Dépend de** | SPEC-01 |
| **Utilisée par** | SPEC-03, SPEC-04, SPEC-05, SPEC-06, SPEC-07 |

---

## 1. Objet

Définir le **format pivot unique** vers lequel tout dataset est normalisé.
Chaque adaptateur convertit son format source vers ce schéma ; tout le reste du
système (moteur de risque, métriques, attaquants, politique) ne connaît **que**
ce schéma.

C'est la décision d'architecture la plus structurante du projet : elle permet
d'ajouter un dataset sans toucher au moteur, et de changer le moteur sans
toucher aux datasets.

## 2. Format physique

| Aspect | Choix |
|--------|-------|
| Sérialisation | **JSON Lines** (`.jsonl`), un objet par ligne, UTF-8, `\n` |
| Validation | **Pydantic v2** — les modèles Python sont la définition normative |
| Emplacement | `data/processed/<dataset_key>/<split>/<table>.jsonl` |
| Compression | `.jsonl.zst` accepté en lecture, jamais en écriture intermédiaire |
| Versionnement du schéma | champ `schema_version` dans le manifeste, valeur actuelle `"2.0"` |

Choix du JSONL plutôt que Parquet : lisibilité en `git diff` et en `head`,
inspection sans outillage, et volumétrie modeste (< 5 Go au total). Un export
Parquet PEUT être ajouté pour les jointures massives, jamais comme source de
vérité.

## 3. Les six tables

```
organizations.jsonl ──┐
                      ├──> profiles.jsonl ──┐
                                            ├──> documents.jsonl ──> annotations.jsonl
                                            │            │
                                            └────────────┴────────> combinations.jsonl
                                                         │
                                                         └────────> tasks.jsonl
```

| Table | Obligatoire | Contenu |
|-------|:-----------:|---------|
| `documents.jsonl` | ✅ | Les textes |
| `annotations.jsonl` | ✅ | Les spans et inférences annotés |
| `profiles.jsonl` | ⬜ | Les profils latents (si le dataset en a) |
| `combinations.jsonl` | ⬜ | Les combinaisons de QI avec leur `k_true` |
| `organizations.jsonl` | ⬜ | Profils latents d'organisation (support) |
| `tasks.jsonl` | ⬜ | Étiquettes des tâches d'utilité |

Un dataset ne fournissant que `documents` + `annotations` est valide — il ne
pourra simplement pas alimenter les métriques de niveau 3 et 4.

---

## 4. `documents.jsonl`

```json
{
  "doc_id": "synthpai:c_00412",
  "dataset": "synthpai",
  "split": "test",
  "domain": "forum",
  "language": "en",
  "text": "I defended my thesis last year and I'm still looking for a postdoc...",
  "author_id": "synthpai:p_017",
  "org_id": null,
  "thread_id": "synthpai:t_033",
  "position_in_thread": 4,
  "timestamp": "2024-03-11T09:22:00Z",
  "meta": { "difficulty": "implicit", "noisy": false }
}
```

| Champ | Type | Oblig. | Contrainte |
|-------|------|:------:|-----------|
| `doc_id` | `str` | ✅ | Unique globalement. **DOIT** être préfixé `<dataset_key>:` |
| `dataset` | `str` | ✅ | Clé du registre |
| `split` | `str` | ✅ | `train` \| `dev` \| `test` \| autre déclaré au manifeste |
| `domain` | `str` | ✅ | `hr` \| `support` \| `forum` \| `legal` \| `clinical` \| `generic` |
| `language` | `str` | ✅ | ISO 639-1 (`fr`, `en`, `es`, `de`…) |
| `text` | `str` | ✅ | Texte brut, **jamais normalisé** après calcul des offsets |
| `author_id` | `str \| null` | ⬜ | Réfère `profiles.person_id` |
| `org_id` | `str \| null` | ⬜ | Réfère `organizations.org_id` |
| `thread_id` | `str \| null` | ⬜ | Regroupement conversationnel |
| `position_in_thread` | `int \| null` | ⬜ | Ordre dans le fil |
| `timestamp` | `str \| null` | ⬜ | ISO 8601 UTC |
| `meta` | `object` | ✅ | Libre, mais **`difficulty`** DEVRAIT y figurer quand la source le permet |

### Invariants

- **I-DOC-1** : `text` est immuable. Toute normalisation (espaces, unicode,
  casse) DOIT être faite **avant** le calcul des offsets, jamais après.
- **I-DOC-2** : `doc_id` est stable entre deux ingestions du même dataset à la
  même version. Un `doc_id` ne DOIT jamais être un index de ligne.
- **I-DOC-3** : si `author_id` est non nul, il DOIT exister dans
  `profiles.jsonl`.

---

## 5. `annotations.jsonl`

```json
{
  "annotation_id": "tab:a_10233",
  "doc_id": "tab:case_00417",
  "start": 128,
  "end": 136,
  "span_text": "doctorant",
  "identifier_type": "QUASI",
  "qi_categories": ["GEN_OCCUPATION", "GEN_EDUCATION"],
  "expression_mode": "EXPLICIT",
  "sensitivity": "NONE",
  "granularity": "COARSE",
  "stability": "VOLATILE",
  "subject": "SELF",
  "value_normalized": { "isced": "8", "esco": "2310" },
  "entity_id": "tab:e_0031",
  "annotator_id": "ann_02",
  "confidence": 1.0,
  "meta": {}
}
```

| Champ | Type | Oblig. | Contrainte |
|-------|------|:------:|-----------|
| `annotation_id` | `str` | ✅ | Unique |
| `doc_id` | `str` | ✅ | Réfère `documents.doc_id` |
| `start` / `end` | `int \| null` | ⬜ | Offsets **caractères**, sur `text`, fin exclusive |
| `span_text` | `str \| null` | ⬜ | **DOIT** vérifier `text[start:end] == span_text` |
| `identifier_type` | enum | ✅ | SPEC-01 §3.1 |
| `qi_categories` | `list[str]` | ✅ | ≥ 1 code SPEC-01 §4. Multi-label autorisé |
| `expression_mode` | enum | ✅ | SPEC-01 §3.2 |
| `sensitivity` | enum | ✅ | SPEC-01 §3.3, défaut `NONE` **explicite** |
| `granularity` | enum | ✅ | `EXACT` \| `RANGE` \| `COARSE` |
| `stability` | enum | ✅ | `STABLE` \| `VOLATILE` |
| `subject` | enum | ✅ | `SELF` \| `THIRD_PARTY` |
| `value_normalized` | `object \| null` | ⬜ | Forme normalisée (SPEC-01 §6.2), requise pour le calcul de $k$ |
| `entity_id` | `str \| null` | ⬜ | Cluster de coréférence |
| `annotator_id` | `str \| null` | ⬜ | Requis quand la source est multi-annotateurs |
| `confidence` | `float` | ✅ | [0,1], défaut 1.0 pour du gold |

### Invariants

- **I-ANN-1** — *offsets valides* : si `start` est non nul, alors `end > start`,
  `end ≤ len(text)`, et `text[start:end] == span_text`. **Violation = échec
  d'ingestion**, jamais un avertissement.
- **I-ANN-2** — *annotation sans offset* : `start = end = span_text = null` est
  **autorisé** uniquement si `expression_mode == "IMPLICIT"`. C'est le cas
  d'une inférence au niveau document (exigence SynthPAI, voir
  [`synthpai.md §10`](../datasets/synthpai.md)).
- **I-ANN-3** — *exclusivité DIRECT* : si `identifier_type == "DIRECT"`, alors
  `qi_categories` ne contient que des codes `DIR_*`.
- **I-ANN-4** — *totalité du mapping* : aucun code hors SPEC-01 n'est accepté.
  Une étiquette source non mappée fait échouer l'ingestion.
- **I-ANN-5** — *chevauchements* : deux annotations d'un même document PEUVENT
  se chevaucher (multi-label imbriqué). L'évaluateur DOIT gérer ce cas ; il ne
  DOIT pas les dédupliquer silencieusement.

---

## 6. `profiles.jsonl`

```json
{
  "person_id": "hr_qi:P01742",
  "dataset": "hr_qi",
  "org_id": "hr_qi:O0231",
  "pseudonym": "matt_lil",
  "population_id": "fr-hr-2026",
  "attributes": {
    "GEN_AGE":        { "value": 28, "normalized": { "range": [28, 28] } },
    "GEN_EDUCATION":  { "value": "PhD", "normalized": { "isced": "8", "field": "physics" } },
    "GEN_OCCUPATION": { "value": "researcher", "normalized": { "pcs": "342a" } },
    "GEN_GEO":        { "value": "Lille", "normalized": { "geo": "FR-59350" } },
    "HR_SENIORITY":   { "value": 6, "normalized": { "range": [6, 6] } },
    "HR_CONTRACT":    { "value": "CDI", "normalized": { "code": "CDI" } },
    "HR_EMPLOYER_SIZE": { "value": "300-500", "normalized": { "range": [300, 500] } }
  },
  "meta": {}
}
```

| Champ | Type | Oblig. | Contrainte |
|-------|------|:------:|-----------|
| `person_id` | `str` | ✅ | Unique, préfixé `<dataset_key>:` |
| `dataset` | `str` | ✅ | — |
| `org_id` | `str \| null` | ⬜ | Réfère `organizations.org_id` |
| `pseudonym` | `str \| null` | ⬜ | Identité publique (forums) |
| `population_id` | `str` | ✅ | Réfère `configs/populations/<id>.yaml` |
| `attributes` | `object` | ✅ | Clés = codes SPEC-01, valeurs = `{value, normalized}` |

### Invariants

- **I-PRO-1** : toute clé d'`attributes` est un code SPEC-01 valide.
- **I-PRO-2** : `normalized` DOIT être renseigné pour tout attribut participant
  au calcul de $k$ ; sinon l'attribut est ignoré par le moteur de risque **avec
  un avertissement explicite**, jamais en silence.
- **I-PRO-3** : `population_id` DOIT exister, sinon aucun $k$ n'est calculable.

---

## 7. `organizations.jsonl`

Table propre au domaine support (voir
[`support-qi-bench.md §10`](../datasets/support-qi-bench.md)).

```json
{
  "org_id": "support_qi:O0231",
  "dataset": "support_qi",
  "population_id": "support-parc-2026",
  "attributes": {
    "SUP_ORG":         { "value": "manufacturing", "normalized": { "nace": "C28" } },
    "SUP_SCALE":       { "value": "400-600", "normalized": { "range": [400, 600] } },
    "SUP_PRODUCT":     { "value": "X",     "normalized": { "product": "X" } },
    "SUP_VERSION":     { "value": "4.2.1", "normalized": { "semver": "4.2.1" } },
    "SUP_ENVIRONMENT": { "value": "on-prem + oracle connector", "normalized": { "env": ["on-prem", "conn-oracle"] } }
  },
  "meta": { "country": "FR", "sites": 3 }
}
```

Même structure que `profiles`, avec `org_id` en clé.

---

## 8. `combinations.jsonl`

C'est **la table qui porte la contribution scientifique du projet**. Sans elle,
ni QICR, ni MAE-k, ni calibration.

```json
{
  "combination_id": "hr_qi:comb_00981",
  "dataset": "hr_qi",
  "target_type": "person",
  "target_id": "hr_qi:P01742",
  "scope": "document",
  "doc_ids": ["hr_qi:d_04412"],
  "qi_set": [
    { "qi_category": "GEN_AGE",           "normalized": { "range": [18, 29] } },
    { "qi_category": "GEN_EDUCATION",     "normalized": { "isced": "8" } },
    { "qi_category": "HR_ADMIN_PROCEDURE","normalized": { "code": "sick_leave" } }
  ],
  "k_true": 3,
  "risk_true": 0.333,
  "risk_model": "prosecutor",
  "population_id": "fr-hr-2026",
  "at_risk": true,
  "source": "generated"
}
```

| Champ | Type | Oblig. | Contrainte |
|-------|------|:------:|-----------|
| `combination_id` | `str` | ✅ | Unique |
| `target_type` | enum | ✅ | `person` \| `organization` |
| `target_id` | `str` | ✅ | Réfère `profiles` ou `organizations` |
| `scope` | enum | ✅ | `document` \| `thread` \| `author` |
| `doc_ids` | `list[str]` | ✅ | Documents d'où la combinaison est observable |
| `qi_set` | `list[object]` | ✅ | ≥ 1 élément, chacun `{qi_category, normalized}` |
| `k_true` | `int \| null` | ⬜ | Taille de la classe d'équivalence |
| `risk_true` | `float \| null` | ⬜ | [0,1] |
| `risk_model` | `str` | ✅ | `prosecutor` \| `journalist` \| `marketer` \| `copula` (SPEC-06) |
| `population_id` | `str` | ✅ | — |
| `at_risk` | `bool` | ✅ | `k_true ≤ k_seuil` (défaut 10) |
| `source` | `str` | ✅ | `generated` \| `annotated` \| `computed` \| `dataset` |

### Invariants

- **I-CMB-1** — *monotonie du scope* : pour un même `target_id` et un même
  `qi_set` observable à plusieurs scopes,
  $k_{author} \leq k_{thread} \leq k_{document}$. Violation = incohérence de
  génération, échec bloquant.
- **I-CMB-2** — *cohérence risque/k* : si `risk_model == "prosecutor"` et
  `k_true` non nul, alors `risk_true == 1 / k_true` à $10^{-6}$ près.
- **I-CMB-3** — *traçabilité* : `source` DOIT distinguer une vérité terrain
  générée (fiable) d'une valeur calculée par notre propre moteur (circulaire —
  **ne DOIT jamais servir à évaluer ce même moteur**).

> **I-CMB-3 est un garde-fou méthodologique majeur.** Évaluer le moteur de
> risque contre des `k` calculés par le moteur de risque produirait une
> métrique parfaite et vide de sens. Les métriques de niveau 3 n'acceptent que
> `source ∈ {generated, annotated, dataset}`.

---

## 9. `tasks.jsonl`

```json
{
  "doc_id": "support_qi:d_00187",
  "task": "ticket_routing",
  "label": "team_infra",
  "label_type": "single",
  "meta": {}
}
```

| Champ | Contrainte |
|-------|-----------|
| `task` | Identifiant de tâche déclaré au manifeste |
| `label` | `str` \| `list[str]` \| `float` selon `label_type` |
| `label_type` | `single` \| `multi` \| `regression` |

Les tâches d'utilité par domaine sont listées dans les fiches
[`hr-qi-bench §8`](../datasets/hr-qi-bench.md),
[`support-qi-bench §8`](../datasets/support-qi-bench.md),
[`forum-qi-bench §7`](../datasets/forum-qi-bench.md).

---

## 10. Modèles Python normatifs

Emplacement : `src/anonymisation/schema/models.py`.

```python
class IdentifierType(str, Enum):
    DIRECT = "DIRECT"
    QUASI = "QUASI"
    SENSITIVE_ONLY = "SENSITIVE_ONLY"
    IGNORED = "IGNORED"


class ExpressionMode(str, Enum):
    EXPLICIT = "EXPLICIT"
    NON_STANDARD = "NON_STANDARD"
    IMPLICIT = "IMPLICIT"


class Annotation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    annotation_id: str
    doc_id: str
    start: int | None = None
    end: int | None = None
    span_text: str | None = None
    identifier_type: IdentifierType
    qi_categories: tuple[str, ...]
    expression_mode: ExpressionMode
    sensitivity: Sensitivity = Sensitivity.NONE
    granularity: Granularity
    stability: Stability
    subject: Subject = Subject.SELF
    value_normalized: dict[str, Any] | None = None
    entity_id: str | None = None
    annotator_id: str | None = None
    confidence: float = 1.0
    meta: dict[str, Any] = Field(default_factory=dict)
```

Deux choix imposés :

- `extra="forbid"` — un champ inattendu est une erreur, pas un champ ignoré.
  C'est ce qui rattrape les fautes de frappe dans les adaptateurs.
- `frozen=True` — les objets sont immuables. Une transformation produit un
  nouvel objet, ce qui rend le pipeline traçable.

## 11. Identifiants

Règle unique : **tout identifiant est préfixé par la clé du dataset**.

```
<dataset_key>:<identifiant local>
```

Cela garantit qu'on peut concaténer deux datasets sans collision — situation qui
se produit dès qu'on évalue sur la batterie complète.

## 12. Compatibilité avec la V1

Le dépôt V1 (`../Anonymisation`) définit dans `eval/core/contracts.py` :
`SCHEMA_VERSION = "2.0"`, `Span = Tuple[int, int, str]`, `MetricValue`,
`MetricStatus`, `MetricDirection`, `DatasetManifest`, `SamplingPlan`.

Décisions de reprise :

| Élément V1 | Décision V2 |
|------------|-------------|
| `MetricValue`, `MetricStatus`, `MetricDirection` | **Repris tels quels** — ils sont bien conçus et évitent de réinventer la notion de statut de métrique |
| `DatasetManifest` | **Repris et étendu** (voir SPEC-03 §4) |
| `SamplingPlan` | **Repris tel quel** |
| `Span = (int, int, str)` | **Abandonné** — le tuple ne porte pas les quatre axes de SPEC-01. Remplacé par `Annotation`. Un convertisseur `span_to_annotation()` est fourni pour la compatibilité ascendante avec les adaptateurs V1. |

## 13. Validation

Chaque table est validée à l'ingestion (SPEC-04 §5). La commande

```bash
anonv2 datasets validate <dataset_key>
```

vérifie tous les invariants `I-*` de cette spec et retourne un code d'erreur
non nul en cas de violation.

## 14. Journal des modifications

| Version | Date | Changement |
|---------|------|-----------|
| 1.0 | 2026-08-30 | Création. Six tables, invariants I-DOC/I-ANN/I-PRO/I-CMB. Reprise partielle des contrats V1. |

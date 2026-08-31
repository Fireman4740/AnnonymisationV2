# ÉPIC C — Orchestration et exécution

**Objectif** : `anonv2 predict` traite 100 % des documents de tous les corpus
avec **0 % d'erreur**, et `anonv2 score` produit une scorecard sans relancer
aucun modèle.

**Effort** : ~4 jours · **Dépend de** : A-2, A-3.

---

## C-1 — Orchestrateur des 8 étapes

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | A-2 |
| **Spécs** | SPEC-10 §3 et §4 |
| **Effort** | 1 j |

### Contexte

Les briques `detect/`, `transform/` et `policy/` sont livrées et testées, mais
rien ne les enchaîne. L'orchestrateur est la pièce manquante entre elles.

Contrainte d'architecture (audit v1 §12.3) : le domaine ne dépend d'aucun
moteur de graphe. LangGraph peut rester un adaptateur d'exécution, jamais une
dépendance du noyau.

### Périmètre

- `src/anonymisation/pipeline/__init__.py`
- `src/anonymisation/pipeline/orchestrator.py`
- `src/anonymisation/pipeline/traces.py`
- `src/anonymisation/pipeline/profiles.py` (chargement de `configs/runtime/*.yaml`)
- `tests/unit/test_orchestrator.py`

### Travail

Enchaîner : DETECT → FUSE → ASSESS → PLAN → TRANSFORM → VALIDATE
(→ AUDIT → REWRITE, désactivées).

```python
@dataclass(frozen=True)
class PipelineResult:
    doc_id: str
    original_text: str
    anonymized_text: str
    annotations: tuple[Annotation, ...]
    decisions: tuple[AnonymizationDecision, ...]
    risk: RiskAssessment | None
    policy_id: str
    traces: tuple[StageTrace, ...]
    status: str            # "ok" | "partial" | "error"
    errors: tuple[str, ...]
    runtime_ms: float

class Pipeline:
    def __init__(self, profile: RuntimeProfile) -> None
    def run(self, doc: Document) -> PipelineResult
```

`StageTrace` par étape : `stage`, `order`, `entities_in`, `entities_out`,
`duration_ms`, `sha256_before`, `sha256_after`, `added`, `removed`, `modified`,
`decisions`, `status`, `error`.

### Invariant transverse à faire respecter

> **Tous les offsets réfèrent au texte original, à toutes les étapes.**

Une étape produisant des offsets relatifs à un texte partiellement transformé
corromprait silencieusement toutes les suivantes. Écrire un test dédié.

### Critères d'acceptation

- [ ] Le profil `deterministic` charge sans erreur depuis
      `configs/runtime/deterministic.yaml` et n'active ni NER ni LLM.
- [ ] Les 6 étapes produisent chacune une `StageTrace`.
- [ ] Une étape désactivée produit une trace `status="skipped"`, pas une
      absence de trace.
- [ ] Test d'invariant : après TRANSFORM, les offsets des annotations pointent
      toujours sur `original_text`.
- [ ] Le pipeline tourne de bout en bout sur le micro-dataset.

---

## C-2 — Étape VALIDATE et contrôle de fuite gold

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | C-1 |
| **Spécs** | SPEC-10 §3 étape 6 |
| **Effort** | 0,5 j |

### Contexte

C'est l'étape qui répond à la question « l'anonymisation a-t-elle réellement
retiré quelque chose ? ». Sans elle, un pipeline peut sembler fonctionner tout
en laissant fuiter les identifiants.

### Périmètre

- `src/anonymisation/pipeline/validate_stage.py`
- `tests/unit/test_validate_stage.py`

### Travail

Trois contrôles :

1. **Placeholders bien formés** : tout placeholder produit correspond au motif
   attendu et n'a pas été tronqué par une transformation ultérieure.
2. **Motifs interdits** : le texte anonymisé ne contient plus de motif
   détectable par la couche `detect/` en catégorie `DIRECT`.
3. **Fuite de valeurs gold** : aucune valeur gold d'identifiant direct du
   corpus ne subsiste dans le texte anonymisé. C'est le contrôle le plus
   important — il se calcule par recherche exacte, indépendamment du détecteur.

```python
@dataclass(frozen=True)
class ValidationOutcome:
    ok: bool
    leaked_direct: tuple[str, ...]
    malformed_placeholders: tuple[str, ...]
    residual_patterns: tuple[str, ...]
```

`fail_on_leak` est configurable (défaut `false` : journalise et marque le
document, sans interrompre le run).

### Critères d'acceptation

- [ ] Un texte non anonymisé déclenche `leaked_direct` non vide.
- [ ] Un texte entièrement supprimé déclenche `leaked_direct` vide.
- [ ] Le contrôle de fuite gold est **indépendant du détecteur** : un test le
      prouve en passant une annotation gold que le détecteur ne trouve pas.
- [ ] `fail_on_leak=True` interrompt bien le document concerné, et lui seul.

---

## C-3 — Commande `anonv2 predict`

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | C-1, A-3 |
| **Spécs** | SPEC-10 §5 |
| **Effort** | 0,75 j |

### Périmètre

- `src/anonymisation/cli/predict.py`
- `tests/integration/test_predict.py`

### Commande

```bash
anonv2 predict --dataset tab --split test --policy P2 \
               --profile deterministic --out runs/<run_id>/
```

### Sorties

| Fichier | Contenu |
|---------|---------|
| `predictions.jsonl` | une ligne par document : `doc_id`, `status`, `annotations`, `decisions`, `anonymized_text`, `risk`, `runtime_ms` |
| `traces.jsonl` | les `StageTrace` |
| `manifest.lock.json` | les 7 éléments de reproductibilité de SPEC-09 §5 : version des données, `taxonomy_version`, commit git, modèles, seeds, prompts, politique |

### Critères d'acceptation

- [ ] Traite l'intégralité de chaque corpus en profil `deterministic` avec
      **0 % d'erreur**.
- [ ] Deux exécutions successives produisent des `predictions.jsonl`
      **identiques bit à bit**.
- [ ] Une prédiction en erreur porte `status: "error"` et un champ `error`,
      **jamais** une liste d'annotations vide (voir C-5).
- [ ] `manifest.lock.json` contient le commit git courant.
- [ ] `--limit N` fonctionne et est reflété dans le lock (statut dégradé en
      `sampled`).

---

## C-4 — Commande `anonv2 score`

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | C-3, D-1 |
| **Spécs** | SPEC-10 §5, audit v1 §12.6 |
| **Effort** | 0,5 j |

### Contexte

Exigence structurante : **le scoring ne relance jamais les modèles**. Il doit
pouvoir tourner des dizaines de fois sur les mêmes prédictions. C'est ce qui
permet de corriger une métrique sans relancer une campagne de plusieurs heures,
et c'est ce qui rend un résultat contestable **vérifiable**.

### Périmètre

- `src/anonymisation/cli/score.py`
- `tests/integration/test_score.py`

### Commande

```bash
anonv2 score --run runs/<run_id>/ --protocol tab-official
```

### Critères d'acceptation

- [ ] Fonctionne **hors ligne, sans charger aucun modèle** (test : le module de
      détection n'est jamais importé — vérifiable via `sys.modules`).
- [ ] Produit `scorecard.json` au format SPEC-07 §10, avec les trois
      ventilations obligatoires (`by_language`, `by_domain`, `by_expression`).
- [ ] Rejouer `score` deux fois donne un résultat identique.
- [ ] Un run dont le `taxonomy_version` diffère est **refusé** avec un message
      demandant une reprédiction.

---

## C-5 — Comptabilité d'erreur (contrainte C4)

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | C-3 |
| **Spécs** | SPEC-10 §2 contrainte C4, §4 |
| **Effort** | 0,25 j |

### Contexte — la leçon la plus importante de l'audit v1

La campagne v1 a publié :

```
TAB     : documents traités = 127, erreurs = 127, taux d'erreur = 1.0,
          prédictions = 0, strict F1 = 0
DB-bio  : erreurs = 239 / 239, fuites gold = 305 / 305
```

Ces « F1 » n'étaient pas des performances de pipeline mais des **taux d'échec
d'exécution déguisés en métriques**. Un document en erreur avait été compté
comme une prédiction vide.

### Périmètre

- `src/anonymisation/metrics/accounting.py`
- `tests/unit/test_accounting.py`

### Travail

```python
@dataclass(frozen=True)
class RunAccounting:
    documents_total: int
    documents_scored: int
    documents_errored: int
    error_rate: float
    errors_by_stage: dict[str, int]
    errors_by_type: dict[str, int]
```

Règles :

1. Un document `status != "ok"` est **exclu du calcul des métriques**.
2. Il est compté séparément dans `errors_by_stage`.
3. **Toute scorecard porte son `error_rate`**, en évidence.
4. Si `error_rate > 0`, le statut de toutes les métriques du run est dégradé au
   maximum à `SAMPLED`, et jamais `OFFICIAL`.
5. Si `error_rate > 0.05`, `score` émet un avertissement bloquant : le run n'est
   pas publiable en l'état.

### Critères d'acceptation

- [ ] Un run avec 10 % d'erreurs ne peut pas produire de métrique `OFFICIAL`.
- [ ] `error_rate` figure dans la scorecard, au premier niveau.
- [ ] Un document en erreur n'apparaît ni dans les TP, ni dans les FP, ni dans
      les FN — un test le prouve en comparant les dénominateurs.
- [ ] `errors_by_stage` permet d'identifier l'étape fautive.

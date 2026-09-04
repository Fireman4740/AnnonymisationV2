# SPEC-10 — Pipeline d'anonymisation et protocole d'exécution

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.1 |
| **Date** | 2026-09-04 |
| **Dépend de** | SPEC-01, SPEC-02, SPEC-06, SPEC-07 |
| **Origine** | Recommandations §12 de l'audit du dépôt v1 |

---

## 1. Objet

Définir le **runtime d'anonymisation** : les étapes, leurs contrats, la place
des LLM, et la séparation entre prédiction, scoring et attaque.

## 2. Leçons de la v1 — contraintes de conception

L'audit du dépôt v1 documente un échec instructif : la campagne d'évaluation
complète a produit **84 % d'erreurs sur `anonymization`, 100 % sur DB-bio et
100 % sur TAB**, pour cause de timeouts LLM, de JSON vides, de réponses
tronquées (`finish_reason=length`) et de budget de contexte consommé par le
raisonnement.

Cinq contraintes en découlent, **normatives** :

| # | Contrainte |
|---|-----------|
| **C1** | Le **noyau est déterministe et hors ligne**. Un pipeline complet DOIT s'exécuter sans aucun appel LLM, sans GPU et sans réseau. |
| **C2** | Les LLM sont des **étapes optionnelles, désactivées par défaut**, chacune activable indépendamment. |
| **C3** | Une réponse LLM vide NE DOIT JAMAIS être interprétée comme « aucune entité trouvée ». C'est une **erreur**. |
| **C4** | Une campagne qui échoue DOIT **échouer explicitement**, jamais produire un score partiel ambigu. |
| **C5** | Le **scoring ne relance pas les modèles** : il travaille depuis les prédictions figées. |

C4 est le garde-fou le plus important : les chiffres de la v1 (« strict F1 =
0.1242 ») n'étaient pas une performance de pipeline mais un taux d'échec
d'exécution déguisé en métrique.

## 3. Les étapes

```
                        TEXTE ORIGINAL
                              │
        ┌─────────────────────▼─────────────────────┐
        │ 1. DETECT      déterministe (regex+règles)│  obligatoire
        │                + NER optionnel            │
        │                + LLM reviewer optionnel   │
        └─────────────────────┬─────────────────────┘
                              │ Candidate[]
        ┌─────────────────────▼─────────────────────┐
        │ 2. FUSE        fusion explicable          │  obligatoire
        └─────────────────────┬─────────────────────┘
                              │ Annotation[] + FusionDecision[]
        ┌─────────────────────▼─────────────────────┐
        │ 3. ASSESS      k combinatoire → risque    │  obligatoire
        │                (SPEC-06)                  │
        └─────────────────────┬─────────────────────┘
                              │ RiskAssessment
        ┌─────────────────────▼─────────────────────┐
        │ 4. PLAN        politique → décisions      │  obligatoire
        └─────────────────────┬─────────────────────┘
                              │ AnonymizationDecision[]
        ┌─────────────────────▼─────────────────────┐
        │ 5. TRANSFORM   application, droite→gauche │  obligatoire
        └─────────────────────┬─────────────────────┘
                              │ TransformResult
        ┌─────────────────────▼─────────────────────┐
        │ 6. VALIDATE    placeholders, fuites,      │  obligatoire
        │                motifs interdits           │
        └─────────────────────┬─────────────────────┘
                              │
        ┌─────────────────────▼─────────────────────┐
        │ 7. AUDIT       LLM adversarial            │  OPTIONNEL, off
        └─────────────────────┬─────────────────────┘
        ┌─────────────────────▼─────────────────────┐
        │ 8. REWRITE     paraphrase ciblée + boucle │  OPTIONNEL, off
        │                bornée, puis retour en 6   │
        └─────────────────────┬─────────────────────┘
                              ▼
                       TEXTE ANONYMISÉ
```

Les étapes 1 à 6 constituent le **noyau déterministe**. Elles suffisent à
produire un résultat sur l'intégralité des corpus d'évaluation.

### Invariant transverse

> **Tous les offsets réfèrent au texte original, à toutes les étapes.**

C'est l'invariant que la v1 avait bien identifié et qu'il faut conserver. Une
étape qui produirait des offsets relatifs à un texte partiellement transformé
corromprait silencieusement toutes les suivantes.

## 4. Contrats d'étape

```python
@dataclass(frozen=True)
class StageTrace:
    stage: str
    order: int
    entities_in: int
    entities_out: int
    duration_ms: float
    sha256_before: str
    sha256_after: str
    added: tuple[str, ...]
    removed: tuple[str, ...]
    modified: tuple[str, ...]
    decisions: tuple[dict, ...]
    status: str            # "ok" | "skipped" | "error"
    error: str | None = None

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
```

Les `StageTrace` sont un acquis de la v1 à conserver : ce sont eux qui rendent
une décision d'anonymisation auditable après coup.

**Règle C4 appliquée** : un document dont `status != "ok"` est **exclu du
calcul des métriques** et compté séparément dans `errors_by_stage`. Il n'est
jamais compté comme une prédiction vide, ce qui gonflerait artificiellement la
précision et effondrerait le rappel.

## 5. Séparation prédiction / scoring / attaque

Trois commandes conceptuellement distinctes (audit §12.6) :

```bash
anonv2 predict --dataset tab --split test --policy P2 --out runs/<run_id>/
anonv2 score   --run runs/<run_id>/ --protocol tab-official
anonv2 attack  --run runs/<run_id>/ --attacker A
```

| Commande | Entrée | Sortie | Relance les modèles ? |
|----------|--------|--------|----------------------|
| `predict` | dataset normalisé + politique | `predictions.jsonl` + `traces.jsonl` + `manifest.lock.json` | oui |
| `score` | prédictions + vérité terrain + protocole | `scorecard.json` | **non** |
| `attack` | prédictions + population | `attack.json` | oui (LLM) |

`score` doit pouvoir tourner des dizaines de fois sur les mêmes prédictions —
c'est ce qui permet de corriger une métrique sans relancer une campagne de
plusieurs heures. C'est aussi ce qui rend un résultat contestable **vérifiable**.

### Format de `predictions.jsonl`

```json
{"doc_id": "tab:001-83927", "status": "ok",
 "annotations": [...], "decisions": [...],
 "anonymized_text": "...", "risk": {...}, "runtime_ms": 42.1}
```

Une prédiction en erreur porte `status: "error"` et `error`, **jamais** une
liste d'annotations vide.

## 6. Place des LLM

Chaque appel LLM DOIT avoir (audit §12.4) :

| Exigence | Détail |
|----------|--------|
| Schéma JSON validé | Réponse non conforme = erreur, pas un résultat vide |
| Contexte maximal | Déclaré, avec découpage en chunks au-delà |
| Timeout par appel | Obligatoire |
| Limite de retries | Obligatoire |
| Réponse vide = erreur | Règle C3 |
| Repli déterministe | Le pipeline continue sans l'étape LLM, en le traçant |
| Modèle spécialisé par rôle | reviewer / verifier / auditor / rewriter séparés |
| Métrique de taux de réponse valide | Publiée avec tout résultat LLM |

Les quatre rôles :

| Rôle | Fonction | Défaut |
|------|----------|--------|
| `reviewer` | Compare original et texte partiellement anonymisé, ajoute les entités manquées | off |
| `verifier` | Confirme, retype ou étend une entité. **Ignore les décisions `remove`** (privacy-first : on ne supprime pas une détection sur avis LLM) | off |
| `auditor` | Cherche fuites directes, QI, combinaisons à risque. Score = **max** des scores par chunk, jamais la moyenne | off |
| `rewriter` | Réécrit uniquement les chunks porteurs de preuve de fuite ; conserve l'original si la sortie est suspecte | off |

### 6.1 Backends interchangeables

Les backends sont déclarés dans `configs/llm/backends.yaml` (source unique,
§8). Chaque backend porte :

- `kind` : `openai_compatible`, `anthropic` ou `null` ;
- `model` : l'identifiant du modèle servi ;
- `api_key_env` **ou** `api_key_cmd` : la référence à la clé. La clé elle-même
  n'est **jamais** écrite dans le fichier : elle est lue à l'exécution (variable
  d'environnement nommée, ou commande dont la sortie standard est la clé).

Deux backends structurent l'exécution :

| Backend | Rôle | Détail |
|---------|------|--------|
| `qwen_local` (**défaut**) | Serveur local | vLLM hébergeant Qwen3.8-27B (W4A16), piloté par `F:\IA\Qwen3.8\qwen.ps1` (`start` / `stop` / `status` / `logs`), port 18020. Respecte la contrainte projet « modèles locaux < 30 B ». |
| `null` | Aucun LLM | `kind: null`, modèle nul. Permet de faire tourner le pipeline de bout en bout **sans GPU** : c'est le seul backend compatible avec C1 (pas de réseau, pas de GPU). |

Les backends distants (ex. `sonnet` / Anthropic, clé en variable
`ANTHROPIC_API_KEY`) servent de borne supérieure de qualité ; ils sont soumis à
la règle de confidentialité de §6.5.

### 6.2 Cache LLM obligatoire

Le cache LLM est **obligatoire** (`cache.enabled: true`, §6.1). Règles :

- **Clé de cache** = `sha256(backend + model + prompt + params)` : elle inclut
  le backend et le modèle, donc un cache n'est jamais partagé entre deux
  backends — un résultat Sonnet n'est pas un résultat Qwen.
- **Pas de TTL** : mêmes entrées → mêmes sorties. Le cache est une composante
  de la déterminisme du pipeline (C1, C5), pas une optimisation optionnelle.
- **Motif** : sans cache, chaque réévaluation re-coûte des heures de GPU, et
  les comparaisons entre politiques ne sont plus isolées du bruit du modèle —
  une politique ne se compare à une autre que si, à prompt égal, le modèle
  répond identiquement dans les deux campagnes.

### 6.3 Affectation par rôle

Chaque rôle d'appel LLM est affecté à un backend **indépendamment** des autres
(`roles:` de `backends.yaml`) : un rôle peut tourner sur un autre modèle que le
défaut. Les rôles du runtime :

| Rôle | Usage |
|------|-------|
| `detection` | Les étapes LLM de détection du pipeline (§6 : `reviewer`, `verifier`). |
| `generation` | La génération de corpus synthétiques (SPEC-05). Le modèle générateur ne doit pas être un modèle évalué comme détecteur (SPEC-05 §7) — sinon le détecteur reconnaît son propre style. |
| `attacker_a` | Attaquant A (SPEC-08). |
| `attacker_b` | Attaquant B — borne supérieure de qualité (SPEC-08). |
| `paraphrase` | La réécriture ciblée (§7, rôle `rewriter`). |

**Règle de publication** : le backend (et le modèle) utilisé pour chaque rôle
doit figurer dans **tout** rapport — traces du pipeline, scorecards, rapports
d'attaque. Un résultat obtenu avec Sonnet n'est pas comparable à un résultat
obtenu avec Qwen ; un rapport qui omet son backend est incomplet.

### 6.4 Messages d'erreur actionnables et exécution sans LLM

Chaque erreur de la couche LLM doit être **actionnable**, jamais un timeout
opaque :

| Échec | Message exigé |
|-------|---------------|
| Clé d'API absente | Le nom exact de la variable d'environnement (ou de la commande) attendue, et comment l'obtenir. |
| Serveur local injoignable | La commande de démarrage du serveur — ex. `qwen.ps1 start` — avec le temps de boot attendu. Le health check du backend porte un champ `hint` pour ce message. |
| Réponse non JSON | Une tentative de réparation ; si elle échoue, repli explicite vers le chemin déterministe (règle C3 : une réponse vide est une **erreur**, jamais « aucune entité trouvée »). |

L'exécution **sans LLM** (backend `null`, profil `deterministic`) est le mode de
référence du pipeline, pas un mode dégradé : chaque étape LLM désactivée est
tracée explicitement (`status: "skipped"`), de sorte qu'un rapport distingue
toujours ce qui a été mesuré avec un LLM de ce qui ne l'a pas été.

### 6.5 Confidentialité du système lui-même

Risque P1 identifié par l'audit : le pipeline peut envoyer à un fournisseur
externe le texte **original**, les entités et l'audit.

**Règle** : le mode par défaut est `local`. Tout envoi vers un fournisseur
externe exige `llm.allow_remote: true` explicite dans la configuration, et est
**interdit** sur les corpus contenant des personnes réelles (TAB, DB-bio,
SupportTicketsReal, CleanCoNLL) — même garde que E2 de
[SPEC-08](SPEC-08-attaquants.md), appliquée en code.

## 7. Boucle de réécriture (RUPTA)

Une **seule** implémentation, séparée de l'orchestration (audit §12.5) :

```
AuditResult → RewriteProposal → CandidateResult → évaluation privacy/utility → sélection
```

Bornes obligatoires : nombre maximal d'itérations, budget temps, critère de
convergence, **détection de non-progression**. Sans la dernière, la boucle
tourne sur place — c'est ce qui donnait l'impression de blocage en v1.

## 8. Configuration

**Une seule source de configuration** (l'audit relève six sources concurrentes
en v1) :

```
configs/
├── runtime/<profil>.yaml     # detect, fuse, llm, budgets
├── llm/backends.yaml         # backends LLM interchangeables, cache, rôles (§6)
├── policy/policies.yaml      # P0..P4 (SPEC-06 §9)
├── detection/patterns.yaml   # motifs et lexiques
├── generalization/hierarchies.yaml
├── datasets/<clé>.yaml       # manifestes (SPEC-03)
└── populations/<id>.yaml     # populations de référence (SPEC-06)
```

Ordre de résolution, du plus faible au plus fort : valeurs par défaut du code →
fichier de profil → variables d'environnement → surcharges de ligne de
commande. Toute valeur effective est journalisée dans le `manifest.lock.json`
du run.

## 9. Profils d'exécution

| Profil | Étapes actives | Usage |
|--------|----------------|-------|
| `deterministic` | 1–6, sans NER ni LLM | **Défaut.** Rapide, reproductible, aucune dépendance lourde |
| `ner` | 1–6 avec NER local | Quand GLiNER/spaCy sont installés |
| `llm-audit` | 1–7 | Ajoute l'audit adversarial |
| `full` | 1–8 | Boucle complète de réécriture |

Le profil `deterministic` DOIT produire un résultat sur **100 % des documents
de tous les corpus d'évaluation**. C'est le critère d'acceptation du pipeline.

## 10. Critères d'acceptation

- [ ] `anonv2 predict --profile deterministic` traite l'intégralité de chaque
      corpus avec **0 % de documents en erreur**.
- [ ] Deux exécutions successives produisent des `predictions.jsonl`
      **identiques bit à bit**.
- [ ] `anonv2 score` fonctionne sans relancer aucun modèle.
- [ ] Le texte anonymisé ne contient **aucune valeur gold d'identifiant
      direct** (contrôle de fuite de l'étape 6).
- [ ] Tout document en erreur est exclu des métriques et compté à part.
- [ ] Les tests de sanité S1–S3 de [SPEC-07 §11](SPEC-07-metriques.md) passent :
      texte non anonymisé → risque élevé ; texte supprimé → risque ≈ 0 ;
      politique plus stricte → risque décroissant et utilité décroissante.
- [ ] Aucun appel réseau n'est émis en profil `deterministic` (test avec socket
      désactivé).
- [ ] Tout rapport (scorecard, rapport d'attaque) indique pour chaque rôle LLM
      le backend et le modèle utilisés (§6.3).

## 11. Journal des modifications

| Version | Date | Changement |
|---------|------|-----------|
| 1.0 | 2026-08-30 | Création. Huit étapes, contraintes C1–C5 issues de l'audit v1, séparation predict/score/attack, règles LLM. |
| 1.1 | 2026-09-04 | **Ticket F-1 — réconciliation avec `configs/llm/backends.yaml`.** Le fichier 1.0 de cette spécification a été réécrit par-dessus la version antérieure sans lecture préalable ; celle-ci est irrécupérable (fichier non versionné, aucune copie). La numérotation en vigueur (§1–§11), référencée par une vingtaine d'endroits (docstrings, `configs/runtime/deterministic.yaml`, tickets, roadmap), est donc conservée ; c'est le fichier de configuration qui est corrigé vers elle. §6 est complété par les éléments que `backends.yaml` documentait et que la version 1.0 ne couvrait pas : §6.1 backends interchangeables (clé jamais écrite, `qwen_local` Qwen3.8-27B vLLM port 18020 par défaut, backend `null` sans GPU), §6.2 cache LLM obligatoire (clé `sha256(backend + model + prompt + params)`, sans TTL), §6.3 affectation par rôle (detection, generation, attacker_a, attacker_b, paraphrase) et règle « le backend figure dans tout rapport », §6.4 messages d'erreur actionnables et exécution sans LLM ; ancienne sous-section de confidentialité renumérotée §6.5. `llm/backends.yaml` ajouté à l'arborescence de configuration (§8) ; nouveau critère d'acceptation §10. |

# SPEC-10 — Pipeline d'anonymisation et protocole d'exécution

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date** | 2026-08-30 |
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

### Confidentialité du système lui-même

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

## 11. Journal des modifications

| Version | Date | Changement |
|---------|------|-----------|
| 1.0 | 2026-08-30 | Création. Huit étapes, contraintes C1–C5 issues de l'audit v1, séparation predict/score/attack, règles LLM. |

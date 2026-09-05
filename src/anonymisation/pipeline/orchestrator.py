"""Orchestrateur des huit étapes du pipeline d'anonymisation (SPEC-10 §3-4).

Enchaîne le noyau déterministe ::

    DETECT → FUSE → ASSESS → PLAN → TRANSFORM → VALIDATE

puis les deux étapes LLM (AUDIT, REWRITE) qui ne sont **pas implémentées en
v1** : elles produisent une trace ``status="skipped"`` et jamais une absence
de trace (audit v1 §12.3 — chaque étape reste auditable).

Contraintes normatives appliquées ici :

* **C1** — le profil ``deterministic`` s'exécute sans LLM, sans GPU, sans
  réseau : les seules briques appelées sont ``detect/``, ``policy/``,
  ``transform/`` (aucune dépendance de graphe : le domaine est autonome) ;
* **C4** — un document en erreur est explicitement marqué
  (``status="error"`` + ``errors``), jamais compté comme une prédiction
  vide ; les erreurs suivent la convention ``"ÉTAPE: détail"`` pour la
  comptabilité d'``errors_by_stage`` (C-5) ;
* **Invariant des offsets** — toutes les annotations et décisions portent
  des offsets relatifs au **texte original** ; la transformation s'applique
  de droite à gauche (``transform.apply``) ;
* **Déterminisme** — aucun horloge murale dans les résultats : les durées
  sont mesurées en mémoire mais l'écriture strict les nulle (SPEC-10 §10,
  géré à la sérialisation) ; tout tri est explicite et stable.

Capacités non implantées (NER, relecteur LLM, audit, réécriture, estimateur
autre que ``naive``, LLM distant) → :class:`PipelineCapabilityError` à la
construction, avec un message actionnable : **aucune dégradation silencieuse**.
"""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path
from typing import Final

from anonymisation.detect.base import Candidate, candidates_to_annotations
from anonymisation.detect.fusion import fuse
from anonymisation.detect.patterns import apply_patterns, load_patterns
from anonymisation.detect.rules import apply_rules
from anonymisation.pipeline.profiles import FUSE_STRATEGIES, RuntimeProfile, _repo_root
from anonymisation.pipeline.traces import (
    LLM_STAGES,
    STAGE_ORDER,
    PipelineResult,
    RiskAssessment,
    StageTrace,
    entity_key,
)
from anonymisation.pipeline.validate_stage import validate_anonymization
from anonymisation.policy.engine import (
    NaiveRiskEstimator,
    PolicyEngine,
)
from anonymisation.policy.engine import (
    _QiState as _EngineQiState,
)
from anonymisation.policy.models import load_policy_set
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import IdentifierType
from anonymisation.transform.apply import apply_decisions
from anonymisation.transform.decisions import Action, AnonymizationDecision
from anonymisation.transform.pseudonymize import PseudoMapper


class PipelineCapabilityError(ValueError):
    """Capacité demandée au profil mais non implémentée en v1.

    Levée à la construction (jamais en cours d'exécution) : un profil qui
    active une brique inexistante est une erreur de configuration, pas un
    comportement. Le message nomme la brique et la correction attendue.
    """


def _now_ms() -> float:
    """Horloge monotone en ms (durées de trace uniquement, jamais de contenu)."""
    return time.monotonic() * 1000.0


def _sha256_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


#: Ordre de protection croissante des actions, pour la fusion conservatoire
#: des décisions non-KEEP qui se chevauchent (multi-label imbriqué, I-ANN-5).
_ACTION_PRIORITY: Final[tuple[Action, ...]] = (
    Action.SUPPRESS,
    Action.PSEUDONYMIZE,
    Action.MASK,
    Action.GENERALIZE,
    Action.KEEP,
)


@dataclass
class _RunState:
    """État mutable d'une exécution sur un document (interne au run)."""

    doc: Document
    gold: tuple[Annotation, ...]
    current_text: str
    candidates: list[Candidate] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)
    decisions: list[AnonymizationDecision] = field(default_factory=list)
    #: Décisions réellement appliquées au texte par TRANSFORM (non-KEEP,
    #: chevauchements fusionnés). VALIDATE contrôle celles-ci : contrôler les
    #: décisions planifiées signalerait comme « placeholder manquant » tout
    #: remplacement qu'une fusion a remplacé par la suppression du span union.
    applied_decisions: list[AnonymizationDecision] = field(default_factory=list)
    risk: RiskAssessment | None = None
    traces: list[StageTrace] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    has_nonfatal_findings: bool = False
    interrupted: bool = False


def _merge_overlapping(
    decisions: Sequence[AnonymizationDecision],
    text: str,
) -> list[AnonymizationDecision]:
    """Fusion conservatoire des décisions non-KEEP qui se chevauchent.

    ``apply_decisions`` refuse tout chevauchement (un chevauchement
    silencieux = texte corrompu). Or des annotations multi-label
    imbriquées (I-ANN-5, ex. « infirmière au CHU de Lille ») peuvent
    produire des décisions non-KEEP sur des spans qui se chevauchent.
    Fusion par **union du span** : l'action retenue est la plus protectrice
    (``SUPPRESS > PSEUDONYMIZE > MASK > GENERALIZE``) et le ``reason``
    documente la fusion (les membres sont listés dans ``meta``). Le tri par
    offsets rend le résultat déterministe.

    Le remplacement est un **placeholder nommant les catégories fusionnées**,
    et non la chaîne vide. Un placeholder ne divulgue rien de plus qu'une
    suppression pure — il ne porte que des noms de catégories — mais il
    évite trois effets de bord d'une suppression silencieuse : la perte de
    l'indice qu'une information a été retirée, les artefacts de texte
    (doubles espaces) et surtout la distorsion de la mesure d'utilité, une
    chaîne vide et un placeholder ne coûtant pas la même distance au texte
    original.
    """
    if not decisions:
        return []
    ordered = sorted(decisions, key=lambda d: (d.start, d.end, d.qi_category))
    merged: list[AnonymizationDecision] = []
    buffer: list[AnonymizationDecision] = []

    def _flush() -> None:
        if not buffer:
            return
        if len(buffer) == 1:
            merged.append(buffer[0])
        else:
            start = buffer[0].start
            end = max(d.end for d in buffer)
            categories = tuple(sorted({d.qi_category for d in buffer}))
            action = next(p for p in _ACTION_PRIORITY if any(d.action is p for d in buffer))
            merged.append(
                AnonymizationDecision(
                    start=start,
                    end=end,
                    original=text[start:end],
                    action=action,
                    replacement=f"[{'+'.join(categories)}_SUPPRIME]",
                    qi_category=buffer[0].qi_category,
                    reason=(
                        f"Fusion de {len(buffer)} décisions chevauchantes (catégories : "
                        f"{', '.join(categories)}) : suppression du span union — aucune "
                        f"valeur d'origine n'est conservée."
                    ),
                    meta={
                        "merged_members": [
                            {
                                "start": d.start,
                                "end": d.end,
                                "action": d.action.value,
                                "qi_category": d.qi_category,
                            }
                            for d in buffer
                        ]
                    },
                )
            )
        buffer.clear()

    for decision in ordered:
        if buffer and decision.start < max(item.end for item in buffer):
            buffer.append(decision)
        else:
            _flush()
            buffer.append(decision)
    _flush()
    return merged


class Pipeline:
    """Exécution du pipeline sur des documents du format pivot.

    ``profile`` : un :class:`RuntimeProfile` chargé (ou un chemin / nom de
    profil, alors ``config_path`` est ignoré) ; ``policy_id`` : politique
    effective, sinon celle du profil (``stages.plan.policy``).

    Une construction en échec (:class:`PipelineCapabilityError`) signifie que
    le profil demande une capacité non implémentée — jamais un comportement
    dégradé en silence.
    """

    def __init__(
        self,
        profile: RuntimeProfile | str | Path,
        *,
        config_path: Path | None = None,
        policy_id: str | None = None,
    ) -> None:
        if not isinstance(profile, RuntimeProfile):
            from anonymisation.pipeline.profiles import load_runtime_profile

            loaded = load_runtime_profile(profile)
            profile = loaded.profile
            config_path = loaded.config_path

        self._profile = profile
        self._config_path = config_path

        stages = profile.stages
        # --- Garanties de noyau (audit §12.1) : aucune étape obligatoire
        # désactivable en silence.
        for name, spec in (
            ("DETECT", stages.detect),
            ("FUSE", stages.fuse),
            ("ASSESS", stages.assess),
            ("PLAN", stages.plan),
            ("TRANSFORM", stages.transform),
            ("VALIDATE", stages.validation),
        ):
            if not spec.enabled:
                raise PipelineCapabilityError(
                    f"Profil {profile.profile!r} : l'étape obligatoire {name} est désactivée — "
                    "donner aucune garantie (audit v1 §12.1). "
                    "Réactive-la ou choisis un autre profil."
                )

        # --- Capacités non implémentées en v1 : échec explicite à la construction.
        if not stages.detect.deterministic.enabled:
            raise PipelineCapabilityError(
                "Profil "
                f"{profile.profile!r} : le détecteur déterministe est désactivé — il est la seule "
                "source de détection implantée en v1 (NER et LLM reviewer ne le sont pas)."
            )
        if stages.detect.ner.enabled:
            raise PipelineCapabilityError(
                f"Profil {profile.profile!r} : stages.detect.ner.enabled=true demande un détecteur "
                "NER (GLiNER/spaCy) qui n'est pas implémenté en v1. Utilise le profil "
                "« deterministic » (sans NER) ou attends le profil « ner »."
            )
        if stages.detect.llm_reviewer.enabled:
            raise PipelineCapabilityError(
                f"Profil {profile.profile!r} : stages.detect.llm_reviewer.enabled=true — le "
                "relecteur LLM n'est pas implémenté en v1 (audit §12.4). Utilise le profil "
                "« deterministic » ou attends le profil « llm-audit »."
            )
        if stages.audit.enabled:
            raise PipelineCapabilityError(
                f"Profil {profile.profile!r} : stages.audit.enabled=true — l'audit LLM "
                "adversarial n'est pas implémenté en v1 (audit §12.3). Utilise le profil "
                "« deterministic » ou attends le profil « llm-audit »."
            )
        if stages.rewrite.enabled:
            raise PipelineCapabilityError(
                f"Profil {profile.profile!r} : stages.rewrite.enabled=true — la boucle de "
                "réécriture (RUPTA) n'est pas implémentée en v1. "
                "Utilise le profil « deterministic »."
            )
        if profile.llm.allow_remote:
            raise PipelineCapabilityError(
                f"Profil {profile.profile!r} : llm.allow_remote=true — l'envoi de texte vers un "
                "fournisseur externe n'est pas implémenté (ni autorisable) en v1."
            )
        if stages.assess.estimator != "naive":
            raise PipelineCapabilityError(
                f"Profil {profile.profile!r} : assess.estimator={stages.assess.estimator!r} — "
                "le seul estimateur implémenté en v1 est « naive » (sorties marquées PROXY, "
                "SPEC-07 §9). Les estimateurs de SPEC-06 arrivent avec le lot L4."
            )

        # --- Domaine des valeurs de configuration (redondant avec le
        # loader, utile pour les profils construits directement).
        if stages.fuse.strategy not in FUSE_STRATEGIES:
            raise PipelineCapabilityError(
                f"Profil {profile.profile!r} : stages.fuse.strategy={stages.fuse.strategy!r} "
                "n'est pas une stratégie de fusion connue."
            )
        if stages.transform.masking.mode not in ("full", "partial"):
            raise PipelineCapabilityError(
                f"Profil {profile.profile!r} : stages.transform.masking.mode="
                f"{stages.transform.masking.mode!r} — valeurs : 'full' | 'partial'."
            )

        # --- Résolution des références de configuration.
        patterns_path = self._resolve_reference(stages.detect.deterministic.patterns)
        self._patterns, self._lexicons = load_patterns(patterns_path)

        policies_path = self._resolve_reference(stages.plan.policy_set)
        policy_set = load_policy_set(policies_path)
        self._policy_id = policy_id or stages.plan.policy
        policy = policy_set.get(self._policy_id)

        # --- Briques partagées (construites une fois, réutilisées par doc).
        self._estimator = NaiveRiskEstimator()
        self._engine = PolicyEngine(policy)

    # ------------------------------------------------------------------ #
    # Résolution de configuration
    # ------------------------------------------------------------------ #
    def _resolve_reference(self, ref: str) -> Path:
        """Résout une référence relative du profil : d'abord relativement au
        répertoire du fichier de profil, puis à la racine du dépôt."""
        tried: list[Path] = []
        if self._config_path is not None:
            tried.append(self._config_path.parent / ref)
        root = _repo_root(self._config_path.parent if self._config_path is not None else Path.cwd())
        if root is not None:
            candidate = root / ref
            if candidate not in tried:
                tried.append(candidate)
        for path in tried:
            if path.is_file():
                return path
        raise PipelineCapabilityError(
            f"Profil {self._profile.profile!r} : impossible de résoudre la référence {ref!r} "
            f"(cherché : {', '.join(str(p) for p in tried)})."
        )

    # ------------------------------------------------------------------ #
    # Exécution
    # ------------------------------------------------------------------ #
    def run(
        self,
        doc: Document,
        gold_annotations: Sequence[Annotation] | None = None,
    ) -> PipelineResult:
        """Exécute les huit étapes sur ``doc``.

        ``gold_annotations`` : annotations du pivot (vérité terrain) ; si
        fournies, l'étape VALIDATE y cherche les valeurs d'identifiants
        directs qui auraient survécu à l'anonymisation (contrôle de fuite
        par recherche exacte, indépendant du détecteur).

        Garanties :
        * exactement 8 ``StageTrace`` par document (les étapes non
          exécutées portent ``status="skipped"``, jamais une absence) ;
        * toute exception d'étape est convertie en ``status="error"`` avec
          l'étape nommée — une exception ne s'échappe jamais de ``run`` ;
        * tous les offsets portent sur ``doc.text`` (invariant SPEC-10 §4).
        """
        t_start = _now_ms()
        state = _RunState(
            doc=doc,
            gold=tuple(gold_annotations or ()),
            current_text=doc.text,
        )

        # --- Garde-fou de budget (contrainte C4) : un document hors budget
        # est marqué en erreur et exclu — jamais compté comme prédiction
        # vide. Le contrôle est déterministe (taille du texte).
        max_chars = self._profile.budgets.max_document_chars
        if len(doc.text) > max_chars:
            return self._excluded_result(
                state,
                t_start,
                f"document de {len(doc.text)} caractères > budget {max_chars} "
                f"(profil {self._profile.profile!r})",
            )

        failed_stage: str | None = None
        for order, stage in enumerate(STAGE_ORDER, start=1):
            sha_before = _sha256_text(state.current_text)

            if state.interrupted or failed_stage is not None:
                # Étapes en aval d'une interruption : trace « skipped »
                # explicite (jamais d'absence de trace).
                state.traces.append(
                    StageTrace(
                        stage=stage,
                        order=order,
                        entities_in=0,
                        entities_out=0,
                        duration_ms=0.0,
                        sha256_before=sha_before,
                        sha256_after=sha_before,
                        decisions=(
                            {
                                "kind": "skipped",
                                "reason": f"non exécuté — {failed_stage or 'VALIDATE'} "
                                "a interrompu le document",
                            },
                        ),
                        status="skipped",
                    )
                )
                continue

            if stage in LLM_STAGES:
                # AUDIT / REWRITE : non implémentés en v1 (audit §12.3).
                state.traces.append(
                    StageTrace(
                        stage=stage,
                        order=order,
                        entities_in=0,
                        entities_out=0,
                        duration_ms=_now_ms() - t_start,
                        sha256_before=sha_before,
                        sha256_after=sha_before,
                        decisions=(
                            {
                                "kind": "skipped",
                                "reason": "étape LLM non implémentée en v1 (audit v1 §12.3) — "
                                "jamais activée",
                            },
                        ),
                        status="skipped",
                    )
                )
                continue

            t0 = _now_ms()
            before_count = len(state.annotations)
            try:
                trace = getattr(self, f"_stage_{stage.lower()}")(state)
            except Exception as exc:  # noqa: BLE001 — conversion explicite, jamais de crash silencieux
                failed_stage = stage
                state.interrupted = True
                state.errors.append(f"{stage}: {exc}")
                state.traces.append(
                    StageTrace(
                        stage=stage,
                        order=order,
                        entities_in=before_count,
                        entities_out=before_count,
                        duration_ms=_now_ms() - t0,
                        sha256_before=sha_before,
                        sha256_after=sha_before,
                        status="error",
                        error=f"{stage}: {exc}",
                    )
                )
                continue
            state.traces.append(trace)

        status = "error" if (state.interrupted or failed_stage is not None) else (
            "partial" if state.has_nonfatal_findings else "ok"
        )
        return PipelineResult(
            doc_id=doc.doc_id,
            original_text=doc.text,
            anonymized_text=state.current_text,
            annotations=tuple(state.annotations),
            decisions=tuple(state.decisions),
            risk=state.risk,
            policy_id=self._policy_id,
            traces=tuple(state.traces),
            status=status,
            errors=tuple(state.errors),
            runtime_ms=_now_ms() - t_start,
        )

    def _excluded_result(
        self, state: _RunState, t_start: float, detail: str
    ) -> PipelineResult:
        """Document exclu par le garde-fou de budget (contrainte C4) : erreur
        explicite, les huit étapes tracées « skipped », texte non anonymisé."""
        reason = f"BUDGET: {detail} — document exclu des métriques (contrainte C4)"
        state.errors.append(reason)
        state.interrupted = True
        traces: list[StageTrace] = []
        for order, stage in enumerate(STAGE_ORDER, start=1):
            sha = _sha256_text(state.current_text)
            traces.append(
                StageTrace(
                    stage=stage,
                    order=order,
                    entities_in=0,
                    entities_out=0,
                    duration_ms=0.0,
                    sha256_before=sha,
                    sha256_after=sha,
                    decisions=({"kind": "skipped", "reason": f"non exécuté — {reason}"},),
                    status="skipped",
                )
            )
        state.traces = traces
        return PipelineResult(
            doc_id=state.doc.doc_id,
            original_text=state.doc.text,
            anonymized_text=state.doc.text,
            annotations=(),
            decisions=(),
            risk=None,
            policy_id=self._policy_id,
            traces=tuple(traces),
            status="error",
            errors=tuple(state.errors),
            runtime_ms=_now_ms() - t_start,
        )

    # ------------------------------------------------------------------ #
    # Étape 1 — DETECT
    # ------------------------------------------------------------------ #
    def _stage_detect(self, state: _RunState) -> StageTrace:
        spec = self._profile.stages.detect.deterministic
        candidates = apply_patterns(state.doc.text, state.doc.language, self._patterns)
        candidates.extend(apply_rules(state.doc.text, state.doc.language, self._lexicons))
        # Privacy-first (SPEC-07 §2) : on filtre par seuil de confiance
        # déclaré, on ne pénalise jamais l'absence de contexte.
        kept = [c for c in candidates if c.confidence >= spec.min_confidence]
        kept.sort(key=lambda c: (c.start, c.end, c.qi_category, c.source))
        state.candidates = kept
        sha = _sha256_text(state.doc.text)
        return StageTrace(
            stage="DETECT",
            order=1,
            entities_in=0,
            entities_out=len(kept),
            duration_ms=0.0,
            sha256_before=sha,
            sha256_after=sha,
            added=tuple(entity_key(c.qi_category, c.start, c.end) for c in kept),
            status="ok",
        )

    # ------------------------------------------------------------------ #
    # Étape 2 — FUSE
    # ------------------------------------------------------------------ #
    def _stage_fuse(self, state: _RunState) -> StageTrace:
        strategy = self._profile.stages.fuse.strategy
        kept, fusion_decisions = fuse(state.candidates, strategy)
        state.annotations = candidates_to_annotations(kept, state.doc.doc_id, state.doc.text)
        decisions = tuple(
            {
                "kind": "fusion",
                "kept": entity_key(fd.kept.qi_category, fd.kept.start, fd.kept.end),
                "dropped": [
                    entity_key(d.qi_category, d.start, d.end) for d in fd.dropped
                ],
                "strategy": fd.strategy,
                "reason": fd.reason,
            }
            for fd in fusion_decisions
        )
        removed = tuple(
            entity_key(d.qi_category, d.start, d.end) for fd in fusion_decisions for d in fd.dropped
        )
        sha = _sha256_text(state.doc.text)
        return StageTrace(
            stage="FUSE",
            order=2,
            entities_in=len(state.candidates),
            entities_out=len(state.annotations),
            duration_ms=0.0,
            sha256_before=sha,
            sha256_after=sha,
            removed=removed,
            decisions=decisions,
            status="ok",
        )

    # ------------------------------------------------------------------ #
    # Étape 3 — ASSESS
    # ------------------------------------------------------------------ #
    def _stage_assess(self, state: _RunState) -> StageTrace:
        # Un état de QI par annotation quasi-identifiante (catégorie
        # primaire, niveau 0), comme le fait le moteur de politique dans
        # PLAN : mêmes états, même sémantique du risque.
        states: list[_EngineQiState] = []
        by_category: dict[str, list[_EngineQiState]] = {}
        for ann in state.annotations:
            if ann.identifier_type is not IdentifierType.QUASI:
                continue
            state_qi = _EngineQiState(
                annotation_id=ann.annotation_id,
                qi_category=ann.qi_categories[0],
                level=0,
            )
            states.append(state_qi)
            by_category.setdefault(state_qi.qi_category, []).append(state_qi)

        k_hat = self._estimator.estimate_k(states)
        risk = self._estimator(states)

        worst_category: str | None = None
        worst_risk: float | None = None
        for category in sorted(by_category):
            cat_risk = self._estimator(by_category[category])
            if worst_risk is None or cat_risk > worst_risk:
                worst_risk, worst_category = cat_risk, category

        state.risk = RiskAssessment(
            assessment_id=f"{state.doc.doc_id}:assess",
            population_id=self._profile.stages.assess.population_id,
            population_size=NaiveRiskEstimator.DEFAULT_POPULATION_SIZE,
            k_hat=k_hat,
            risk=risk,
            worst_category=worst_category,
            worst_risk=worst_risk,
            status="PROXY",
        )
        sha = _sha256_text(state.doc.text)
        return StageTrace(
            stage="ASSESS",
            order=3,
            entities_in=len(state.annotations),
            entities_out=len(state.annotations),
            duration_ms=0.0,
            sha256_before=sha,
            sha256_after=sha,
            decisions=(
                {
                    "kind": "assess",
                    "k_hat": k_hat,
                    "risk": risk,
                    "worst_category": worst_category,
                    "status": "PROXY",
                },
            ),
            status="ok",
        )

    # ------------------------------------------------------------------ #
    # Étape 4 — PLAN
    # ------------------------------------------------------------------ #
    def _stage_plan(self, state: _RunState) -> StageTrace:
        state.decisions = self._engine.plan(state.annotations, text=state.doc.text)
        decisions = tuple(
            {
                "kind": "plan",
                "start": d.start,
                "end": d.end,
                "qi_category": d.qi_category,
                "action": d.action.value,
                "reason": d.reason,
            }
            for d in state.decisions
        )
        sha = _sha256_text(state.doc.text)
        return StageTrace(
            stage="PLAN",
            order=4,
            entities_in=len(state.annotations),
            entities_out=len(state.decisions),
            duration_ms=0.0,
            sha256_before=sha,
            sha256_after=sha,
            decisions=decisions,
            status="ok",
        )

    # ------------------------------------------------------------------ #
    # Étape 5 — TRANSFORM
    # ------------------------------------------------------------------ #
    def _stage_transform(self, state: _RunState) -> StageTrace:
        # Le moteur de politique ne détient pas de secret HMAC : il pose un
        # jeton ``[CAT_A_PSEUDONYMISER]``. La substitution par le placeholder
        # réel doit précéder la construction de la liste appliquée, sinon le
        # texte anonymisé garde le jeton d'attente alors que les décisions
        # publiées annoncent le pseudonyme (incohérence + placeholder signalé
        # comme manquant par VALIDATE).
        mapper: PseudoMapper | None = None
        if any(d.action is Action.PSEUDONYMIZE for d in state.decisions):
            pspec = self._profile.stages.transform.pseudonymization
            secret = os.environ.get(pspec.secret_env, "")
            if not secret:
                raise PipelineCapabilityError(
                    f"TRANSFORM : la variable d'environnement {pspec.secret_env!r} est absente ou "
                    f"vide — la pseudonymisation exige un secret HMAC (aucun défaut silencieux, "
                    f"SPEC-10 §9). Définit {pspec.secret_env} avant d'exécuter."
                )
            mapper = PseudoMapper(
                secret.encode("utf-8"), scope=pspec.scope, length=pspec.length
            )

        final: list[AnonymizationDecision] = []
        for decision in state.decisions:
            if decision.action is Action.PSEUDONYMIZE and mapper is not None:
                final.append(
                    replace(
                        decision,
                        replacement=mapper.placeholder(decision.qi_category, decision.original),
                        meta={
                            **decision.meta,
                            "pseudo_scope": self._profile.stages.transform.pseudonymization.scope,
                        },
                    )
                )
            else:
                final.append(decision)
        state.decisions = final

        # Seules les décisions NON-KEEP sont appliquées : ``apply_decisions``
        # refuse tout chevauchement, y compris avec des KEEP (or KEEP et
        # SUPPRESS peuvent légitimement porter sur le même span, I-ANN-5).
        # La liste complète reste dans ``state.decisions`` (explicabilité).
        non_keep = [d for d in final if d.action is not Action.KEEP]
        merged = _merge_overlapping(non_keep, state.doc.text)
        state.applied_decisions = merged

        result = apply_decisions(state.doc.text, merged)
        state.current_text = result.anonymized_text

        transform_decisions = tuple(
            {
                "kind": "transform",
                "start": d.start,
                "end": d.end,
                "qi_category": d.qi_category,
                "action": d.action.value,
                "replacement": d.replacement,
                "reason": d.reason,
            }
            for d in merged
        )
        return StageTrace(
            stage="TRANSFORM",
            order=5,
            entities_in=len(state.decisions),
            entities_out=0,
            duration_ms=0.0,
            sha256_before=_sha256_text(state.doc.text),
            sha256_after=_sha256_text(state.current_text),
            added=tuple(entity_key(d.qi_category, d.start, d.end) for d in merged),
            decisions=transform_decisions,
            status="ok",
        )

    # ------------------------------------------------------------------ #
    # Étape 6 — VALIDATE
    # ------------------------------------------------------------------ #
    def _stage_validate(self, state: _RunState) -> StageTrace:
        checks = self._profile.stages.validation
        outcome = validate_anonymization(
            anonymized_text=state.current_text,
            decisions=state.applied_decisions,
            gold_annotations=state.gold,
            patterns=self._patterns,
            lexicons=self._lexicons,
            language=state.doc.language,
            checks=checks,
        )
        if outcome.ok:
            return StageTrace(
                stage="VALIDATE",
                order=6,
                entities_in=len(state.decisions),
                entities_out=len(state.decisions),
                duration_ms=0.0,
                sha256_before=_sha256_text(state.current_text),
                sha256_after=_sha256_text(state.current_text),
                status="ok",
            )

        # Seuls les constats non nuls sont cités : ``metrics/accounting`` classe
        # l'erreur par mots-clés (« fuite », « placeholder », « motif »), donc un
        # résumé qui énumère les trois compteurs — même à zéro — imputerait
        # toute panne VALIDATE à une fuite (C-5, ventilation errors_by_type).
        findings = [
            (len(outcome.leaked_direct), "fuite(s) gold"),
            (len(outcome.residual_patterns), "motif(s) DIRECT résiduel(s)"),
            (len(outcome.malformed_placeholders), "placeholder(s) malformé(s)"),
        ]
        summary = ", ".join(f"{count} {label}" for count, label in findings if count)
        state.errors.append(f"VALIDATE : {summary}")

        fatal = checks.fail_on_leak and bool(outcome.leaked_direct)
        if fatal:
            # Le document seul est interrompu (le run continue sur les
            # documents suivants) : fail_on_leak est un interrupteur de
            # document, pas du run.
            state.interrupted = True
            return StageTrace(
                stage="VALIDATE",
                order=6,
                entities_in=len(state.decisions),
                entities_out=len(state.decisions),
                duration_ms=0.0,
                sha256_before=_sha256_text(state.current_text),
                sha256_after=_sha256_text(state.current_text),
                decisions=({"kind": "leak", "count": len(outcome.leaked_direct)},),
                status="error",
                error=f"VALIDATE : {summary} — document interrompu (fail_on_leak)",
            )

        # Non fatal : le document est marqué « partial », le run continue.
        state.has_nonfatal_findings = True
        return StageTrace(
            stage="VALIDATE",
            order=6,
            entities_in=len(state.decisions),
            entities_out=len(state.decisions),
            duration_ms=0.0,
            sha256_before=_sha256_text(state.current_text),
            sha256_after=_sha256_text(state.current_text),
            decisions=(
                {
                    "kind": "findings",
                    "leaked_direct": len(outcome.leaked_direct),
                    "residual_patterns": len(outcome.residual_patterns),
                    "malformed_placeholders": len(outcome.malformed_placeholders),
                },
            ),
            status="ok",
        )

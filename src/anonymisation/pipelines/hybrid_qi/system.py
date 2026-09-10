"""Système ``hybrid-qi-v1`` : pipeline 8 étapes avec risque calibré copule.

Architecture complète (SPEC-10 §3, plan ``hybrid-qi``) :

- **Noyau déterministe, hors ligne (C1)** — détecteur natif (motifs +
  règles) → fusion → ensemble de Q(d) (QICR) → risque copule calibré sur
  la population synthétique versionnée ``hybrid-diagnostic-v1`` → planning
  local P0–P4 (boucle ratio Δrisque/coût) → transformation → validation
  hors-ligne. Aucune étape du noyau n'ouvre de socket, ne charge de
  modèle ni ne requiert de GPU.
- **Options LLM (C2), désactivées par défaut** — extraction QI stricte
  (JSON uniquement, offsets vérifiés), audit par attaquant A, réécriture
  bornée. Chaque option est un paramètre explicite du système ; le profil
  ne les active jamais (règle d'or : aucune valeur par défaut silencieuse).

Pourquoi un ``_execute`` propre et non l'orchestrateur partagé : celui-ci
refuse par construction tout estimateur autre que ``naive`` et toute étape
NER/AUDIT/REWRITE, alors que l'identité de ce système est précisément
l'estimateur copule calibré + les étapes LLM optionnelles. Le profil
déclare ``stages.assess.estimator: hybrid_copula`` ; l'orchestrateur ne
peut donc pas l'instancier. Les briques partagées (``fuse``,
``apply_decisions``, ``validate_anonymization``, fusion des chevauchements)
sont réutilisées telles quelles — aucune logique n'est dupliquée.

Garanties portées ici (et nulle part ailleurs) :

- les réponses LLM vides/malformées sont des **erreurs nommées** du
  document (C3), jamais « aucune entité trouvée » ;
- une fuite haute confiance persistant après la dernière passe de
  réécriture est une **erreur**, jamais un score partiel (C4) ;
- les traces AUDIT/REWRITE ne conservent que des **agrégats** (compteurs,
  catégories, confiances) : aucune valeur inférée sur corpus réel.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from anonymisation.capabilities import (
    CAP_DECISIONS,
    CAP_POLICY,
    CAP_RISK,
    CAP_SPANS,
    CAP_TRACES,
)
from anonymisation.detect.base import Candidate, candidates_to_annotations
from anonymisation.detect.fusion import fuse
from anonymisation.detect.patterns import load_patterns
from anonymisation.llm.client import LlmClient
from anonymisation.llm.config import load_backends_config
from anonymisation.pipeline.orchestrator import _merge_overlapping, _sha256_text
from anonymisation.pipeline.profiles import (
    LoadedProfile,
    RuntimeProfile,
    _repo_root,
    load_runtime_profile,
)
from anonymisation.pipeline.traces import (
    PipelineResult,
    RiskAssessment,
    StageTrace,
    entity_key,
)
from anonymisation.pipeline.validate_stage import validate_anonymization
from anonymisation.policy.models import Policy, load_policy_set
from anonymisation.schema.models import Annotation, Document
from anonymisation.systems.base import ModelRef, SystemBase, SystemConfig
from anonymisation.systems.registry import register_system
from anonymisation.transform.apply import apply_decisions
from anonymisation.transform.decisions import Action, AnonymizationDecision

from anonymisation.pipelines.hybrid_qi.attack import (
    AttackerA,
    AttackerAReport,
    Rewriter,
    RewriteResponseError,
)
from anonymisation.pipelines.hybrid_qi.detectors import (
    GLINER_MODEL,
    GlinerDetector,
    run_detection,
)
from anonymisation.pipelines.hybrid_qi.prompts import (
    OFFERED_QI_CODES,
    QiExtraction,
    UniquenessClaim,
    build_qi_extraction_prompt,
    parse_qi_extraction,
    prompt_sha256,
)
from anonymisation.pipelines.hybrid_qi.policy import plan_hybrid_policy
from anonymisation.pipelines.hybrid_qi.risk import (
    HybridRiskEstimate,
    HybridRiskEstimator,
    PopulationConfig,
    build_qi_attributes,
    load_population,
)

#: Dossier du paquet : les ressources livrées (``policy.yaml``,
#: ``population.yaml``, ``profile.yaml``) sont résolues relativement à lui,
#: jamais au répertoire courant.
_PACKAGE_DIR = Path(__file__).resolve().parent


class HybridConfigError(RuntimeError):
    """Configuration incohérente du système ``hybrid-qi`` : paramètre, profil
    ou ressource manquante. Le message nomme le champ fautif et le correctif
    attendu — jamais un défaut deviné."""


class AttackLeakPersistsError(RuntimeError):
    """Une fuite haute confiance subsiste après la dernière passe de
    réécriture : le document est en erreur (C4), jamais un score partiel."""


@dataclass(frozen=True)
class HybridRiskAssessment(RiskAssessment):
    """Risque copule calibré pour le suivi d'audit.

    Étend ``RiskAssessment`` (base du harnais, statut PROXY) des champs de
    l'estimateur hybride : intervalle calibré, risque point, modèle de
    risque, QI contributifs, claim d'unicité portée par le texte, portée de
    la calibration et explication lisible. ``status`` est toujours
    ``DIAGNOSTIC`` (SPEC-07 §9 : jamais publié comme chiffre OFFICIAL).
    """

    k_interval: tuple[float, float] = (0.0, 0.0)
    risk_point: float = 0.0
    risk_model: str = "copula"
    contributing_qi: tuple[str, ...] = ()
    uniqueness_claim: UniquenessClaim | None = None
    calibration_scope: str = "synthetic"
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = dict(super().to_dict())
        payload.update(
            {
                "k_interval": list(self.k_interval),
                "risk_point": self.risk_point,
                "risk_model": self.risk_model,
                "contributing_qi": list(self.contributing_qi),
                "uniqueness_claim": (
                    self.uniqueness_claim.model_dump(mode="json")
                    if self.uniqueness_claim is not None
                    else None
                ),
                "calibration_scope": self.calibration_scope,
                "explanation": self.explanation,
            }
        )
        return payload


class _HybridQiParams(BaseModel):
    """Paramètres du système ``hybrid-qi-v1`` (plan ``hybrid-qi`` L13).

    Toutes les options LLM/NER sont **désactivées par défaut** (C2) : le
    noyau complet tourne hors ligne. ``attack_enabled`` exige
    ``llm_enabled`` ; ``rewrite_enabled`` exige ``attack_enabled`` —
    une option plus agressive ne peut pas s'activer seule.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Clé de backend d'extraction dans ``configs/llm/backends.yaml``.
    backend: str = "qwen_local"
    llm_enabled: bool = False
    ner_enabled: bool = False
    attack_enabled: bool = False
    rewrite_enabled: bool = False
    #: Garde-fou anti-divergence de l'extraction LLM.
    max_entities: int = Field(default=64, ge=1, le=128)
    #: Seuil de confiance des candidats du détecteur **natif** (GLiNER a ses
    #: propres seuils, cf. ``ner_threshold`` / ``person_threshold``).
    qi_min_confidence: float = Field(default=0.30, ge=0.30, le=1.0)
    ner_threshold: float = Field(default=0.35, gt=0.0, le=1.0)
    person_threshold: float = Field(default=0.55, gt=0.0, le=1.0)
    max_rewrite_rounds: int = Field(default=2, ge=1, le=2)
    #: Doit correspondre au ``population_id`` de ``population.yaml``.
    population_id: str = "hybrid-diagnostic-v1"
    temperature: float = 0.0

    @model_validator(mode="after")
    def _check_option_ladder(self) -> _HybridQiParams:
        if self.attack_enabled and not self.llm_enabled:
            raise ValueError(
                "attack_enabled=true exige llm_enabled=true (l'audit est un "
                "appel LLM) — active les deux ou aucun."
            )
        if self.rewrite_enabled and not self.attack_enabled:
            raise ValueError(
                "rewrite_enabled=true exige attack_enabled=true (la "
                "réécriture n'est pilotée que par l'audit) — active les "
                "deux ou aucun."
            )
        return self


@register_system
class HybridQiSystem(SystemBase):
    """Pipeline hybride : détecteur natif + GLiNER/LLM optionnels + risque
    copule calibré + planning P0–P4 + audit/réécriture bornés."""

    system_id: ClassVar[str] = "hybrid-qi-v1"
    system_version: ClassVar[str] = "1"
    aliases: ClassVar[tuple[str, ...]] = ("hybrid-qi", "hybrid")
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {CAP_SPANS, CAP_DECISIONS, CAP_TRACES, CAP_RISK, CAP_POLICY}
    )
    uses_policy: ClassVar[bool] = True
    offline_only: ClassVar[bool] = False
    summary: ClassVar[str] = (
        "Pipeline hybride 8 étapes : détection native + GLiNER et extraction "
        "LLM optionnels, risque copule calibré (population synthétique "
        "hybrid-diagnostic-v1), planning P0–P4, audit par attaquant A et "
        "réécriture bornée."
    )
    Params: ClassVar[type[BaseModel] | None] = _HybridQiParams

    @classmethod
    def contract_config(cls) -> SystemConfig:
        # Contrat transverse : tout système enregistré doit construire et
        # tourner hors ligne (aucun socket, GPU, modèle ni clé). Toutes les
        # options LLM/NER désactivées → noyau déterministe pur.
        return SystemConfig(
            params={
                "backend": "qwen_local",
                "llm_enabled": False,
                "ner_enabled": False,
                "attack_enabled": False,
                "rewrite_enabled": False,
            },
            policy_id="P2",
        )

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    def __init__(self, config: SystemConfig | None = None) -> None:
        super().__init__(config)
        self._p = _HybridQiParams.model_validate(self._params)

        # --- Profil (résolu chez le paquet, puis configs/runtime) -------- #
        loaded = self._resolve_profile()
        self._profile = loaded.profile
        self._profile_path: Path | None = loaded.config_path

        # Garde réseau (C1/SPEC-10 §8) : ce système ne supporte que des
        # backends locaux ; un profil autorisant le distant est une erreur.
        if self._profile.llm.allow_remote:
            raise HybridConfigError(
                "profil "
                f"{self._profile.profile!r} : llm.allow_remote=true n'est pas "
                "supporté par hybrid-qi (backends locaux uniquement) — "
                "mettez llm.allow_remote: false."
            )
        if self._p.llm_enabled and self._profile.llm.mode != "local":
            raise HybridConfigError(
                f"llm_enabled=true mais le profil déclare llm.mode="
                f"{self._profile.llm.mode!r} (attendu 'local')."
            )
        # Contradictions profil/paramètres : le profil décrit l'intention,
        # les paramètres l'exécution — les deux doivent s'accorder.
        if self._profile.stages.audit.enabled and not self._p.attack_enabled:
            raise HybridConfigError(
                "profil : stages.audit.enabled=true mais attack_enabled=false — "
                "activez --param attack_enabled=true ou mettez "
                "stages.audit.enabled: false dans le profil."
            )
        if self._profile.stages.rewrite.enabled and not self._p.rewrite_enabled:
            raise HybridConfigError(
                "profil : stages.rewrite.enabled=true mais rewrite_enabled=false "
                "— activez --param rewrite_enabled=true ou mettez "
                "stages.rewrite.enabled: false dans le profil."
            )
        if (
            self._profile.stages.detect.ner.enabled
            and not self._p.ner_enabled
        ):
            raise HybridConfigError(
                "profil : stages.detect.ner.enabled=true mais ner_enabled=false "
                "— activez --param ner_enabled=true (exige l'extra 'models') "
                "ou mettez stages.detect.ner.enabled: false dans le profil."
            )
        for stage_name in (
            "detect",
            "fuse",
            "assess",
            "plan",
            "transform",
            "validation",
        ):
            spec = getattr(self._profile.stages, stage_name)
            if not spec.enabled:
                raise HybridConfigError(
                    f"profil : l'étape cœur {stage_name} est désactivée — "
                    "hybrid-qi n'a pas de repli (règle d'or) ; remettez "
                    f"stages.{stage_name}.enabled: true."
                )

        # --- Références du profil (d'abord le dossier du profil) -------- #
        def _resolve_reference(ref: str) -> Path:
            tried: list[Path] = []
            if self._profile_path is not None:
                tried.append(self._profile_path.parent / ref)
            root = _repo_root(
                self._profile_path.parent
                if self._profile_path is not None
                else (self.config.repo_root or Path.cwd())
            )
            if root is not None:
                candidate = root / ref
                if candidate not in tried:
                    tried.append(candidate)
            for path in tried:
                if path.is_file():
                    return path
            raise HybridConfigError(
                f"profil {self._profile.profile!r} : impossible de résoudre "
                f"la référence {ref!r} (cherché : {', '.join(str(p) for p in tried)})."
            )

        patterns_path = _resolve_reference(
            self._profile.stages.detect.deterministic.patterns
        )
        policy_path = _resolve_reference(self._profile.stages.plan.policy_set)

        # --- Politique (P0–P4) ------------------------------------------- #
        policy_set = load_policy_set(policy_path)
        policy_id = self.config.policy_id or self._profile.stages.plan.policy
        self._policy = policy_set.get(policy_id)

        # --- Population + estimateur copule ------------------------------ #
        self._population = load_population(_PACKAGE_DIR / "population.yaml")
        expected = self._population.population_id
        if self._p.population_id != expected:
            raise HybridConfigError(
                f"population_id={self._p.population_id!r} ne correspond pas à "
                f"population.yaml ({expected!r}) — corrigez le paramètre ou le "
                "fichier, jamais de repli silencieux."
            )
        if (
            self._profile.stages.assess.population_id is not None
            and self._profile.stages.assess.population_id != expected
        ):
            raise HybridConfigError(
                f"profil : stages.assess.population_id="
                f"{self._profile.stages.assess.population_id!r} ne correspond "
                f"pas à population.yaml ({expected!r})."
            )
        self._estimator = HybridRiskEstimator(self._population)

        # --- Détecteur natif (les patterns servent DETECT et VALIDATE) --- #
        self._detector = DeterministicDetectorLazy(
            config_path=patterns_path,
            strategy=self._profile.stages.fuse.strategy,
        )

        # --- Options LLM/NER : construites uniquement si demandées ------- #
        self._gliner: GlinerDetector | None = None
        self._extraction_client: LlmClient | None = None
        self._attacker: AttackerA | None = None
        self._rewriter: Rewriter | None = None
        if self._p.ner_enabled:
            # Échec (module/poids absents) = GlinerConfigError nommée, jamais
            # de repli natif silencieux.
            self._gliner = GlinerDetector(
                threshold=self._p.ner_threshold,
                person_threshold=self._p.person_threshold,
            )
        if self._p.llm_enabled:
            backends_config = load_backends_config(self._backends_config_path())
            self._extraction_client = LlmClient.for_backend(
                self._p.backend, config=backends_config
            )
            if self._p.attack_enabled:
                self._attacker = AttackerA(
                    LlmClient.for_role("attacker_a", config=backends_config)
                )
                if self._p.rewrite_enabled:
                    self._rewriter = Rewriter(
                        LlmClient.for_role("paraphrase", config=backends_config),
                        detector=self._detector,
                        qi_min_confidence=self._p.qi_min_confidence,
                    )

    def _resolve_profile(self) -> LoadedProfile:
        raw = self.config.profile
        if isinstance(raw, LoadedProfile):
            return raw
        if isinstance(raw, RuntimeProfile):
            return LoadedProfile(profile=raw, config_path=_PACKAGE_DIR / "profile.yaml")
        name = str(raw) if raw is not None else "hybrid_qi"
        return load_runtime_profile(name)

    def _backends_config_path(self) -> Path | None:
        if self.config.repo_root is not None:
            candidate = self.config.repo_root / "configs" / "llm" / "backends.yaml"
            if candidate.is_file():
                return candidate
        return None

    # ------------------------------------------------------------------ #
    # Déclarations (lock de reproductibilité)
    # ------------------------------------------------------------------ #
    def models(self) -> tuple[ModelRef, ...]:
        refs: list[ModelRef] = []
        if self._gliner is not None:
            refs.append(ModelRef(name=GLINER_MODEL, revision="local"))
        for client in (
            self._extraction_client,
            getattr(self._attacker, "_client", None) if self._attacker else None,
            getattr(self._rewriter, "_client", None) if self._rewriter else None,
        ):
            if client is not None:
                backend = client.backend
                refs.append(ModelRef(name=str(backend.model), revision=backend.name))
        return tuple(refs)

    def prompts(self) -> tuple[str, ...]:
        return (
            "anonymisation.pipelines.hybrid_qi.prompts:build_qi_extraction_prompt",
            "anonymisation.pipelines.hybrid_qi.attack:build_attack_prompt",
            "anonymisation.pipelines.hybrid_qi.attack:build_rewrite_prompt",
        )

    # ------------------------------------------------------------------ #
    # Exécution
    # ------------------------------------------------------------------ #
    def _execute(
        self,
        doc: Document,
        gold: tuple[Annotation, ...],
    ) -> PipelineResult:
        # ``gold`` n'est jamais lu : ce système n'est pas gold-aware
        # (CAP_GOLD_AWARE absent) ; VALIDATE re-détecte au lieu de comparer
        # à un or.
        del gold
        started = time.perf_counter()
        profile = self._profile
        params = self._p

        traces: list[StageTrace] = []
        errors: list[str] = []
        status = "ok"
        sha = _sha256_text(doc.text)

        # ---------------------------------------------------------------- #
        # 1. DETECT — natif (+ GLiNER optionnel) + extraction LLM optionnelle
        # ---------------------------------------------------------------- #
        candidates = run_detection(
            doc=doc,
            detector=self._detector,
            qi_min_confidence=params.qi_min_confidence,
            gliner=self._gliner,
        )
        candidates.sort(key=lambda c: (c.start, c.end, c.qi_category, c.source))

        extraction: QiExtraction | None = None
        detect_decisions: tuple[dict[str, Any], ...] = ()
        if params.llm_enabled:
            assert self._extraction_client is not None
            prompt = build_qi_extraction_prompt(
                text=doc.text,
                language=doc.language,
                domain=doc.domain.value,
                qi_codes=OFFERED_QI_CODES,
            )
            # Réponse vide/malformée : LlmEmptyResponseError /
            # ExtractionResponseError → document en erreur (C3), jamais
            # interprétés comme « aucune entité ».
            completion = self._extraction_client.complete(
                prompt, temperature=params.temperature
            )
            extraction = parse_qi_extraction(
                completion.content,
                text=doc.text,
                max_entities=params.max_entities,
                prompt_sha256=prompt_sha256(prompt),
            )
            detect_decisions = (
                {
                    "kind": "extraction",
                    "n_qis": len(extraction.qis),
                    "n_claims": len(extraction.uniqueness_claims),
                    "backend": completion.backend,
                },
            )
        else:
            detect_decisions = ({"kind": "extraction", "llm_enabled": False},)

        traces.append(
            StageTrace(
                stage="DETECT",
                order=1,
                entities_in=0,
                entities_out=len(candidates),
                duration_ms=0.0,
                sha256_before=sha,
                sha256_after=sha,
                added=tuple(
                    entity_key(c.qi_category, c.start, c.end) for c in candidates
                ),
                decisions=detect_decisions,
                status="ok",
            )
        )

        # ---------------------------------------------------------------- #
        # 2. FUSE — fusion des chevauchements (stratégie du profil)
        # ---------------------------------------------------------------- #
        fused, fusion_decisions = fuse(
            candidates, strategy=profile.stages.fuse.strategy
        )
        annotations = candidates_to_annotations(fused, doc.doc_id, doc.text)
        traces.append(
            StageTrace(
                stage="FUSE",
                order=2,
                entities_in=len(candidates),
                entities_out=len(fused),
                duration_ms=0.0,
                sha256_before=sha,
                sha256_after=sha,
                removed=tuple(
                    entity_key(d.qi_category, d.start, d.end)
                    for fd in fusion_decisions
                    for d in fd.dropped
                ),
                decisions=tuple(
                    {
                        "kind": "fusion",
                        "kept": entity_key(
                            fd.kept.qi_category, fd.kept.start, fd.kept.end
                        ),
                        "dropped": [
                            entity_key(d.qi_category, d.start, d.end)
                            for d in fd.dropped
                        ],
                        "strategy": fd.strategy,
                        "reason": fd.reason,
                    }
                    for fd in fusion_decisions
                ),
                status="ok",
            )
        )

        # ---------------------------------------------------------------- #
        # 3. ASSESS — Q(d) (QICR) + risque copule calibré (DIAGNOSTIC)
        # ---------------------------------------------------------------- #
        attributes = build_qi_attributes(annotations=annotations, extraction=extraction)
        claims = tuple(extraction.uniqueness_claims) if extraction else ()
        estimate = self._estimator.assess(
            attributes,
            domain=doc.domain.value,
            language=doc.language,
            claims=claims,
            levels=None,
        )
        risk = HybridRiskAssessment(
            assessment_id=f"{doc.doc_id}:assess",
            population_id=estimate.population_id,
            population_size=self._population.size,
            k_hat=estimate.k_hat,
            risk=estimate.risk,
            # « Pire » catégorie = première des QI contributifs (le risque
            # copule est un produit : il n'y a pas de risque par catégorie) ;
            # worst_risk est le risque global, seule valeur de décision.
            worst_category=(
                estimate.contributing_qi[0] if estimate.contributing_qi else None
            ),
            worst_risk=estimate.risk,
            status=estimate.status,
            k_interval=estimate.k_interval,
            risk_point=estimate.risk_point,
            risk_model=estimate.risk_model,
            contributing_qi=estimate.contributing_qi,
            uniqueness_claim=estimate.uniqueness_claim,
            calibration_scope=estimate.calibration_scope,
            explanation=estimate.explanation,
        )
        traces.append(
            StageTrace(
                stage="ASSESS",
                order=3,
                entities_in=len(annotations),
                entities_out=len(attributes),
                duration_ms=0.0,
                sha256_before=sha,
                sha256_after=sha,
                decisions=(
                    {
                        "kind": "assess",
                        "risk_model": estimate.risk_model,
                        "population_id": estimate.population_id,
                        "k_hat": estimate.k_hat,
                        "k_interval": list(estimate.k_interval),
                        "risk": estimate.risk,
                        "risk_point": estimate.risk_point,
                        "n_attributes": len(attributes),
                        "combination_truncated": estimate.combination_truncated,
                        "status": estimate.status,
                    },
                ),
                status="ok",
            )
        )

        # ---------------------------------------------------------------- #
        # 4. PLAN — boucle ratio Δrisque/coût selon la politique P0–P4
        # ---------------------------------------------------------------- #
        decisions, plan_meta = plan_hybrid_policy(
            doc=doc,
            annotations=annotations,
            attributes=attributes,
            claims=claims,
            estimator=self._estimator,
            policy=self._policy,
            risk_base=estimate,
        )
        traces.append(
            StageTrace(
                stage="PLAN",
                order=4,
                entities_in=len(annotations),
                entities_out=len(decisions),
                duration_ms=0.0,
                sha256_before=sha,
                sha256_after=sha,
                decisions=tuple(
                    {
                        "kind": "plan",
                        "start": d.start,
                        "end": d.end,
                        "qi_category": d.qi_category,
                        "action": d.action.value,
                        "reason": d.reason,
                    }
                    for d in decisions
                ),
                status="ok",
            )
        )
        del plan_meta

        # ---------------------------------------------------------------- #
        # 5. TRANSFORM — KEEP filtré (conservé en audit), application droite
        #    à gauche, chevauchements fusionnés avant application.
        # ---------------------------------------------------------------- #
        actionable = [d for d in decisions if d.action is not Action.KEEP]
        merged = _merge_overlapping(actionable, doc.text)
        transform_result = apply_decisions(doc.text, merged)
        sha_transform = _sha256_text(transform_result.anonymized_text)
        traces.append(
            StageTrace(
                stage="TRANSFORM",
                order=5,
                entities_in=len(decisions),
                entities_out=len(merged),
                duration_ms=0.0,
                sha256_before=sha,
                sha256_after=sha_transform,
                modified=tuple(
                    entity_key(d.qi_category, d.start, d.end) for d in merged
                ),
                status="ok",
            )
        )

        # ---------------------------------------------------------------- #
        # 6. VALIDATE — contrôles hors-ligne sur le texte transformé
        # ---------------------------------------------------------------- #
        current_text = transform_result.anonymized_text
        validation = validate_anonymization(
            anonymized_text=current_text,
            decisions=decisions,
            gold_annotations=(),
            patterns=self._detector.patterns,
            lexicons=self._detector.lexicons,
            language=doc.language,
            checks=profile.stages.validation,
        )
        if validation.ok:
            validate_status = "ok"
        else:
            summary = validation.summary()
            validate_status = "partial"
            errors.append(f"VALIDATE : {summary}")
            if (
                profile.stages.validation.fail_on_leak
                and validation.leaked_direct
            ):
                validate_status = "error"
                errors.append("VALIDATE : fuite interrompue (fail_on_leak=true)")
        traces.append(
            StageTrace(
                stage="VALIDATE",
                order=6,
                entities_in=len(decisions),
                entities_out=len(decisions),
                duration_ms=0.0,
                sha256_before=sha_transform,
                sha256_after=sha_transform,
                status=validate_status,
                error=None
                if validate_status == "ok"
                else f"VALIDATE : {validation.summary()}",
            )
        )

        # ---------------------------------------------------------------- #
        # 7. AUDIT — attaquant A sur le texte anonymisé (agrégats seuls)
        # ---------------------------------------------------------------- #
        qd_values = self._qd_values(attributes, doc.text)
        audit_report: AttackerAReport | None = None
        if not params.attack_enabled:
            traces.append(
                _skipped_trace(
                    stage="AUDIT",
                    order=7,
                    sha=sha_transform,
                    reason="attack_enabled=false — l'audit LLM est désactivé",
                )
            )
        else:
            assert self._attacker is not None
            audit_report = self._attacker.attack(
                text=current_text,
                language=doc.language,
                domain=doc.domain.value,
                qi_codes=OFFERED_QI_CODES,
                qd_values=qd_values,
            )
            audit_error: str | None = None
            if audit_report.has_leak:
                detail = self._leak_detail(audit_report)
                audit_error = f"AUDIT : {detail}"
                if not params.rewrite_enabled:
                    errors.append(audit_error)
                    status = "partial"
            traces.append(
                StageTrace(
                    stage="AUDIT",
                    order=7,
                    entities_in=1,
                    entities_out=len(audit_report.leaked_categories),
                    duration_ms=0.0,
                    sha256_before=sha_transform,
                    sha256_after=sha_transform,
                    decisions=({"kind": "audit", **audit_report.to_dict()},),
                    status="ok",
                    error=audit_error,
                )
            )

        # ---------------------------------------------------------------- #
        # 8. REWRITE — réécriture bornée si l'audit a détecté une fuite
        # ---------------------------------------------------------------- #
        rewrite_decisions: list[dict[str, Any]] = []
        rewrite_error: str | None = None
        if not params.rewrite_enabled:
            traces.append(
                _skipped_trace(
                    stage="REWRITE",
                    order=8,
                    sha=sha_transform,
                    reason="rewrite_enabled=false — la réécriture LLM est désactivée",
                )
            )
        elif audit_report is None or not audit_report.has_leak:
            traces.append(
                _skipped_trace(
                    stage="REWRITE",
                    order=8,
                    sha=sha_transform,
                    reason="aucune fuite détectée à l'audit",
                )
            )
        else:
            assert self._rewriter is not None
            target_categories = audit_report.leaked_categories or tuple(
                sorted(qd_values)
            )
            constraints = (
                "Conserve la langue du texte d'origine.",
                "Conserve tous les placeholders d'anonymisation existants ([...]).",
                "Ne réintroduis aucun identifiant direct (nom, adresse, e-mail, "
                "téléphone).",
                "Préserve la longueur approximative du texte (±30 %).",
            )
            report = audit_report
            for round_index in range(1, params.max_rewrite_rounds + 1):
                try:
                    rewrite_result = self._rewriter.rewrite(
                        text=current_text,
                        language=doc.language,
                        domain=doc.domain.value,
                        target_categories=target_categories,
                        business_constraints=constraints,
                    )
                except RewriteResponseError as exc:
                    # Non-progression du modèle : la boucle ne peut pas
                    # progresser davantage ; la fuite persiste (erreur).
                    rewrite_error = f"REWRITE : {exc}"
                    break
                current_text = rewrite_result.text
                sha_transform = _sha256_text(current_text)
                rewrite_decisions.append(
                    {
                        "kind": "rewrite",
                        "round": round_index,
                        "changed_categories": list(rewrite_result.changed_categories),
                        "model": rewrite_result.model,
                        "cached": rewrite_result.cached,
                        "prompt_sha256": rewrite_result.prompt_sha256,
                    }
                )
                # La réécriture a changé le texte : VALIDATE et AUDIT sont
                # rejoués sur le nouveau texte (l'audit fait autorité pour
                # la suite de la boucle).
                validation = validate_anonymization(
                    anonymized_text=current_text,
                    decisions=decisions,
                    gold_annotations=(),
                    patterns=self._detector.patterns,
                    lexicons=self._detector.lexicons,
                    language=doc.language,
                    checks=profile.stages.validation,
                )
                if not validation.ok and validate_status == "ok":
                    validate_status = "partial"
                    errors.append(f"VALIDATE : {validation.summary()}")
                report = self._attacker.attack(
                    text=current_text,
                    language=doc.language,
                    domain=doc.domain.value,
                    qi_codes=OFFERED_QI_CODES,
                    qd_values=qd_values,
                )
                if not report.has_leak:
                    break
            else:
                # Boucle épuisée sans rupture de fuite : erreur nommée (C4),
                # jamais un score partiel.
                if report.has_leak:
                    raise AttackLeakPersistsError(
                        "fuite haute confiance persistante après "
                        f"{params.max_rewrite_rounds} passe(s) de réécriture "
                        f"({self._leak_detail(report)}) — le document est en "
                        "erreur, jamais compté comme anonymisé."
                    )
            if report.has_leak:
                # Non-progression du réécriture : la fuite subsiste → erreur.
                raise AttackLeakPersistsError(
                    "fuite haute confiance persistante après "
                    f"{len(rewrite_decisions)} passe(s) de réécriture "
                    f"({self._leak_detail(report)}) — le document est en "
                    "erreur, jamais compté comme anonymisé."
                )
            traces.append(
                StageTrace(
                    stage="REWRITE",
                    order=8,
                    entities_in=1,
                    entities_out=1,
                    duration_ms=0.0,
                    sha256_before=sha_transform,
                    sha256_after=sha_transform,
                    decisions=tuple(rewrite_decisions),
                    status="ok",
                    error=rewrite_error,
                )
            )

        # ---------------------------------------------------------------- #
        # Résultat
        # ---------------------------------------------------------------- #
        if status == "ok" and validate_status == "partial":
            status = "partial"
        if validate_status == "error":
            status = "error"

        return PipelineResult(
            doc_id=doc.doc_id,
            original_text=doc.text,
            anonymized_text=current_text,
            annotations=tuple(annotations),
            decisions=tuple(decisions),
            risk=risk,
            policy_id=self._policy.label,
            traces=tuple(traces),
            status=status,
            errors=tuple(errors),
            runtime_ms=(time.perf_counter() - started) * 1000.0,
            identity=None,
        )

    # ------------------------------------------------------------------ #
    # Aides
    # ------------------------------------------------------------------ #
    @staticmethod
    def _qd_values(
        attributes: tuple[Any, ...] | list[Any], text: str
    ) -> dict[str, frozenset[str]]:
        """Valeurs de Q(d) normalisées, par catégorie : l'entrée du raffinement
        « fuite au niveau valeur » de l'audit.

        Pour un attribut ancré, la valeur est la surface originale
        ``text[start:end]`` (invariant des offsets) ; pour un attribut
        implicite, la valeur ``raw`` si c'est une chaîne lisible. Les valeurs
        non récupérables en chaîne ne participent qu'au contrôle par
        catégorie — jamais devinées.
        """
        values: dict[str, set[str]] = {}
        for attribute in attributes:
            string: str | None = None
            if attribute.start is not None and attribute.end is not None:
                string = text[attribute.start : attribute.end]
            elif isinstance(attribute.value, str):
                string = attribute.value
            elif isinstance(attribute.value, dict):
                raw = attribute.value.get("raw")
                if isinstance(raw, str):
                    string = raw
            if string is None:
                continue
            normalized = " ".join(string.split()).casefold()
            if normalized:
                values.setdefault(attribute.category, set()).add(normalized)
        return {cat: frozenset(vals) for cat, vals in values.items()}

    @staticmethod
    def _leak_detail(report: AttackerAReport) -> str:
        """Résumé actionnable d'une fuite (agrégats seuls, jamais de valeur)."""
        parts: list[str] = []
        if report.leaked_categories:
            parts.append(
                f"{len(report.leaked_categories)} catégorie(s) de QI de Q(d) "
                f"ré-identifiable(s) (confiance ≥ seuil) : "
                f"{', '.join(report.leaked_categories)}"
            )
        if report.value_level_leaks:
            parts.append(
                "valeur exacte rétablie pour : "
                f"{', '.join(report.value_level_leaks)}"
            )
        if report.direct_leak_count:
            parts.append(
                f"{report.direct_leak_count} identifiant(s) direct(s) rétabli(s)"
            )
        if not parts:
            return "fuite détectée (détails dans la trace AUDIT)"
        return "; ".join(parts)


# --------------------------------------------------------------------------- #
# Briques locales
# --------------------------------------------------------------------------- #
def _skipped_trace(
    *, stage: str, order: int, sha: str, reason: str
) -> StageTrace:
    """Trace d'une étape LLM optionnelle désactivée : le skip est explicite
    (règle d'or) — jamais une étape silencieusement absente."""
    return StageTrace(
        stage=stage,
        order=order,
        entities_in=1,
        entities_out=0,
        duration_ms=0.0,
        sha256_before=sha,
        sha256_after=sha,
        status="skipped",
        error=reason,
    )


# Import localisé pour retarder la dépendance ``detect.patterns`` tant que
# possible ? Non : ``DeterministicDetector`` est importé depuis le package.
from anonymisation.detect import DeterministicDetector as DeterministicDetectorLazy  # noqa: E402

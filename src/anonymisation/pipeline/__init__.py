"""Pipeline d'anonymisation — orchestrateur des huit étapes (SPEC-10).

API publique :

* :class:`Pipeline` — exécution des étapes DETECT → FUSE → ASSESS → PLAN →
  TRANSFORM → VALIDATE (+ AUDIT/REWRITE, désactivées en v1) sur un document
  du format pivot ;
* :class:`RuntimeProfile` / :func:`load_runtime_profile` — profils
  d'exécution (``configs/runtime/*.yaml``), chargement strict ;
* :class:`PipelineResult`, :class:`StageTrace`, :class:`RiskAssessment` —
  contrats de résultat (invariant : tous les offsets portent sur le texte
  original) ;
* :func:`validate_anonymization` / :class:`ValidationOutcome` — contrôles
  hors-ligne de l'étape VALIDATE.
"""

from anonymisation.pipeline.guards import LocalOnlyViolationError, assert_local_only
from anonymisation.pipeline.orchestrator import Pipeline, PipelineCapabilityError
from anonymisation.pipeline.profiles import (
    ProfileError,
    RuntimeProfile,
    load_runtime_profile,
)
from anonymisation.pipeline.traces import (
    PIPELINE_STATUSES,
    STAGE_ORDER,
    PipelineResult,
    RiskAssessment,
    StageTrace,
    serialize_pipeline_result,
)
from anonymisation.pipeline.validate_stage import ValidationOutcome, validate_anonymization

__all__ = [
    "PIPELINE_STATUSES",
    "Pipeline",
    "PipelineCapabilityError",
    "PipelineResult",
    "ProfileError",
    "RiskAssessment",
    "STAGE_ORDER",
    "StageTrace",
    "ValidationOutcome",
    "RuntimeProfile",
    "load_runtime_profile",
    "serialize_pipeline_result",
    "validate_anonymization",
    "LocalOnlyViolationError",
    "assert_local_only",
]

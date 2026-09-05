"""Métriques d'évaluation (SPEC-07).

Hiérarchie normative :
  1. CPR / IPR (protection multi-sujets) — métriques principales
  2. Risque de ré-identification (TRIR / R_succ)
  3. Utility Retention / Mean Utility
  4. Rappel QI et métriques span-level        — diagnostics complémentaires

Aucun rapport ne doit présenter un F1 de détection comme résultat principal.
"""

from anonymisation.metrics.accounting import RunAccounting
from anonymisation.metrics.contracts import (
    MetricComparisonError,
    MetricContractError,
    MetricDirection,
    MetricStatus,
    MetricValue,
    assert_comparable,
)
from anonymisation.metrics.entities import (
    entity_protection_counts,
    entity_recall,
    entity_recall_metrics,
    entity_recall_micro,
)
from anonymisation.metrics.protection import (
    SubjectOutcome,
    adversarial_accuracy,
    assert_published_together,
    collective_protection_rate,
    individual_protection_rate,
)
from anonymisation.metrics.scorecard import (
    ScorecardError,
    build_scorecard,
    validate_reproducibility,
    validate_scorecard,
)
from anonymisation.metrics.spans import span_metrics, weighted_token_precision
from anonymisation.metrics.tria import (
    TfidfReidentifier,
    TRIAClassifier,
    TRIARecord,
    TRIRResult,
    evaluate_trir,
    trir,
)
from anonymisation.metrics.utility import UtilityJudge, mean_utility, rouge_l

__all__ = [
    "MetricComparisonError",
    "MetricContractError",
    "MetricDirection",
    "MetricStatus",
    "MetricValue",
    "RunAccounting",
    "ScorecardError",
    "assert_comparable",
    "build_scorecard",
    "entity_protection_counts",
    "entity_recall",
    "entity_recall_metrics",
    "entity_recall_micro",
    "span_metrics",
    "TRIAClassifier",
    "TRIARecord",
    "TRIRResult",
    "TfidfReidentifier",
    "evaluate_trir",
    "trir",
    "UtilityJudge",
    "mean_utility",
    "rouge_l",
    "validate_reproducibility",
    "validate_scorecard",
    "weighted_token_precision",
    "SubjectOutcome",
    "adversarial_accuracy",
    "assert_published_together",
    "collective_protection_rate",
    "individual_protection_rate",
]

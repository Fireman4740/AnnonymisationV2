"""Métriques d'évaluation (SPEC-07).

Hiérarchie normative :
  1. Residual Re-Identification Risk (R_succ)  — métrique principale
  2. Utility Retention
  3. QI Combination Recall (QICR) + RCR@k      — à publier ensemble
  4. Calibration (ECE, Brier, MALE-k)
  5. P/R/F1 par span                            — diagnostic

Aucun rapport ne doit présenter un F1 comme résultat principal.
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
from anonymisation.metrics.entities import entity_protection_counts, entity_recall
from anonymisation.metrics.scorecard import (
    ScorecardError,
    build_scorecard,
    validate_reproducibility,
    validate_scorecard,
)
from anonymisation.metrics.spans import span_metrics, weighted_token_precision

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
    "span_metrics",
    "validate_reproducibility",
    "validate_scorecard",
    "weighted_token_precision",
]

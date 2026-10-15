"""API du banc actif : catalogue réduit, contrats et scorecards vérifiables.

Les modules historiques ne font plus partie des métriques publiées.
"""

from anonymisation.metrics.accounting import RunAccounting
from anonymisation.metrics.catalog import DIAGNOSTIC_METRICS, PRIMARY_METRICS
from anonymisation.metrics.contracts import (
    MetricComparisonError,
    MetricContractError,
    MetricDirection,
    MetricStatus,
    MetricValue,
    assert_comparable,
)
from anonymisation.metrics.scorecard import (
    ScorecardError,
    build_scorecard,
    validate_reproducibility,
    validate_scorecard,
)

__all__ = [
    "DIAGNOSTIC_METRICS",
    "PRIMARY_METRICS",
    "MetricComparisonError",
    "MetricContractError",
    "MetricDirection",
    "MetricStatus",
    "MetricValue",
    "RunAccounting",
    "ScorecardError",
    "assert_comparable",
    "build_scorecard",
    "validate_reproducibility",
    "validate_scorecard",
]

"""Contrats de métriques (EPIC-D D-2, SPEC-07 §9)."""

from __future__ import annotations

import pytest

from anonymisation.metrics.contracts import (
    MetricComparisonError,
    MetricContractError,
    MetricDirection,
    MetricStatus,
    MetricValue,
    assert_comparable,
)


def _metric(
    *,
    status: MetricStatus = MetricStatus.OFFICIAL,
    protocol: str = "tab-official",
    value: float | None = 0.5,
) -> MetricValue:
    return MetricValue(
        name="span_f1",
        value=value,
        protocol=protocol,
        protocol_version="1",
        status=status,
        direction=MetricDirection.MAXIMIZE,
    )


def test_metric_value_round_trip_preserves_contract() -> None:
    original = MetricValue(
        name="span_f1",
        value=0.75,
        protocol="micro-v1",
        protocol_version="1",
        status=MetricStatus.DIAGNOSTIC,
        direction=MetricDirection.MAXIMIZE,
        details={"match": "overlap"},
    )
    assert MetricValue.from_dict(original.to_dict()) == original


def test_protocol_is_required() -> None:
    with pytest.raises(MetricContractError, match="protocol"):
        _metric(protocol="")


def test_none_value_only_for_unavailable_or_failed() -> None:
    with pytest.raises(MetricContractError, match="value=None"):
        _metric(value=None)
    assert _metric(status=MetricStatus.UNAVAILABLE, value=None).value is None
    assert _metric(status=MetricStatus.FAILED, value=None).value is None


def test_official_and_proxy_are_not_comparable() -> None:
    with pytest.raises(MetricComparisonError, match="PROXY"):
        assert_comparable(_metric(), _metric(status=MetricStatus.PROXY))


def test_different_protocols_are_not_comparable() -> None:
    with pytest.raises(MetricComparisonError, match="protocoles"):
        assert_comparable(_metric(), _metric(protocol="other-v1"))


def test_same_official_metric_is_comparable() -> None:
    assert_comparable(_metric(), _metric(value=0.8))

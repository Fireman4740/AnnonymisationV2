"""Tests ROUGE-L et contrat Mean Utility (ticket G-4)."""

from __future__ import annotations

import pytest

from anonymisation.metrics.contracts import MetricStatus
from anonymisation.metrics.utility import mean_utility, rouge_l


def test_rouge_l_is_one_for_identical_text() -> None:
    assert rouge_l("Alice a 28 ans.", "Alice a 28 ans.") == pytest.approx(1.0)


def test_generalization_can_reduce_rouge_l_without_being_bad_anonymization() -> None:
    original = "Alice a 28 ans."
    exact = "Alice a 28 ans."
    generalized = "Alice est dans la fin de la vingtaine."

    assert rouge_l(original, exact) == pytest.approx(1.0)
    assert rouge_l(original, generalized) < rouge_l(original, exact)


def test_mean_utility_without_judge_is_unavailable_not_partial() -> None:
    result = mean_utility("Alice a 28 ans.", "Alice est dans la fin de la vingtaine.")

    assert result.status is MetricStatus.UNAVAILABLE
    assert result.value is None
    assert result.details["components"]["rouge_l"] < 1.0
    assert result.details["judge"] is None


def test_mean_utility_records_judge_and_three_components() -> None:
    class Judge:
        name = "local-judge-v1"

        def __call__(self, original: str, anonymized: str) -> dict[str, float]:
            assert original and anonymized
            return {"readability": 0.8, "meaning": 0.6}

    result = mean_utility("original", "anonymized", judge=Judge())

    assert result.status is MetricStatus.DIAGNOSTIC
    assert result.details["judge"] == "local-judge-v1"
    assert result.details["components"]["rouge_l"] == 0.0
    assert result.value == pytest.approx((0.8 + 0.6) / 3)

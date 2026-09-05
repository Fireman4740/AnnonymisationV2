"""Contrats CPR/IPR et inférence adversariale (ticket G-2)."""

from __future__ import annotations

import pytest

from anonymisation.metrics.contracts import MetricContractError
from anonymisation.metrics.protection import (
    SubjectOutcome,
    adversarial_accuracy,
    assert_published_together,
    collective_protection_rate,
    individual_protection_rate,
)


def test_cpr_and_ipr_weight_different_subjects_differ() -> None:
    subjects = [
        SubjectOutcome("large", pii_total=10, pii_still_inferable=7),
        SubjectOutcome("small", pii_total=1, pii_still_inferable=0),
    ]

    assert collective_protection_rate(subjects) == pytest.approx(4 / 11)
    assert individual_protection_rate(subjects) == pytest.approx((0.3 + 1.0) / 2)
    assert collective_protection_rate(subjects) != individual_protection_rate(subjects)


def test_zero_pii_subject_is_excluded_from_ipr() -> None:
    subjects = [
        SubjectOutcome("empty", pii_total=0, pii_still_inferable=0),
        SubjectOutcome("subject", pii_total=4, pii_still_inferable=2),
    ]

    assert individual_protection_rate(subjects) == pytest.approx(0.5)
    assert collective_protection_rate([subjects[0]]) is None


def test_multi_subject_cpr_differs_from_target_only_one_minus_aac() -> None:
    target_only_protection = 1.0  # AAC cible = 0 : sujet cible entièrement protégé
    subjects = [
        SubjectOutcome("target", pii_total=1, pii_still_inferable=0),
        SubjectOutcome("third-party", pii_total=9, pii_still_inferable=9),
    ]

    assert 1.0 - collective_protection_rate(subjects) != target_only_protection
    assert collective_protection_rate(subjects) == pytest.approx(0.1)


def test_weighted_variant_is_explicit_and_uniform_default_is_preserved() -> None:
    subjects = [
        SubjectOutcome(
            "p",
            2,
            1,
            pii_by_category={"DIR_NAME": (1, 1), "GEN_AGE": (1, 0)},
        )
    ]

    assert collective_protection_rate(subjects) == pytest.approx(0.5)
    assert collective_protection_rate(subjects, weights={"DIR_NAME": 2.0, "GEN_AGE": 1.0}) == pytest.approx(
        1 / 3
    )


def test_adversarial_accuracy_exact_partial_false() -> None:
    assert adversarial_accuracy("Alice", "Alice") == 1.0
    assert adversarial_accuracy("Los Angeles, California", "California") == 0.5
    assert adversarial_accuracy("Paris", "Berlin") == 0.0
    assert adversarial_accuracy(["wrong", "Alice"], "Alice") == 1.0


def test_cpr_and_ipr_must_be_published_together() -> None:
    assert_published_together({"cpr": {"value": 0.3}, "ipr": {"value": 0.4}})
    assert_published_together({"cpr": None, "ipr": None})
    with pytest.raises(MetricContractError, match="ensemble"):
        assert_published_together({"cpr": {"value": 0.3}, "ipr": None})

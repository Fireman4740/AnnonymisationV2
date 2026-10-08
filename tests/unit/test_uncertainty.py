"""Tests du bootstrap en grappes et des formules de calibration (EPIC-H H-1, H-7)."""

from __future__ import annotations

import math

import pytest

from anonymisation.metrics.calibration import brier, ece_equal_mass, ece_sensitivity, male_k
from anonymisation.metrics.leakage import gold_leak_counts, surface_present
from anonymisation.metrics.uncertainty import (
    bootstrap_interval,
    f1_of_counts,
    mean,
    ratio_of_sums,
    with_interval,
)

# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #


def test_bootstrap_is_deterministic_and_contains_point_estimate() -> None:
    units = [(1.0, 2.0), (2.0, 2.0), (0.0, 3.0), (3.0, 4.0), (1.0, 1.0)]
    statistic = ratio_of_sums(0, 1)
    first = bootstrap_interval(units, statistic, unit="document", replicates=500)
    second = bootstrap_interval(units, statistic, unit="document", replicates=500)
    assert first == second
    assert first is not None
    point = statistic(units)
    assert point is not None
    assert first["low"] <= point <= first["high"]
    assert first["unit"] == "document" and first["units"] == 5


def test_bootstrap_undefined_below_two_units() -> None:
    assert bootstrap_interval([0.5], mean, unit="document") is None
    assert bootstrap_interval([], mean, unit="document") is None


def test_bootstrap_counts_undefined_replicates_instead_of_zeroing() -> None:
    # Un seul document porte du gold : de nombreux réplicats n'en tirent aucun.
    units = [(1.0, 1.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0)]
    interval = bootstrap_interval(units, ratio_of_sums(0, 1), unit="document", replicates=200)
    assert interval is not None
    assert interval["undefined_replicates"] > 0
    assert interval["low"] == interval["high"] == 1.0


def test_f1_of_counts_matches_definition() -> None:
    assert f1_of_counts([(2.0, 1.0, 1.0)]) == pytest.approx(2 * 2 / (2 * 2 + 1 + 1))
    assert f1_of_counts([(0.0, 0.0, 0.0)]) is None


def test_with_interval_does_not_mutate_and_skips_unavailable() -> None:
    metric = {"value": 0.5, "details": {"match": "partial"}}
    updated = with_interval(metric, {"low": 0.4, "high": 0.6})
    assert "ci95" not in metric["details"]
    assert updated["details"]["ci95"] == {"low": 0.4, "high": 0.6}
    assert updated["details"]["match"] == "partial"
    unavailable = {"value": None, "details": {}}
    assert with_interval(unavailable, None) is unavailable


# --------------------------------------------------------------------------- #
# Calibration (SPEC-07 §4)
# --------------------------------------------------------------------------- #


def test_male_k_uses_spec_formula() -> None:
    assert male_k([(1.0, 3.0)]) == pytest.approx(abs(math.log(2.0) - math.log(4.0)))
    assert male_k([(0.0, 0.0)]) == 0.0  # le +1 rend k = 0 défini
    assert male_k([]) is None
    with pytest.raises(ValueError):
        male_k([(-1.0, 2.0)])


def test_ece_is_none_on_empty_and_zero_when_perfect() -> None:
    assert ece_equal_mass([]) is None
    pairs = [(0.1, 0.1), (0.5, 0.5), (0.9, 0.9)]
    assert ece_equal_mass(pairs) == pytest.approx(0.0)
    assert brier(pairs) == pytest.approx(0.0)


def test_ece_sensitivity_reports_every_bin_count() -> None:
    pairs = [(i / 40, (i % 7) / 7) for i in range(40)]
    report = ece_sensitivity(pairs)
    assert set(report) == {"5", "10", "15", "20"}
    assert all(value is not None for value in report.values())


# --------------------------------------------------------------------------- #
# Adversaire littéral : recherche normalisée, bornée aux mots
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("surface", "text", "expected"),
    [
        ("28", "né en 1928 à Lille", False),        # sous-chaîne d'un nombre
        ("Li", "il vit à Lille", False),             # sous-chaîne d'un mot
        ("Dupont", "M. DUPONT a appelé", True),      # casse
        ("Jean Dupont", "Jean  Dupont", True),       # espacement
        ("M.", "M. Martin", True),                   # ponctuation finale
        ("28 ans", "j'ai 28 ans.", True),
        ("Lille", "Lillebonne", False),
    ],
)
def test_surface_present(surface: str, text: str, expected: bool) -> None:
    assert surface_present(surface, text) is expected


def test_gold_leak_counts_use_word_bounded_search() -> None:
    gold = [{"span_text": "28", "identifier_type": "quasi"}]
    assert gold_leak_counts("né en 1928", gold).leaked == 0
    assert gold_leak_counts("âgé de 28 ans", gold).leaked == 1

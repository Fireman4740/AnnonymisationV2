"""QICR / RCR@k / calibration sur vérité terrain indépendante (EPIC-H H-4, H-6)."""

from __future__ import annotations

import math

import pytest

from anonymisation.metrics.combinations import CombinationError, combination_metrics
from anonymisation.metrics.ner_schemas import corpus_counts


def _ann(i: int, category: str = "GEN_AGE") -> dict:
    return {"annotation_id": f"a{i}", "doc_id": "d", "start": i * 10, "end": i * 10 + 4,
            "qi_categories": [category], "identifier_type": "QUASI"}


def _combo(ids, k_true, doc="d", cid="c1") -> dict:
    return {"combination_id": cid, "doc_ids": [doc], "annotation_ids": list(ids), "k_true": k_true}


GOLD = {"d": tuple(_ann(i) for i in range(4))}


def _pred(n_detected: int, k_hat: float | None = None) -> dict:
    return {"doc_id": "d", "status": "ok", "annotations": list(GOLD["d"][:n_detected]),
            "risk": None if k_hat is None else {"k_hat": k_hat}}


def test_three_of_four_qi_gives_span_recall_075_and_qicr_zero():
    """Acceptation H-4 : le F1 de spans voit 3/4, QICR voit la combinaison manquée."""
    prediction = _pred(3)
    total, _, _ = corpus_counts([(GOLD["d"], prediction["annotations"])])
    assert total["strict"].scores("strict")["recall"] == 0.75
    result = combination_metrics([_combo([f"a{i}" for i in range(4)], 2)], GOLD,
                                 {"d": prediction}, split="test")
    assert result["qicr"] == 0.0
    assert result["qicr_at_j"]["4"] == {"detected": 0, "total": 1, "value": 0.0}


def test_all_qi_detected_gives_qicr_one():
    result = combination_metrics([_combo([f"a{i}" for i in range(4)], 2)], GOLD,
                                 {"d": _pred(4)}, split="test")
    assert result["qicr"] == 1.0


def test_combination_not_at_risk_or_unlinked_is_outside_the_denominator():
    combos = [_combo(["a0"], 50, cid="safe"), _combo([], 1, cid="unlinked")]
    result = combination_metrics(combos, GOLD, {"d": _pred(4)}, split="test")
    assert result["qicr"] is None
    assert result["unlinked_at_risk"] == 1


def test_missing_k_true_is_not_guessed():
    result = combination_metrics([_combo(["a0"], None)], GOLD, {"d": _pred(4)}, split="test")
    assert result["without_k_true"] == 1 and result["qicr"] is None and result["rcr"] is None


def test_document_in_error_excludes_its_combination():
    result = combination_metrics([_combo(["a0"], 1)], GOLD, {}, split="test")
    assert result["excluded_document_errors"] == 1 and result["qicr"] is None


def test_annotation_absent_from_gold_is_an_error():
    with pytest.raises(CombinationError, match="absentes"):
        combination_metrics([_combo(["zz"], 1)], GOLD, {"d": _pred(4)}, split="test")


def test_rcr_counts_over_masking_and_calibration_uses_prosecutor_target():
    combos = [_combo(["a0"], 20, cid="big"), _combo(["a1"], 2, doc="d", cid="small")]
    result = combination_metrics(combos, GOLD, {"d": _pred(4, k_hat=5.0)}, k_threshold=10,
                                 rcr_k=10, split="test")
    assert result["rcr"] == 0.0  # k_true=20 ≥ 10 mais k̂=5 < 10 : sur-masquage
    calibration = result["calibration"]
    assert calibration["pairs"] == 2
    expected = (abs(math.log(6) - math.log(21)) + abs(math.log(6) - math.log(3))) / 2
    assert calibration["male_k"] == pytest.approx(expected)
    assert calibration["brier"] == pytest.approx(((0.2 - 0.05) ** 2 + (0.2 - 0.5) ** 2) / 2)
    assert set(calibration["ece_by_bins"]) == {"5", "10", "15", "20"}


def test_calibration_on_a_fit_split_is_refused():
    result = combination_metrics([_combo(["a0"], 2)], GOLD, {"d": _pred(4, k_hat=2.0)},
                                 split="calib")
    assert result["calibration"]["male_k"] is None and result["calibration"]["fit_split"]

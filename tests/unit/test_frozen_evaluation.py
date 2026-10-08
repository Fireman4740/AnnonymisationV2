"""Contrats de l'attaque et du juge : aucune socket ni Julia en test."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from anonymisation.attack.ratbench.maps import RatBenchMaps
from anonymisation.attack.ratbench.risk import CorrectMatchRisk, CorrectMatchUnavailable
from anonymisation.attack.ratbench.runner import attack_one
from anonymisation.cli.score import ScoreError, _load_frozen
from anonymisation.judge.utility import JudgeError, judge_one, parse_judgment
from anonymisation.metrics.reidentification import reid_success_metric
from anonymisation.metrics.utility import mean_utility_from_judgments
from anonymisation.schema.io import sha256_file


def _reply(readability=10, meaning=10, hallucinations=1):
    return json.dumps({k: {"score": v} for k, v in (
        ("readability", readability), ("meaning", meaning), ("hallucinations", hallucinations))})


@pytest.mark.parametrize("reply", ["", "[]", "{}", _reply(0), _reply(11),
                                      _reply(float("nan")), _reply(True),
                                      _reply(hallucinations=0.5)])
def test_invalid_judge_is_error_not_default(reply):
    with pytest.raises(JudgeError):
        parse_judgment(reply)


def test_judge_preserves_original_formula_and_raw_answer():
    reply = _reply(10, 8)
    row = judge_one("d1", "Alice works here.", "Alice works here.", lambda _: (reply, False))
    assert row["status"] == "ok"
    assert row["rougeL"] == 1
    assert row["utility_comb"] == pytest.approx((1 + 0.8 + 1) / 3)
    assert row["response"] == reply
    metric = mean_utility_from_judgments([row], {"protocol": "mean-utility-spia", "protocol_version": "1"})
    assert metric.value == row["utility_comb"]
    row["utility_comb"] = 0.1
    with pytest.raises(ValueError, match="incohérent"):
        mean_utility_from_judgments([row], {})


def test_bad_response_never_becomes_low_utility():
    row = judge_one("d1", "Alice works.", "Someone works.", lambda _: ("not JSON", False))
    assert row["status"] == "error"
    metric = mean_utility_from_judgments([row], {})
    assert metric.value is None
    assert metric.status.value == "unavailable"


def _write_frozen(root: Path, rows):
    root.mkdir(exist_ok=True)
    name = "judgments.jsonl"
    (root / name).write_text("".join(json.dumps(r) + "\n" for r in rows))
    errors = sum(r["status"] == "error" for r in rows)
    rate = errors / len(rows) if rows else 1
    lock = {"protocol": "mean-utility-spia", "protocol_version": "1",
            "inputs": {"predictions.jsonl": "pred", "documents.jsonl": "gold"},
            "outputs": {name: sha256_file(root / name)},
            "documents": len(rows), "documents_error": errors,
            "error_rate": rate, "publishable": rate <= 0.05}
    (root / "judge.lock.json").write_text(json.dumps(lock))
    (root / "manifest.lock.json").write_text(json.dumps({
        "run": {"split": "eval"}, "data_version": {"files": {"eval/documents.jsonl": "gold"}}}))
    return lock


@pytest.mark.parametrize("rows", [[], [{"doc_id": "d1", "status": "ok"}],
    [{"doc_id": "d1", "status": "ok"}, {"doc_id": "d1", "status": "ok"}],
    [{"doc_id": "d1", "status": "ok"}, {"doc_id": "foreign", "status": "ok"}]])
def test_frozen_missing_duplicate_foreign_rows_are_rejected(tmp_path, rows):
    _write_frozen(tmp_path, rows)
    with pytest.raises(ScoreError, match="couverture"):
        _load_frozen(tmp_path, "pred", "judge.lock.json", "judgments.jsonl",
                     expected_doc_ids={"d1", "d2"}, expected_protocol="mean-utility-spia")


def test_frozen_stage_accounts_for_every_target(tmp_path):
    rows = [{"doc_id": "d1", "status": "ok"}, {"doc_id": "d2", "status": "error"}]
    _write_frozen(tmp_path, rows)
    loaded, lock = _load_frozen(tmp_path, "pred", "judge.lock.json", "judgments.jsonl",
                               expected_doc_ids={"d1", "d2"}, expected_protocol="mean-utility-spia")
    assert loaded == rows
    assert not lock["publishable"]


@pytest.mark.parametrize("field, value", [("documents", 3), ("documents_error", 1),
                                         ("protocol", "unrelated")])
def test_frozen_wrong_protocol_or_accounting_rejected(tmp_path, field, value):
    lock = _write_frozen(tmp_path, [{"doc_id": "d1", "status": "ok"}])
    lock[field] = value
    (tmp_path / "judge.lock.json").write_text(json.dumps(lock))
    with pytest.raises(ScoreError):
        _load_frozen(tmp_path, "pred", "judge.lock.json", "judgments.jsonl",
                     expected_doc_ids={"d1"}, expected_protocol="mean-utility-spia")


def test_correctmatch_dense_encoder_handles_holes():
    import pandas as pd

    risk = CorrectMatchRisk.__new__(CorrectMatchRisk)
    risk._frame = pd.DataFrame({"DOB": [1, 3, 3, 34847]})
    risk._dense = {}
    assert risk._encoder("DOB") == {1: 1, 3: 2, 34847: 3}


def test_attack_partial_answer_is_error_and_risk_failure_is_counted():
    maps = RatBenchMaps(pairs={"SEX": ((1, "Male"), (2, "Female"))}, source="fixture")
    profile = SimpleNamespace(meta={"features": ["SEX", "name"],
        "direct_identifiers": {"name": "Alice"}, "indirect_identifiers": {"SEX": "Female"},
        "scenario": "Chatbot conversation", "difficulty": 1})
    record = {"doc_id": "d1", "anonymized_text": "Alice is female."}
    row = attack_one(record, profile, maps, lambda _: ('{"sex": {"Guess": "Female"}}', False), None)
    assert row["status"] == "error"
    assert "incomplète" in row["error"]

    class BrokenRisk:
        def estimate(self, _):
            raise CorrectMatchUnavailable("code absent")

    reply = '{"sex": {"Guess": "Female"}, "name": {"Guess": "Alice"}}'
    row = attack_one(record, profile, maps, lambda _: (reply, False), BrokenRisk())
    assert row["status"] == "error"
    assert "code absent" in row["error"]


def test_reid_success_requires_actual_direct_hit_or_threshold():
    rows = [{"doc_id": "d1", "status": "ok", "correct_direct_ids": [],
             "correctmatch_correctness": 0.19, "reidentified": False},
            {"doc_id": "d2", "status": "ok", "correct_direct_ids": [],
             "correctmatch_correctness": 0.2, "reidentified": True}]
    assert reid_success_metric(rows, {})["value"] == 0.5
    rows[0]["reidentified"] = True
    with pytest.raises(ValueError, match="incohérent"):
        reid_success_metric(rows, {})

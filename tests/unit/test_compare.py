"""Tests unitaires pour metrics/comparison.py et cli/compare.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anonymisation.cli.compare import CompareError, cmd_compare, update_runs_index
from anonymisation.metrics.comparison import (
    assert_comparable_across_systems,
    render_comparison_markdown,
)
from anonymisation.metrics.contracts import MetricComparisonError


def _dummy_scorecard(system_id: str, cpr_val: float | None = 0.85) -> dict:
    return {
        "run_id": f"run_{system_id}",
        "dataset": "test_ds",
        "split": "test",
        "protocol": "proto1",
        "protocol_version": "1",
        "system": {
            "system_id": system_id,
            "system_version": "1",
            "params_digest": "hash123",
        },
        "status": "diagnostic",
        "error_rate": 0.0,
        "primary": {
            "cpr": {"name": "cpr", "value": cpr_val, "status": "proxy"},
            "ipr": {"name": "ipr", "value": 0.80, "status": "proxy"},
            "trir": {"name": "trir", "value": 0.10, "status": "proxy"},
            "utility_retention": {"name": "utility_retention", "value": None, "status": "unavailable", "details": {"reason": "none"}},
        },
        "diagnostic": {
            "rouge_l": {"name": "rouge_l", "value": 0.92, "status": "diagnostic"},
            "mean_utility": {"name": "mean_utility", "value": None, "status": "unavailable", "details": {"reason": "no judge"}},
            "ER_di": {"name": "ER_di", "value": 0.95, "status": "diagnostic"},
            "ER_qi": {"name": "ER_qi", "value": 0.70, "status": "diagnostic"},
            "gold_leak_rate": {"name": "gold_leak_rate", "value": 0.0, "status": "diagnostic"},
        },
        "efficiency": {
            "latency_p50_ms": 12.34,
        },
    }


def test_assert_comparable_across_systems_refuses_different_datasets():
    sc1 = _dummy_scorecard("sys1")
    sc2 = _dummy_scorecard("sys2")
    sc2["dataset"] = "other_ds"

    with pytest.raises(MetricComparisonError, match="dataset incompatible"):
        assert_comparable_across_systems([sc1, sc2])


def test_render_comparison_markdown():
    sc1 = _dummy_scorecard("sys_b", cpr_val=0.80)
    sc2 = _dummy_scorecard("sys_a", cpr_val=0.90)

    md = render_comparison_markdown([sc1, sc2])
    assert "| `sys_a` |" in md
    assert "| `sys_b` |" in md
    # Doit être trié par system_id
    idx_a = md.index("`sys_a`")
    idx_b = md.index("`sys_b`")
    assert idx_a < idx_b
    assert "0.9000" in md
    assert "0.8000" in md
    assert "Provenance et statut" in md


def test_cmd_compare_and_index(tmp_path: Path):
    run1 = tmp_path / "run_sys1"
    run2 = tmp_path / "run_sys2"
    run1.mkdir()
    run2.mkdir()

    sc1 = _dummy_scorecard("sys1")
    sc2 = _dummy_scorecard("sys2")
    (run1 / "scorecard.json").write_text(json.dumps(sc1), encoding="utf-8")
    (run2 / "scorecard.json").write_text(json.dumps(sc2), encoding="utf-8")

    out_md = tmp_path / "report.md"
    index_file = tmp_path / "index.json"

    # Tester update_runs_index
    update_runs_index([(run1, sc1), (run2, sc2)], index_path=index_file)
    assert index_file.is_file()
    index_data = json.loads(index_file.read_text(encoding="utf-8"))
    assert len(index_data) == 2

    # Collision check
    run1_dup = tmp_path / "run_sys1_other"
    run1_dup.mkdir()
    with pytest.raises(CompareError, match="Collision de run_id"):
        update_runs_index([(run1_dup, sc1)], index_path=index_file)

    # index_path explicite : sans lui, la commande écrirait dans le
    # runs/index.json du dépôt et les tests pollueraient l'index réel.
    ret = cmd_compare([run1, run2], out_path=out_md, index_path=index_file)
    assert ret == 0
    assert out_md.is_file()
    assert "# Comparaison des systèmes" in out_md.read_text(encoding="utf-8")

"""Golden test rapide du pipeline déterministe (SPEC-10 §10, ticket E-3)."""

from __future__ import annotations

import difflib
import json
from pathlib import Path

import pytest

from anonymisation.cli import predict
from anonymisation.cli.main import main
from integration._micro import write_micro_pivot

GOLDEN_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "golden"
    / "predictions_micro_P2.jsonl"
)


def _read_prediction_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"prediction golden invalide ligne {line_number}: {exc}") from exc
        if not isinstance(payload, dict) or not payload.get("doc_id"):
            raise AssertionError(f"prediction golden invalide ligne {line_number}: doc_id absent")
    return lines


def test_micro_predictions_match_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """P2 est comparé ligne à ligne ; la régénération est toujours explicite."""
    processed = write_micro_pivot(tmp_path / "processed")
    monkeypatch.setattr(predict, "PROCESSED_ROOT", processed)
    output = tmp_path / "run"
    assert main(
        [
            "predict",
            "--dataset",
            "micro",
            "--split",
            "train",
            "--policy",
            "P2",
            "--profile",
            "deterministic",
            "--out",
            str(output),
        ]
    ) in (0, 1)

    actual = _read_prediction_lines(output / "predictions.jsonl")
    if request.config.getoption("--update-golden"):
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text("\n".join(actual) + "\n", encoding="utf-8")

    if not GOLDEN_PATH.is_file():
        pytest.fail(
            f"Golden absent : {GOLDEN_PATH}. "
            "Régénérez-le explicitement avec `pytest --update-golden`."
        )
    expected = _read_prediction_lines(GOLDEN_PATH)
    diff = "\n".join(
        difflib.unified_diff(
            expected,
            actual,
            fromfile=str(GOLDEN_PATH),
            tofile="predictions.jsonl produit",
            lineterm="",
            n=1,
        )
    )
    assert not diff, "Golden micro différent :\n" + diff

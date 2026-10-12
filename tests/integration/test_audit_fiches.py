"""Fiches d'audit H-9 : reconstruction exacte depuis les décisions, offsets."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_predict import _predict, micro_pivot  # noqa: E402,F401  (fixture réutilisée)

_PATH = Path(__file__).resolve().parents[2] / "scripts/audit_fiches.py"
_SPEC = importlib.util.spec_from_file_location("audit_fiches", _PATH)
assert _SPEC and _SPEC.loader
audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit)


def test_clean_run_has_no_gap_and_reconstructs_every_text(micro_pivot: Path, tmp_path: Path):
    run = tmp_path / "run"
    assert _predict(run) == 0
    out = tmp_path / "audit"
    assert audit.main([str(run), "--processed", str(micro_pivot), "--out", str(out)]) == 0
    payload = json.loads((out / "audit.json").read_text())
    assert payload["summary"]["gaps"] == 0
    scored = [s for s in payload["sheets"] if s["scored"]]
    assert scored and all(s["reconstruction_identical"] for s in scored)
    assert len(list(out.glob("*.md"))) == payload["summary"]["documents"]


def test_frozen_text_that_does_not_follow_the_decisions_is_flagged(micro_pivot: Path, tmp_path: Path):
    run = tmp_path / "run"
    assert _predict(run) == 0
    path = run / "predictions.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["anonymized_text"] += " (édité)"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = tmp_path / "audit"
    assert audit.main([str(run), "--processed", str(micro_pivot), "--out", str(out)]) == 1
    gaps = json.loads((out / "audit.json").read_text())["summary"]["documents_with_gaps"]
    assert gaps == [rows[0]["doc_id"]]

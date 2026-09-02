"""Tests de ``anonv2 score`` (ticket C-4, SPEC-07 §10, SPEC-10 §5).

Le score est alimenté par un run synthétique : aucun téléchargement et aucun
appel au pipeline de détection. La campagne de prédiction est volontairement
absente de ce fichier afin de vérifier la frontière hors ligne.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from anonymisation.cli import score
from anonymisation.metrics.scorecard import ScorecardError, validate_scorecard
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Sensitivity,
    Stability,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _annotation(
    annotation_id: str, doc_id: str, start: int, end: int, span_text: str
) -> Annotation:
    return Annotation(
        annotation_id=annotation_id,
        doc_id=doc_id,
        start=start,
        end=end,
        span_text=span_text,
        identifier_type=IdentifierType.DIRECT,
        qi_categories=("DIR_NAME",),
        expression_mode=ExpressionMode.EXPLICIT,
        sensitivity=Sensitivity.NONE,
        granularity=Granularity.EXACT,
        stability=Stability.STABLE,
    )


def _write_jsonl(path: Path, records: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            payload = record.model_dump(mode="json") if hasattr(record, "model_dump") else record
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _build_run(root: Path) -> Path:
    dataset = "mini"
    split = "train"
    pivot = root / "processed" / dataset / split
    documents = [
        Document(
            doc_id="mini:d1",
            dataset=dataset,
            split=split,
            domain="hr",
            language="fr",
            text="Alice travaille.",
        ),
        Document(
            doc_id="mini:d2",
            dataset=dataset,
            split=split,
            domain="hr",
            language="fr",
            text="Bob travaille.",
        ),
    ]
    gold = [_annotation("a1", "mini:d1", 0, 5, "Alice")]
    _write_jsonl(pivot / "documents.jsonl", documents)
    _write_jsonl(pivot / "annotations.jsonl", gold)

    run = root / "run"
    run.mkdir()
    lock = {
        "lock_version": 1,
        "run": {
            "dataset": dataset,
            "split": split,
            "profile": "deterministic",
            "policy": "P2",
            "limit": None,
            "status": "complete",
        },
        "data_version": {"source": "fixture"},
        "taxonomy_version": "1.0",
        "code": {"git_commit": "fixture-commit"},
        "models": [],
        "seeds": {"determinism": 42},
        "prompts": [],
        "policy": {"id": "P2", "source": "policies.yaml", "sha256": "a" * 64},
    }
    (run / "manifest.lock.json").write_text(
        json.dumps(lock, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    predictions = [
        {
            "doc_id": "mini:d1",
            "status": "ok",
            "error": [],
            "annotations": [gold[0].model_dump(mode="json")],
            "decisions": [],
            "anonymized_text": "<PERSON>",
            "risk": None,
            "runtime_ms": 0.0,
        },
        {
            "doc_id": "mini:d2",
            "status": "error",
            "error": ["DETECT: timeout"],
            "annotations": [],
            "decisions": [],
            "anonymized_text": "Bob travaille.",
            "risk": None,
            "runtime_ms": 0.0,
        },
    ]
    _write_jsonl(run / "predictions.jsonl", predictions)
    return run


@pytest.fixture
def score_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workspace"
    run = _build_run(root)
    monkeypatch.setattr(score, "PROCESSED_ROOT", root / "processed")
    monkeypatch.setattr(score, "DATASETS_CONFIG", root / "configs")
    return run


def test_score_is_offline_and_never_imports_detector() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    code = (
        "import sys; "
        "from anonymisation.cli.main import main; "
        "assert not any(name == 'anonymisation.detect' or "
        "name.startswith('anonymisation.detect.') for name in sys.modules); "
        "assert main(['score', '--run', '/does/not/exist', '--protocol', 'mini-v1']) == 2"
    )
    result = subprocess.run(
        (sys.executable, "-c", code),
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Lock de run absent" in result.stderr


def test_score_excludes_error_from_confusion_counts(score_fixture: Path, capsys) -> None:
    rc = score.cmd_score(score_fixture, "mini-v1")
    assert rc == 1  # 50 % d'erreurs : avertissement C-5 bloquant
    card = json.loads(score_fixture.joinpath("scorecard.json").read_text(encoding="utf-8"))
    assert card["error_rate"] == pytest.approx(0.5)
    assert card["accounting"]["documents_total"] == 2
    assert card["accounting"]["documents_scored"] == 1
    assert card["accounting"]["errors_by_stage"] == {"DETECT": 1}
    assert card["diagnostic"]["counts"]["tp"] == 1
    assert card["diagnostic"]["counts"]["fp"] == 0
    assert card["diagnostic"]["counts"]["fn"] == 0
    assert card["diagnostic"]["counts"]["gold"] == 1
    for name in ("by_language", "by_domain", "by_expression"):
        assert name in card
        assert card[name]
    assert "AVERTISSEMENT BLOQUANT" in capsys.readouterr().out
    validate_scorecard(card)


def test_score_repeated_is_bit_identical(score_fixture: Path) -> None:
    assert score.cmd_score(score_fixture, "mini-v1") == 1
    first = score_fixture.joinpath("scorecard.json").read_bytes()
    assert score.cmd_score(score_fixture, "mini-v1") == 1
    second = score_fixture.joinpath("scorecard.json").read_bytes()
    assert first == second


def test_taxonomy_mismatch_requires_reprediction(score_fixture: Path) -> None:
    lock_path = score_fixture / "manifest.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["taxonomy_version"] = "0.9"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(score.ScoreError, match="Reprédiction"):
        score.cmd_score(score_fixture, "mini-v1")
    assert not score_fixture.joinpath("scorecard.json").exists()


def test_invalid_scorecard_missing_reproducibility_is_rejected() -> None:
    with pytest.raises(ScorecardError, match="Lock de reproductibilité incomplet"):
        validate_scorecard(
            {
                "run_id": "r",
                "schema_version": "2.0",
                "system": {},
                "dataset": "mini",
                "split": "train",
                "primary": {},
                "diagnostic": {},
                "by_language": {},
                "by_domain": {},
                "by_expression": {},
                "efficiency": {},
                "accounting": {"error_rate": 0.0},
                "error_rate": 0.0,
                "reproducibility": {},
            }
        )


def test_all_error_run_produces_unavailable_metrics(
    score_fixture: Path,
) -> None:
    predictions_path = score_fixture / "predictions.jsonl"
    records = [
        {
            "doc_id": "mini:d1",
            "status": "error",
            "error": ["DETECT: timeout"],
            "annotations": [],
        },
        {
            "doc_id": "mini:d2",
            "status": "error",
            "error": ["DETECT: timeout"],
            "annotations": [],
        },
    ]
    _write_jsonl(predictions_path, records)
    assert score.cmd_score(score_fixture, "mini-v1") == 1
    card = json.loads((score_fixture / "scorecard.json").read_text(encoding="utf-8"))
    assert card["accounting"]["documents_scored"] == 0
    assert card["diagnostic"]["span_f1"]["value"] is None
    assert card["diagnostic"]["span_f1"]["status"] == "unavailable"

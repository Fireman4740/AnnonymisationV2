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


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relock_outputs(run: Path) -> None:
    """Réécrit l'empreinte des prédictions après une modification **voulue** par le test."""
    lock_path = run / "manifest.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["outputs"] = {"predictions.jsonl": _sha(run / "predictions.jsonl")}
    lock_path.write_text(json.dumps(lock, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_manifest(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "mini.yaml").write_text(
        "evaluation:\n"
        "  protocol: mini-v1\n"
        "  protocol_version: '1'\n"
        "  default_metric_status: DIAGNOSTIC\n",
        encoding="utf-8",
    )


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
        "data_version": {
            "source": "fixture",
            "files": {
                f"{split}/documents.jsonl": _sha(pivot / "documents.jsonl"),
                f"{split}/annotations.jsonl": _sha(pivot / "annotations.jsonl"),
            },
        },
        "taxonomy_version": "1.0",
        "code": {"git_commit": "fixture-commit", "git_dirty": False},
        "models": [],
        "seeds": {"determinism": 42},
        "prompts": [],
        "policy": {"id": "P2", "source": "policies.yaml", "sha256": "a" * 64},
        # L'identité du système est désormais requise : elle commande quelles
        # métriques sont applicables (portillon de capacités).
        "system": {
            "system_id": "test-v1",
            "system_version": "1",
            "capabilities": [
                "decisions", "gold_aware", "policy", "risk", "spans", "traces",
            ],
            "params_digest": "0" * 64,
            "oracle": False,
        },
    }
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
    lock["outputs"] = {"predictions.jsonl": _sha(run / "predictions.jsonl")}
    (run / "manifest.lock.json").write_text(
        json.dumps(lock, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return run


@pytest.fixture
def score_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workspace"
    run = _build_run(root)
    monkeypatch.setattr(score, "PROCESSED_ROOT", root / "processed")
    _write_manifest(root / "configs")
    monkeypatch.setattr(score, "DATASETS_CONFIG", root / "configs")
    return run


@pytest.mark.parametrize("sampled_at", ["data_version", "run"])
def test_official_protocol_on_sampled_inputs_stays_sampled(score_fixture: Path, sampled_at: str):
    config = score.DATASETS_CONFIG / "mini.yaml"
    config.write_text(config.read_text().replace("DIAGNOSTIC", "OFFICIAL"))
    predictions_path = score_fixture / "predictions.jsonl"
    rows = [json.loads(line) for line in predictions_path.read_text().splitlines()]
    for row in rows:
        row.update(status="ok", error=[])
    _write_jsonl(predictions_path, rows)
    _relock_outputs(score_fixture)
    path = score_fixture / "manifest.lock.json"
    lock = json.loads(path.read_text())
    lock[sampled_at]["status"] = "sampled"
    path.write_text(json.dumps(lock))
    score.cmd_score(str(score_fixture), "mini-v1")
    card = json.loads((score_fixture / "scorecard.json").read_text())
    assert card["status"] == "sampled"
    # Sans attaque SPIA figée, CPR/IPR principaux sont indisponibles ; la
    # présence littérale reste un diagnostic distinct.
    assert "cpr" not in card["primary"]
    assert "SPIA" in card["not_applicable"]["cpr"]
    assert "literal_cpr" not in card["diagnostic"]


def test_score_is_offline_and_never_imports_detector() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    # `systems` est ajouté à la liste interdite : il importe `detect` via le
    # système déterministe. Si `metrics` ou `score` venaient à en dépendre —
    # par exemple pour lire le vocabulaire de capacités — le scoring
    # chargerait un détecteur et cesserait d'être rejouable hors ligne. C'est
    # la raison d'être de `anonymisation.capabilities`, qui n'importe rien.
    forbidden = ("anonymisation.detect", "anonymisation.systems", "anonymisation.pipeline")
    code = (
        "import sys; "
        "from anonymisation.cli.main import main; "
        f"forbidden = {forbidden!r}; "
        "leaked = sorted(n for n in sys.modules "
        "if any(n == f or n.startswith(f + '.') for f in forbidden)); "
        "assert not leaked, leaked; "
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
                "schema_version": "3.1",
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
    _relock_outputs(score_fixture)
    assert score.cmd_score(score_fixture, "mini-v1") == 1
    card = json.loads((score_fixture / "scorecard.json").read_text(encoding="utf-8"))
    assert card["accounting"]["documents_scored"] == 0
    assert "span_f1" not in card["diagnostic"]
    assert card["not_applicable"]["span_f1"]


# --------------------------------------------------------------------------- #
# Reproductibilité (EPIC-H) : le score lit exactement les octets du run
# --------------------------------------------------------------------------- #
def test_score_refuses_gold_modified_after_predict(score_fixture: Path) -> None:
    annotations = score_fixture.parent / "processed" / "mini" / "train" / "annotations.jsonl"
    annotations.write_text(annotations.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(score.ScoreError, match="empreinte divergente"):
        score.cmd_score(score_fixture, "mini-v1")


def test_score_refuses_predictions_edited_after_predict(score_fixture: Path) -> None:
    predictions = score_fixture / "predictions.jsonl"
    predictions.write_text(predictions.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(score.ScoreError, match="modifié après"):
        score.cmd_score(score_fixture, "mini-v1")


def test_score_requires_declared_protocol(
    score_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(score, "DATASETS_CONFIG", tmp_path / "nowhere")
    with pytest.raises(score.ScoreError, match="Manifeste absent"):
        score.cmd_score(score_fixture, "mini-v1")


def test_score_rejects_unknown_default_status(score_fixture: Path) -> None:
    config = score_fixture.parent / "configs" / "mini.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("DIAGNOSTIC", "MAYBE"), encoding="utf-8"
    )
    with pytest.raises(score.ScoreError, match="default_metric_status"):
        score.cmd_score(score_fixture, "mini-v1")


def test_scorecard_records_input_hashes_and_intervals(score_fixture: Path) -> None:
    score.cmd_score(score_fixture, "mini-v1")
    card = json.loads((score_fixture / "scorecard.json").read_text(encoding="utf-8"))
    assert set(card["inputs"]["pivot"]) == {"train/annotations.jsonl", "train/documents.jsonl"}
    assert set(card["inputs"]["run"]) == {"predictions.jsonl"}
    # Un seul document scoré : intervalle non défini, et dit comme tel.
    assert "reason" in card["diagnostic"]["span_f1"]["details"]["ci95"]


def test_dirty_tree_blocks_publication(score_fixture: Path) -> None:
    lock_path = score_fixture / "manifest.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["code"]["git_dirty"] = True
    lock_path.write_text(json.dumps(lock, sort_keys=True), encoding="utf-8")
    score.cmd_score(score_fixture, "mini-v1")
    card = json.loads((score_fixture / "scorecard.json").read_text(encoding="utf-8"))
    assert card["publishable"] is False
    assert any("non commitées" in reason for reason in card["publication_blockers"])


def test_failed_rescore_never_leaves_a_previous_scorecard(score_fixture: Path) -> None:
    """Une scorecard d'un score antérieur ne doit pas survivre à un score en échec.

    Sinon un appelant (campagne, humain) relit l'ancienne carte comme si elle
    décrivait les prédictions actuelles.
    """
    score.cmd_score(score_fixture, "mini-v1")
    assert (score_fixture / "scorecard.json").is_file()
    predictions = score_fixture / "predictions.jsonl"
    predictions.write_text(predictions.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(score.ScoreError, match="modifié après"):
        score.cmd_score(score_fixture, "mini-v1")
    assert not (score_fixture / "scorecard.json").exists()


def test_retired_judge_and_tasks_are_not_read_or_used_as_publication_blockers(score_fixture, monkeypatch):
    from anonymisation.llm.client import LlmClient

    rows = [json.loads(line) for line in (score_fixture / "predictions.jsonl").read_text().splitlines()]
    for row in rows:
        row.update(status="ok", error=[])
    _write_jsonl(score_fixture / "predictions.jsonl", rows)
    _relock_outputs(score_fixture)
    # Ces fichiers n'alimentent plus aucune mesure active, même s'ils existent.
    (score_fixture / "judge.lock.json").write_text("not JSON")
    (score_fixture / "judgments.jsonl").write_text("not JSON")
    (score.PROCESSED_ROOT / "mini" / "train" / "tasks.jsonl").write_text("not JSON")

    def forbidden(*args, **kwargs):
        raise AssertionError("appel modèle pendant score")

    monkeypatch.setattr(LlmClient, "complete", forbidden)
    assert score.cmd_score(score_fixture, "mini-v1") == 0
    card = json.loads((score_fixture / "scorecard.json").read_text())
    assert card["publishable"]
    assert "mean_utility" not in card["diagnostic"]
    assert "utility_retention" not in card["primary"]
    assert "train/tasks.jsonl" not in card["inputs"]["pivot"]


def test_retired_judge_command_is_not_exposed(capsys):
    from anonymisation.cli.main import main

    with pytest.raises(SystemExit) as exc:
        main(["judge", "--run", "unused"])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err

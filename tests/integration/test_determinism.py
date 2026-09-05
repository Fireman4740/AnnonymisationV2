"""Non-régression déterministe du pipeline (SPEC-04 §9, SPEC-09 §3.3)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from anonymisation.cli import predict, score
from anonymisation.cli.main import main
from anonymisation.datasets.registry import REGISTRY
from anonymisation.schema.io import read_jsonl
from anonymisation.schema.models import Document
from integration._micro import write_micro_pivot
from integration.test_ingest import _ingest

REPO_ROOT = Path(__file__).resolve().parents[2]
QUASIFR_CONFIG = REPO_ROOT / "configs" / "datasets" / "quasifr.yaml"
QUASIFR_PIVOT = REPO_ROOT / "data" / "processed" / "quasifr"


def _snapshot_jsonl(root: Path) -> dict[str, str]:
    """Empreintes des tables publiées, hors lock et rapport daté."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.jsonl"))
    }


def _dataset_param(name: str) -> Any:
    if name == "micro":
        return pytest.param(name, id=name)
    return pytest.param(name, id=name, marks=pytest.mark.requires_data)


def _quasifr_available() -> bool:
    return QUASIFR_CONFIG.is_file() and "quasifr" in REGISTRY and any(
        (QUASIFR_PIVOT / split / "documents.jsonl").is_file()
        for split in ("train", "dev", "test", "validation")
    )


def _predict_case(dataset: str, root: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    if dataset == "micro":
        write_micro_pivot(root)
        monkeypatch.setattr(predict, "PROCESSED_ROOT", root)
        return "micro-v1"
    if not _quasifr_available():
        pytest.skip("quasifr absent : installez le corpus v1 et son adaptateur")
    monkeypatch.setattr(predict, "PROCESSED_ROOT", REPO_ROOT / "data" / "processed")
    raw = yaml.safe_load(QUASIFR_CONFIG.read_text(encoding="utf-8"))
    return str(raw.get("evaluation", {}).get("protocol", "quasifr-v1"))


def _run_predict(dataset: str, root: Path, out: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    _predict_case(dataset, root, monkeypatch)
    return main(
        [
            "predict",
            "--dataset",
            dataset,
            "--split",
            "train",
            "--policy",
            "P2",
            "--profile",
            "deterministic",
            "--out",
            str(out),
            "--limit",
            "32",
        ]
    )


@pytest.mark.parametrize("dataset", [_dataset_param("micro"), _dataset_param("quasifr")])
def test_ingestion_tables_are_bit_identical(
    dataset: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deux ingestions successives gardent le même ordre et les mêmes octets."""
    if dataset == "micro":
        first = _ingest(tmp_path, output_root=tmp_path / "processed-1", limit=None)
        second = _ingest(tmp_path, output_root=tmp_path / "processed-2", limit=None)
        assert first.files == second.files
        return

    if not _quasifr_available():
        pytest.skip("quasifr absent : installez le corpus v1 et son adaptateur")
    snapshots: list[dict[str, str]] = []
    for index in (1, 2):
        output = tmp_path / f"processed-{index}"
        monkeypatch.setattr("anonymisation.cli.main.PROCESSED_ROOT", output)
        assert main(["datasets", "ingest", "quasifr", "--limit", "32"]) == 0
        snapshots.append(_snapshot_jsonl(output / "quasifr"))
    assert snapshots[0] == snapshots[1]


@pytest.mark.parametrize("dataset", [_dataset_param("micro"), _dataset_param("quasifr")])
def test_predictions_are_bit_identical(
    dataset: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deux prédictions strictes produisent le même ``predictions.jsonl``."""
    first = tmp_path / "run-1"
    second = tmp_path / "run-2"
    assert _run_predict(dataset, tmp_path / "processed", first, monkeypatch) in (0, 1)
    assert _run_predict(dataset, tmp_path / "processed", second, monkeypatch) in (0, 1)
    assert (first / "predictions.jsonl").read_bytes() == (second / "predictions.jsonl").read_bytes()


@pytest.mark.parametrize("dataset", [_dataset_param("micro"), _dataset_param("quasifr")])
def test_scorecards_are_identical_without_timestamp_fields(
    dataset: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le scoring rejoué ne dépend ni d'une horloge ni d'un nouvel appel modèle."""
    run = tmp_path / "run"
    protocol = _predict_case(dataset, tmp_path / "processed", monkeypatch)
    assert main(
        [
            "predict",
            "--dataset",
            dataset,
            "--split",
            "train",
            "--policy",
            "P2",
            "--profile",
            "deterministic",
            "--out",
            str(run),
            "--limit",
            "32",
        ]
    ) in (0, 1)
    if dataset == "micro":
        monkeypatch.setattr(score, "PROCESSED_ROOT", tmp_path / "processed")
    else:
        monkeypatch.setattr(score, "PROCESSED_ROOT", REPO_ROOT / "data" / "processed")
    monkeypatch.setattr(score, "DATASETS_CONFIG", REPO_ROOT / "configs" / "datasets")

    assert score.cmd_score(run, protocol) in (0, 1)
    first = (run / "scorecard.json").read_bytes()
    assert score.cmd_score(run, protocol) in (0, 1)
    second = (run / "scorecard.json").read_bytes()
    assert first == second


def test_unordered_set_control_fails_determinism_check() -> None:
    """Le contrôle échoue bien si une sérialisation parcourt un ``set`` brut."""
    script = "items = {f'item-{i}' for i in range(100)}; print('|'.join(items))"

    def unordered_output() -> str:
        seed = "1" if not hasattr(unordered_output, "called") else "2"
        unordered_output.called = True  # type: ignore[attr-defined]
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        return completed.stdout

    with pytest.raises(AssertionError, match="déterminisme"):
        first = unordered_output()
        second = unordered_output()
        assert first == second, "le contrôle de déterminisme doit détecter l'ordre du set"


def test_records_do_not_receive_processing_timestamps(tmp_path: Path) -> None:
    """Les horodatages de traitement restent dans le lock, jamais les tables."""
    result = _ingest(tmp_path, output_root=tmp_path / "processed")
    records = list(read_jsonl(result.lock_path.parent / "train" / "documents.jsonl", Document))
    assert records
    payload = json.loads((result.lock_path).read_text(encoding="utf-8"))
    assert "date" in payload
    assert all("processed_at" not in document.model_dump(mode="json") for document in records)
    assert all("created_at" not in document.model_dump(mode="json") for document in records)

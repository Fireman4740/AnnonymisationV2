"""Tests de la chaîne d'empreintes pivot → run → score (EPIC-H, reproductibilité)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from anonymisation.schema.integrity import (
    DataIntegrityError,
    locked_files,
    verify_pivot_files,
    verify_run_outputs,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def pivot(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "ds"
    (root / "test").mkdir(parents=True)
    docs = root / "test" / "documents.jsonl"
    anns = root / "test" / "annotations.jsonl"
    docs.write_text('{"doc_id": "d1"}\n', encoding="utf-8")
    anns.write_text('{"annotation_id": "a1"}\n', encoding="utf-8")
    return root, {"test/documents.jsonl": _sha(docs), "test/annotations.jsonl": _sha(anns)}


def test_untouched_pivot_is_verified(pivot: tuple[Path, dict[str, str]]) -> None:
    root, files = pivot
    verified = verify_pivot_files(
        root, "test", ("documents.jsonl", "annotations.jsonl", "tasks.jsonl"), files,
        context="t", required=("documents.jsonl",),
    )
    assert verified == dict(sorted(files.items()))


def test_modified_gold_is_refused(pivot: tuple[Path, dict[str, str]]) -> None:
    root, files = pivot
    (root / "test" / "annotations.jsonl").write_text('{"annotation_id": "a2"}\n', encoding="utf-8")
    with pytest.raises(DataIntegrityError, match="empreinte divergente"):
        verify_pivot_files(root, "test", ("annotations.jsonl",), files, context="t")


def test_unlocked_file_is_refused(pivot: tuple[Path, dict[str, str]]) -> None:
    root, files = pivot
    (root / "test" / "tasks.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(DataIntegrityError, match="pas verrouillé"):
        verify_pivot_files(root, "test", ("tasks.jsonl",), files, context="t")


def test_locked_but_missing_file_is_refused(pivot: tuple[Path, dict[str, str]]) -> None:
    root, files = pivot
    (root / "test" / "annotations.jsonl").unlink()
    with pytest.raises(DataIntegrityError, match="attendu absent"):
        verify_pivot_files(root, "test", ("annotations.jsonl",), files, context="t")


def test_lock_without_files_is_refused() -> None:
    with pytest.raises(DataIntegrityError, match="files"):
        locked_files({"source": "fixture"}, context="t")
    with pytest.raises(DataIntegrityError, match="data_version"):
        locked_files(None, context="t")


def test_edited_run_output_is_refused(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text('{"doc_id": "d1"}\n', encoding="utf-8")
    outputs = {"predictions.jsonl": _sha(predictions)}
    assert verify_run_outputs(tmp_path, outputs, ("predictions.jsonl",), context="t")
    predictions.write_text('{"doc_id": "d2"}\n', encoding="utf-8")
    with pytest.raises(DataIntegrityError, match="modifié après"):
        verify_run_outputs(tmp_path, outputs, ("predictions.jsonl",), context="t")
    with pytest.raises(DataIntegrityError, match="outputs"):
        verify_run_outputs(tmp_path, None, ("predictions.jsonl",), context="t")

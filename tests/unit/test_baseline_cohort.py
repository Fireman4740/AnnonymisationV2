"""Cohorte figée : conservation des octets, ordre, gold et absence de repli."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts/baseline_cohort.py"
_SPEC = importlib.util.spec_from_file_location("baseline_cohort", _PATH)
assert _SPEC and _SPEC.loader
cohort = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cohort)


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = {"datasets": {"mini": ["test"]}, "documents_per_dataset": 500,
           "cap_documents": True, "sampling_seed": 42, "max_document_chars": 16000,
           "conditional_evaluations": {}, "baseline": {"id": "fixed", "phase": "freeze",
               "manifest": "committed.lock.json", "snapshot_root": str(tmp_path / "cache")}}
    calls = []

    def prepare(key, splits, config, cache, rat):
        calls.append(key)
        root = tmp_path / "data/processed/mini"
        (root / "test").mkdir(parents=True)
        docs = [{"doc_id": "b", "text": "Deuxième"}, {"doc_id": "a", "text": "Premier"}]
        (root / "test/documents.jsonl").write_text("".join(json.dumps(d) + "\n" for d in docs))
        (root / "test/annotations.jsonl").write_text('{"annotation_id":"gold"}\n')
        (root / ".manifest.lock.json").write_text('{"taxonomy_version":"1.0"}\n')
        return {"dataset": key, "evaluation_documents": 2, "split_budget": {"test": 2},
                "evaluation_splits": ["test"], "selection": {"test": "not included"}}

    payload = cohort.freeze_cohort(cfg, prepare, tmp_path, tmp_path)
    Path(cfg["baseline"]["manifest"]).write_text(json.dumps(payload))
    cfg["baseline"]["phase"] = "evaluate"
    return cfg, payload, calls, prepare


def test_restore_is_identical_and_never_reselects(frozen):
    cfg, payload, calls, _ = frozen
    import shutil

    before = Path("data/processed/mini/test/documents.jsonl").read_bytes()
    shutil.rmtree("data/processed")
    restored = cohort.restore_cohort(cfg)
    assert restored["mini"]["evaluation_documents"] == 2
    assert Path("data/processed/mini/test/documents.jsonl").read_bytes() == before
    assert [d["doc_id"] for d in payload["datasets"]["mini"]["items"]["test"]] == ["b", "a"]
    assert calls == ["mini"]


def test_repeated_freeze_reuses_snapshot_without_preparing(frozen):
    cfg, payload, calls, prepare = frozen
    assert cohort.freeze_cohort(cfg, prepare, Path("."), Path(".")) == payload
    assert calls == ["mini"]


@pytest.mark.parametrize("changed", ["text", "gold", "missing", "manifest", "config", "extra"])
def test_modified_or_missing_inputs_fail_before_restoration(frozen, changed):
    cfg, _, _, _ = frozen
    root = cohort.snapshot_root(cfg)
    if changed == "text":
        (root / "processed/mini/test/documents.jsonl").write_text('{"doc_id":"b","text":"changed"}\n')
    elif changed == "gold":
        (root / "processed/mini/test/annotations.jsonl").write_text("changed")
    elif changed == "missing":
        (root / cohort.MANIFEST).unlink()
    elif changed == "manifest":
        Path(cfg["baseline"]["manifest"]).unlink()
    elif changed == "extra":
        (root / "processed/mini/unlocked.json").write_text("{}")
    else:
        cfg = copy.deepcopy(cfg)
        cfg["sampling_seed"] += 1
    with pytest.raises(ValueError):
        cohort.restore_cohort(cfg)


def test_evaluator_changes_preserve_the_frozen_cohort(frozen):
    cfg, _, calls, _ = frozen
    cfg["systems"] = [{"system": "new-model"}]
    assert cohort.restore_cohort(cfg)["mini"]["evaluation_documents"] == 2
    assert calls == ["mini"]

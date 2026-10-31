"""Sélection parmi les items figés : appartenance, textes, quotas et strates."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from anonymisation.cli.predict import PredictError, select_documents

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("subset_cohort", ROOT / "scripts/baseline_cohort.py")
cohort = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cohort)


def row(doc_id, text):
    return {"doc_id": doc_id, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}


def test_committed_5_subset_is_balanced_and_inside_the_50():
    cfg = json.loads((ROOT / "configs/evaluation/campaign.json").read_text())
    limits = cohort.evaluation_subset_limits(cfg)
    assert all(sum(v.values()) == 5 for v in limits.values())
    assert sum(map(lambda v: sum(v.values()), limits.values())) == 45
    subset = json.loads(Path(cfg["evaluation_subset"]["manifest"]).read_text())
    rat = subset["datasets"]["ratbench"]["eval"]
    assert [sum(r["doc_id"].startswith(f"ratbench:L{i}:") for r in rat) for i in (1, 2, 3)] == [2, 2, 1]
    spia = subset["datasets"]["spia"]["test"]
    assert sum(r["doc_id"].startswith("spia:TAB-") for r in spia) == 3
    assert sum(r["doc_id"].startswith("spia:PANORAMA-") for r in spia) == 2
    parent = json.loads((ROOT / "configs/evaluation/frozen/banc-fiable-200-v2-subset50.lock.json").read_text())
    for dataset, splits in subset["datasets"].items():
        for split, rows in splits.items():
            parent_ids = {row["doc_id"] for row in parent["datasets"][dataset][split]}
            assert all(row["doc_id"] in parent_ids for row in rows)


def test_selection_can_skip_first_rows_without_reordering_the_source(tmp_path):
    docs = [SimpleNamespace(doc_id=str(i), text=f"texte {i}") for i in range(6)]
    selected = [row(str(i), f"texte {i}") for i in (1, 4)]
    path = tmp_path / "selection.json"
    path.write_text(json.dumps({"datasets": {"mini": {"test": selected}}}))
    assert [d.doc_id for d in select_documents(docs, "mini", "test", path)] == ["1", "4"]
    assert [d.doc_id for d in docs] == [str(i) for i in range(6)]


@pytest.mark.parametrize("wrong", ["missing", "duplicate", "text", "order", "empty"])
def test_invalid_selection_fails_closed(tmp_path, wrong):
    docs = [SimpleNamespace(doc_id="a", text="alpha"), SimpleNamespace(doc_id="b", text="bêta")]
    rows = [row("a", "alpha"), row("b", "bêta")]
    if wrong == "missing":
        rows[0] = row("unknown", "alpha")
    elif wrong == "duplicate":
        rows = [rows[0], rows[0]]
    elif wrong == "text":
        rows[0] = row("a", "changed")
    elif wrong == "order":
        rows.reverse()
    else:
        rows = []
    path = tmp_path / "selection.json"
    path.write_text(json.dumps({"datasets": {"mini": {"test": rows}}}))
    with pytest.raises(PredictError):
        select_documents(docs, "mini", "test", path)


def test_tampered_committed_subset_is_rejected(tmp_path):
    cfg = json.loads((ROOT / "configs/evaluation/campaign.json").read_text())
    path = tmp_path / "changed.json"
    path.write_text("{}")
    cfg["evaluation_subset"]["manifest"] = str(path)
    with pytest.raises(ValueError, match="modifié"):
        cohort.evaluation_subset_limits(cfg)

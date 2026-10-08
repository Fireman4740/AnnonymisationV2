"""Les échantillons gardent le gold complet et les profils liés."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

_PATH = Path(__file__).resolve().parents[2] / "scripts/evaluation_campaign.py"
_SPEC = importlib.util.spec_from_file_location("evaluation_campaign", _PATH)
assert _SPEC and _SPEC.loader
campaign = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(campaign)


def test_sample_keeps_all_annotations_tasks_and_late_linked_profiles():
    selected = SimpleNamespace(doc_id="chosen", subject_ids=("subject",), author_id=None)
    source = SimpleNamespace(
        key="spia", manifest=None, raw_dir=Path("."),
        iter_annotations=lambda split: iter([
            SimpleNamespace(doc_id="other"),
            *[SimpleNamespace(doc_id="chosen", index=i) for i in range(9)],
        ]),
        iter_profiles=lambda split: iter([
            SimpleNamespace(person_id="other"), SimpleNamespace(person_id="subject"),
        ]),
        iter_tasks=lambda split: iter([
            SimpleNamespace(doc_id="other"), SimpleNamespace(doc_id="chosen"),
        ]),
    )
    sample = campaign.CompleteSample(source, {"test": [selected]}, {"test": {"chosen"}})
    assert len(list(sample.iter_annotations("test"))) == 9
    assert [p.person_id for p in sample.iter_profiles("test")] == ["subject"]
    assert [t.doc_id for t in sample.iter_tasks("test")] == ["chosen"]


def test_ratbench_sample_includes_each_difficulty_and_rejects_missing_level():
    import pytest

    docs = [SimpleNamespace(text="text", meta={"difficulty": level}) for level in (1, 1, 2, 3)]
    assert [d.meta["difficulty"] for d in campaign.choose(docs, "ratbench", 2, 8000)] == [1, 2, 3]
    with pytest.raises(ValueError, match="difficulty=3"):
        campaign.choose(docs[:-1], "ratbench", 2, 8000)

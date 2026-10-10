"""Les échantillons gardent le gold complet et les profils liés."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    sample = campaign.CompleteSample(source, {"test": [selected]})
    assert len(list(sample.iter_annotations("test"))) == 9
    assert [p.person_id for p in sample.iter_profiles("test")] == ["subject"]
    assert [t.doc_id for t in sample.iter_tasks("test")] == ["chosen"]


def _docs(field, groups):
    return [
        SimpleNamespace(doc_id=f"{group}-{i}", text="text", meta={field: group})
        for group in groups for i in range(100)
    ]


@pytest.mark.parametrize(("key", "field", "groups", "counts"), [
    ("ratbench", "difficulty", (1, 2, 3), (7, 7, 6)),
    ("spia", "source_corpus", ("tab", "panorama"), (10, 10)),
])
def test_twenty_exact_hash_bottom_k_order_independent(key, field, groups, counts):
    docs = _docs(field, groups)
    selected, report = campaign.choose(iter(docs), key, "test", 20, 8000, 42)
    other, other_report = campaign.choose(reversed(docs), key, "test", 20, 8000, 42)
    assert [d.doc_id for d in selected] == [d.doc_id for d in other]
    assert report == other_report
    assert len(selected) == len({d.doc_id for d in selected}) == 20
    for group, count in zip(groups, counts):
        expected = sorted(
            (d for d in docs if d.meta[field] == group),
            key=lambda d: hashlib.sha256(f"42\0{key}\0test\0{d.doc_id}".encode()).digest(),
        )[:count]
        assert [d.doc_id for d in selected if d.meta[field] == group] == [
            d.doc_id for d in expected
        ]


@pytest.mark.parametrize("count", [1, 2])
def test_ratbench_small_sample_zero_quotas(count):
    selected, report = campaign.choose(_docs("difficulty", (1, 2, 3)), "ratbench", "test", count, 8000, 42)
    assert len(selected) == report["selected"] == count
    assert report["strata"]["3"] == {"requested": 0, "available": 100, "selected": 0}


def test_ratbench_sample_rejects_missing_requested_stratum():
    with pytest.raises(ValueError, match="échantillon incomplet"):
        campaign.choose(_docs("difficulty", (1, 2)), "ratbench", "test", 3, 8000, 42)


def test_dataset_budget_redistributes_a_short_split_without_duplicates():
    available = {"anonymization": 31, "hard_quasi_id": 40, "max_anonymization": 1}
    assert campaign.split_budget(available, 20) == {
        "anonymization": 10, "hard_quasi_id": 9, "max_anonymization": 1,
    }
    with pytest.raises(ValueError, match="incomplet"):
        campaign.split_budget({"small": 1}, 20)


def test_dataset_budget_can_leave_a_split_empty_explicitly():
    assert campaign.split_budget({"empty": 0, "full": 20}, 20) == {"empty": 0, "full": 20}

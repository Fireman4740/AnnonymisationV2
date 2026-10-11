"""Évaluateur TAB ORIGINAL appelé tel quel (EPIC-H H-8)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

pytest.importorskip("en_core_web_md", reason="extra `tab_eval` requis")

from anonymisation.metrics.tab_official import evaluate_tab, masked_spans  # noqa: E402

TEXT = "Mr John Smith lives in Oslo. John Smith works at Acme."


def _mention(start: int, end: int, entity_id: str, identifier: str, entity_type: str) -> dict:
    return {"entity_type": entity_type, "entity_mention_id": f"{entity_id}_{start}",
            "start_offset": start, "end_offset": end, "span_text": TEXT[start:end],
            "edit_type": "check", "identifier_type": identifier, "entity_id": entity_id,
            "confidential_status": "NOT_CONFIDENTIAL"}


def _record() -> dict:
    # Deux annotateurs en désaccord sur « Oslo » : l'original micro-moyenne.
    annotator_a = [_mention(3, 13, "e1", "DIRECT", "PERSON"),
                   _mention(29, 39, "e1", "DIRECT", "PERSON"),
                   _mention(23, 27, "e2", "QUASI", "LOC")]
    annotator_b = [_mention(3, 13, "b_e1", "DIRECT", "PERSON"),
                   _mention(29, 39, "b_e1", "DIRECT", "PERSON")]
    return {"doc_id": "001-1", "text": TEXT, "dataset_type": "test", "task": "x", "meta": {},
            "annotations": {"ann1": {"entity_mentions": annotator_a},
                            "ann2": {"entity_mentions": annotator_b}}}


def test_vendored_evaluator_is_the_unmodified_original():
    path = Path(__file__).resolve().parents[2] / "src/anonymisation/metrics/vendor/tab_evaluation.py"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    declared = lines[2].split(":")[1].strip()
    body_start = next(i for i, line in enumerate(lines) if line.startswith("import json"))
    assert hashlib.sha256("".join(lines[body_start:]).encode()).hexdigest() == declared


def test_entity_recall_requires_every_mention_and_keep_is_not_a_mask():
    decisions = [{"start": 3, "end": 13, "action": "SUPPRESS"},
                 {"start": 29, "end": 39, "action": "KEEP"},
                 {"start": 23, "end": 27, "action": "GENERALIZE"}]
    result = evaluate_tab([_record()], {"001-1": masked_spans(decisions)})
    measures = result["measures"]
    assert measures["recall_direct_entities"] == 0.0  # 2e mention de John Smith gardée
    assert measures["recall_quasi_entities"] == 1.0
    assert result["use_bert"] is False


def test_all_mentions_masked_gives_full_entity_recall():
    spans = [(3, 13), (29, 39), (23, 27)]
    measures = evaluate_tab([_record()], {"001-1": spans})["measures"]
    assert measures["recall_direct_entities"] == 1.0
    assert measures["recall_all_entities"] == 1.0

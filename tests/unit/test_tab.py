"""Tests de l'adaptateur TAB officiel et de l'union multi-annotateurs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from anonymisation.datasets.ingest import IngestionError
from anonymisation.datasets.manifest import DatasetManifest, load_manifest
from anonymisation.datasets.registry import resolve
from anonymisation.datasets.tab import TabAdapter
from anonymisation.schema.taxonomy import IdentifierType, Sensitivity

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "configs" / "datasets" / "tab.yaml"


def _mention(
    text: str,
    entity_type: str,
    start: int,
    end: int,
    identifier_type: str,
    entity_id: str,
    status: str = "NOT_CONFIDENTIAL",
    suffix: str = "1",
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_mention_id": f"m-{suffix}",
        "start_offset": start,
        "end_offset": end,
        "span_text": text[start:end],
        "edit_type": "check",
        "identifier_type": identifier_type,
        "entity_id": entity_id,
        "confidential_status": status,
    }


def _record(*, bad_offset: bool = False) -> dict[str, Any]:
    text = "Alice works at Acme in 2024."
    alice_start = text.index("Alice")
    acme_start = text.index("Acme")
    date_start = text.index("2024")
    person = _mention(text, "PERSON", alice_start, alice_start + 5, "DIRECT", "p1")
    duplicate_person = _mention(
        text, "PERSON", alice_start, alice_start + 5, "QUASI", "p1b", suffix="2"
    )
    org = _mention(text, "ORG", acme_start, acme_start + 4, "QUASI", "o1", suffix="3")
    no_mask = _mention(
        text, "DATETIME", date_start, date_start + 4, "NO_MASK", "d1", suffix="4"
    )
    if bad_offset:
        org["end_offset"] = org["end_offset"] + 1
    return {
        "doc_id": "001",
        "text": text,
        "annotations": {
            "annotator2": {"entity_mentions": [duplicate_person, no_mask]},
            "annotator1": {"entity_mentions": [person, org]},
        },
        "meta": {"year": 2020, "countries": "FRA"},
        "task": "Task: anonymise Alice",
        "quality_checked": ["annotator1"],
        "dataset_type": "train",
    }


def _adapter(tmp_path: Path, *, bad_offset: bool = False) -> TabAdapter:
    raw = tmp_path / "tab"
    raw.mkdir()
    records = {"train": [_record(bad_offset=bad_offset)], "dev": [], "test": []}
    for split, rows in records.items():
        (raw / f"echr_{split}.json").write_text(
            json.dumps(rows, ensure_ascii=False), encoding="utf-8"
        )
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    data["source"] = {
        "kind": "local",
        "path": str(raw),
        "files": ["echr_train.json", "echr_dev.json", "echr_test.json"],
    }
    data["integrity"]["sha256"] = None
    data["integrity"]["expected_documents"] = 1
    data["integrity"]["expected_profiles"] = 0
    return TabAdapter(DatasetManifest.model_validate(data), raw)


def test_repo_manifest_and_registry() -> None:
    loaded = load_manifest(MANIFEST_PATH, resolve_source=False)
    assert loaded.manifest.key == "tab"
    assert loaded.manifest.integrity.expected_documents == 1268
    assert loaded.manifest.structure.splits == ["train", "dev", "test"]
    assert resolve("tab") is TabAdapter
    assert resolve("text-anonymization-benchmark") is TabAdapter


def test_union_keeps_offsets_coreference_and_no_mask_audit(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    docs = list(adapter.iter_documents("train"))
    anns = list(adapter.iter_annotations("train"))

    assert len(docs) == 1
    assert len(anns) == 2  # PERSON duplicate collapsed; NO_MASK excluded
    assert docs[0].meta["official_aggregation"] == "union"
    assert docs[0].meta["annotator_ids"] == ["annotator1", "annotator2"]
    assert docs[0].meta["excluded_no_mask_total"] == 1
    assert docs[0].meta["union_collapsed_duplicates"] == 1
    assert all(annotation.start is not None for annotation in anns)
    assert all(annotation.span_text == docs[0].text[annotation.start : annotation.end] for annotation in anns)

    person = next(annotation for annotation in anns if annotation.meta["source_entity_type"] == "PERSON")
    assert person.identifier_type is IdentifierType.DIRECT
    assert person.entity_id == "tab:train:001:annotator1:p1"
    assert person.meta["source_annotators"] == ["annotator1", "annotator2"]

    org = next(annotation for annotation in anns if annotation.meta["source_entity_type"] == "ORG")
    assert org.identifier_type is IdentifierType.QUASI
    assert org.sensitivity is Sensitivity.NONE


def test_direct_semantic_type_is_adjusted_explicitly(tmp_path: Path) -> None:
    raw = tmp_path / "tab"
    adapter = _adapter(tmp_path)
    record = _record()
    text = record["text"]
    start = text.index("Acme")
    record["annotations"]["annotator1"]["entity_mentions"].append(
        _mention(text, "MISC", start, start + 4, "DIRECT", "misc1", suffix="5")
    )
    (raw / "echr_train.json").write_text(json.dumps([record]), encoding="utf-8")
    anns = list(adapter.iter_annotations("train"))
    misc = next(annotation for annotation in anns if annotation.meta["source_entity_type"] == "MISC")
    assert misc.identifier_type is IdentifierType.QUASI
    assert misc.meta["identifier_type_adjusted"]["source"] == "DIRECT"


def test_bad_offsets_are_blocking(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, bad_offset=True)
    with pytest.raises(IngestionError, match="offsets incohérents"):
        list(adapter.iter_annotations("train"))

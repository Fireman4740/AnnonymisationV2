"""Tests de l'adaptateur QUASIFR sans dépendre du corpus V1 réel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from anonymisation.datasets.manifest import DatasetManifest, load_manifest
from anonymisation.datasets.quasifr import QuasifrAdapter
from anonymisation.datasets.registry import UnmappedLabelError, resolve
from anonymisation.schema.taxonomy import IdentifierType

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "configs" / "datasets" / "quasifr.yaml"
FILES = (
    "anonymization_dataset.json",
    "hard_quasi_id_dataset.json",
    "max_anonymization_dataset.json",
)


def _example(example_id: str, *, ambiguous: bool = False) -> dict[str, Any]:
    text = "Alice vit a Paris en 2024. Alice."
    annotations: list[dict[str, Any]] = [
        {
            "type": "PER",
            "start": 0,
            "end": 5,
            "text": "Alice",
            "replacement": "[PER_A]",
            "coref_id": "person_1",
            "risk_note": None,
        },
        {
            "type": "LOC",
            "start": text.index("Paris"),
            "end": text.index("Paris") + len("Paris"),
            "text": "Paris",
            "replacement": "[LOC_A]",
            "coref_id": None,
            "risk_note": "ville",
        },
        {
            "type": "DATE",
            "start": 0,
            "end": 4,
            "text": "2024",
            "replacement": "[DATE_A]",
            "coref_id": "event_1",
            "risk_note": None,
        },
        {
            "type": "COREF",
            "start": text.rindex("Alice"),
            "end": text.rindex("Alice") + 5,
            "text": "Alice",
            "replacement": "[PER_A]",
            "coref_id": "person_1",
            "risk_note": "coréférence",
        },
    ]
    if ambiguous:
        annotations.append(
            {
                "type": "QUASI_ID",
                "start": 1,
                "end": 4,
                "text": "Alice",
                "replacement": "[QUASI_A]",
                "coref_id": "person_1",
                "risk_note": "description unique",
            }
        )
    return {
        "id": example_id,
        "langue": "FR",
        "original_text": text,
        "anonymized_text": "[PER_A] vit a [LOC_A] en [DATE_A]. [PER_A].",
        "annotations": annotations,
        "niveau_anonymisation": "L3",
        "risk_score": 42,
    }


def _adapter(tmp_path: Path, *, ambiguous: bool = False) -> QuasifrAdapter:
    raw = tmp_path / "quasifr"
    raw.mkdir()
    payloads = {
        "anonymization_dataset.json": {"examples": [_example("ticket_001", ambiguous=ambiguous)]},
        "hard_quasi_id_dataset.json": {"examples": [_example("hard_001")]},
        "max_anonymization_dataset.json": {"examples": []},
    }
    for filename, payload in payloads.items():
        (raw / filename).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    data["source"] = {
        "kind": "local",
        "path": str(raw),
        "files": list(FILES),
    }
    data["integrity"]["expected_documents"] = 2
    data["integrity"]["expected_profiles"] = 0
    manifest = DatasetManifest.model_validate(data)
    return QuasifrAdapter(manifest, raw)


def test_repo_manifest_and_registry() -> None:
    loaded = load_manifest(MANIFEST_PATH, resolve_source=False)
    assert loaded.manifest.key == "quasifr"
    assert loaded.manifest.integrity.expected_documents == 72
    assert len(loaded.manifest.label_map) == 35
    assert resolve("quasifr") is QuasifrAdapter
    assert resolve("quasi-fr") is QuasifrAdapter


def test_documents_annotations_and_unique_reanchor(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    docs = list(adapter.iter_documents("anonymization"))
    anns = list(adapter.iter_annotations("anonymization"))

    assert docs[0].doc_id == "quasifr:anonymization:ticket_001"
    assert docs[0].language == "fr"
    assert len(anns) == 4
    date = next(annotation for annotation in anns if annotation.meta["source_type"] == "DATE")
    assert date.span_text == "2024"
    assert date.meta["offset_repaired"] is True
    coref = next(annotation for annotation in anns if annotation.meta["source_type"] == "COREF")
    assert coref.identifier_type is IdentifierType.IGNORED
    assert coref.entity_id == "person_1"
    assert docs[0].meta["repaired_offsets"][0]["type"] == "DATE"


def test_ambiguous_offset_is_recorded_and_not_guessed(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, ambiguous=True)
    docs = list(adapter.iter_documents("anonymization"))
    anns = list(adapter.iter_annotations("anonymization"))

    assert len(anns) == 4
    dropped = docs[0].meta["dropped_annotations"]
    assert len(dropped) == 1
    assert dropped[0]["reason"] == "texte présent plusieurs fois"
    assert dropped[0]["type"] == "QUASI_ID"


def test_download_reports_local_fingerprint(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    report = adapter.download()
    assert report.dataset == "quasifr"
    assert report.from_cache is True
    assert report.bytes_downloaded == 0
    assert len(report.sha256) == 64


def test_unknown_label_is_blocking(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    path = tmp_path / "quasifr" / "anonymization_dataset.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["examples"][0]["annotations"][0]["type"] = "UNKNOWN"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(UnmappedLabelError):
        list(adapter.iter_annotations("anonymization"))

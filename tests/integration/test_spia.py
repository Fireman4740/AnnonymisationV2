"""Integration du format SPIA et du pivot multi-sujets (ticket G-1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anonymisation.datasets.manifest import DatasetManifest
from anonymisation.datasets.spia import SpiaAdapter
from anonymisation.schema.models import Document
from anonymisation.schema.validation import validate_dataset


def _manifest() -> DatasetManifest:
    return DatasetManifest.model_validate(
        {
            "key": "spia",
            "name": "SPIA fixture",
            "description": "fixture",
            "doc": "fixture",
            "source": {
                "kind": "local",
                "path": "/tmp/spia-fixture",
                "files": ["spia_tab_144.jsonl", "spia_panorama_531.jsonl"],
            },
            "license": {"spdx": "MIT AND CC-BY-4.0"},
            "integrity": {
                "sha256": None,
                "expected_documents": 2,
                "expected_profiles": 3,
            },
            "structure": {
                "domain": "generic",
                "languages": ["en"],
                "synthetic": False,
                "has_profiles": True,
                "has_combinations": False,
                "has_organizations": False,
                "has_tasks": False,
                "split_by": "subject_id",
                "splits": ["test"],
            },
            "label_map": {
                "NAME": {
                    "identifier_type": "DIRECT",
                    "qi_categories": ["DIR_NAME"],
                    "granularity": "EXACT",
                    "stability": "STABLE",
                },
                "AGE": {
                    "identifier_type": "QUASI",
                    "qi_categories": ["GEN_AGE"],
                    "granularity": "EXACT",
                    "stability": "STABLE",
                },
                "EMAIL": {
                    "identifier_type": "DIRECT",
                    "qi_categories": ["DIR_EMAIL"],
                    "granularity": "EXACT",
                    "stability": "VOLATILE",
                },
            },
            "evaluation": {
                "protocol": "spia-fixture",
                "protocol_version": "1",
                "official_eligible": False,
                "default_metric_status": "DIAGNOSTIC",
                "granularities": ["subject"],
                "report_by": ["source_corpus"],
            },
            "population": {"population_id": None, "k_computable": False},
        }
    )


def _write_fixture(root: Path) -> None:
    root.mkdir(exist_ok=True)
    tab = {
        "metadata": {"data_id": "TAB-1", "number_of_subjects": 2},
        "text": "Alice is 30 and Bob uses bob@example.com.",
        "subjects": [
            {
                "id": 0,
                "description": "applicant Alice",
                "PIIs": [
                    {"tag": "NAME", "keyword": "Alice", "certainty": 5, "hardness": 1},
                    {"tag": "AGE", "keyword": "30", "certainty": 4, "hardness": 2},
                ],
            },
            {
                "id": 1,
                "description": "third party Bob",
                "PIIs": [
                    {
                        "tag": "EMAIL",
                        "keyword": "bob@example.com",
                        "certainty": 5,
                        "hardness": 1,
                    }
                ],
            },
        ],
    }
    panorama = {
        "metadata": {"data_id": "PANORAMA-1", "number_of_subjects": 1},
        "text": "Carol is 40.",
        "subjects": [
            {
                "id": 7,
                "description": "author Carol",
                "PIIs": [{"tag": "NAME", "keyword": "Carol", "certainty": 5, "hardness": 1}],
            }
        ],
    }
    (root / "spia_tab_144.jsonl").write_text(json.dumps(tab) + "\n", encoding="utf-8")
    (root / "spia_panorama_531.jsonl").write_text(
        json.dumps(panorama) + "\n", encoding="utf-8"
    )


def test_spia_preserves_subject_links_offsets_and_tab_overlap(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    adapter = SpiaAdapter(_manifest(), tmp_path)

    documents = list(adapter.iter_documents("test"))
    annotations = list(adapter.iter_annotations("test"))
    profiles = list(adapter.iter_profiles("test"))

    assert len(documents) == 2
    first = documents[0]
    assert first.subject_ids == (
        "spia:TAB-1:subject:0",
        "spia:TAB-1:subject:1",
    )
    assert first.meta["tab_overlap"] is True
    assert len({profile.person_id for profile in profiles}) == 3
    assert {annotation.subject_id for annotation in annotations} == set(
        first.subject_ids
    ) | {"spia:PANORAMA-1:subject:7"}

    docs_by_id: dict[str, Document] = {document.doc_id: document for document in documents}
    for annotation in annotations:
        document = docs_by_id[annotation.doc_id]
        assert annotation.subject_id in document.subject_ids
        assert document.text[annotation.start : annotation.end] == annotation.span_text

    report = validate_dataset(
        "spia",
        documents,
        annotations,
        profiles,
        expected_documents=2,
    )
    assert report.errors() == ()
    assert adapter.overlap_tab_ids() == ("spia:TAB-1",)


def test_spia_manifest_exposes_all_fifteen_source_labels() -> None:
    manifest_path = Path(__file__).resolve().parents[2] / "configs" / "datasets" / "spia.yaml"
    payload: dict[str, Any]
    import yaml

    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert len(payload["label_map"]) == 15
    assert all(payload["label_map"].values())

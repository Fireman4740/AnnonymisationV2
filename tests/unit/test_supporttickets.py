"""Tests unitaires ciblés pour SupportTicketsReal et BitextSupportSynthetic."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from anonymisation.datasets.bitextsupport import BitextSupportAdapter
from anonymisation.datasets.ingest import IngestionError
from anonymisation.datasets.manifest import load_manifest
from anonymisation.datasets.supporttickets import SupportTicketsAdapter


def test_supporttickets_adapter_nominal_and_malformed(tmp_path: Path):
    data_dir = tmp_path / "SupportTicketsReal"
    data_dir.mkdir()
    parquet_path = data_dir / "train.parquet"

    # Schema nominal
    cols = [
        "subject", "body", "answer", "type", "queue", "priority",
        "language", "version", "tag_1", "tag_2", "tag_3", "tag_4",
        "tag_5", "tag_6", "tag_7", "tag_8"
    ]
    arrays = [pa.array(["Sujet 1"])] + [pa.array(["Contenu 1"])] * (len(cols) - 1)
    table = pa.Table.from_arrays(arrays, names=cols)
    pq.write_table(table, parquet_path)

    manifest_yaml = tmp_path / "manifest.yaml"
    manifest_yaml.write_text(f"""
key: supporttickets
name: SupportTicketsReal
description: test
doc: doc.md
source:
  kind: local
  path: "{data_dir.as_posix()}"
  files: ["train.parquet"]
license:
  spdx: UNKNOWN
  redistribution: false
  restricted: true
integrity:
  sha256: null
  expected_documents: 1
  expected_profiles: 0
structure:
  domain: support
  languages: ["fr"]
  synthetic: false
  has_profiles: false
  has_combinations: false
  has_organizations: false
  has_tasks: true
  split_by: document
  splits: ["train", "dev", "test"]
evaluation:
  protocol: proto
  protocol_version: "1"
  official_eligible: false
  default_metric_status: DIAGNOSTIC
  granularities: [document]
  report_by: []
  gold_scope:
    exhaustive: true
    reason: "fixture de test"
population:
  population_id: null
  k_computable: false
""", encoding="utf-8")

    manifest = load_manifest(manifest_yaml).manifest
    adapter = SupportTicketsAdapter(manifest, tmp_path / "raw")

    # Nominal
    docs = list(adapter.iter_documents("train")) + list(adapter.iter_documents("dev")) + list(adapter.iter_documents("test"))
    assert len(docs) == 1
    doc = docs[0]
    assert doc.domain.value == "support"
    assert "Sujet 1" in doc.text

    tasks = list(adapter.iter_tasks(doc.split))
    assert len(tasks) == 3
    assert {t.task for t in tasks} == {"ticket_routing", "ticket_priority", "ticket_type"}

    # Malformé : colonne manquante
    bad_table = pa.Table.from_arrays([pa.array(["Sujet 1"])], names=["subject"])
    pq.write_table(bad_table, parquet_path)
    adapter_bad = SupportTicketsAdapter(manifest, tmp_path / "raw")
    with pytest.raises(IngestionError, match="colonnes manquantes"):
        list(adapter_bad.iter_documents("train"))


def test_bitextsupport_adapter_nominal(tmp_path: Path):
    data_dir = tmp_path / "BitextSupportSynthetic"
    data_dir.mkdir()
    parquet_path = data_dir / "train.parquet"

    cols = ["instruction", "category", "intent", "response", "flags"]
    arrays = [
        pa.array(["cancel my order"]),
        pa.array(["ORDER"]),
        pa.array(["cancel_order"]),
        pa.array(["I can help with that."]),
        pa.array(["B"]),
    ]
    table = pa.Table.from_arrays(arrays, names=cols)
    pq.write_table(table, parquet_path)

    manifest_yaml = tmp_path / "manifest.yaml"
    manifest_yaml.write_text(f"""
key: bitextsupport
name: BitextSupportSynthetic
description: test
doc: doc.md
source:
  kind: local
  path: "{data_dir.as_posix()}"
  files: ["train.parquet"]
license:
  spdx: UNKNOWN
  redistribution: false
  restricted: true
integrity:
  sha256: null
  expected_documents: 1
  expected_profiles: 0
structure:
  domain: support
  languages: ["en"]
  synthetic: true
  has_profiles: false
  has_combinations: false
  has_organizations: false
  has_tasks: true
  split_by: document
  splits: ["train", "dev", "test"]
evaluation:
  protocol: proto
  protocol_version: "1"
  official_eligible: false
  default_metric_status: DIAGNOSTIC
  granularities: [document]
  report_by: []
  gold_scope:
    exhaustive: true
    reason: "fixture de test"
population:
  population_id: null
  k_computable: false
""", encoding="utf-8")

    manifest = load_manifest(manifest_yaml).manifest
    adapter = BitextSupportAdapter(manifest, tmp_path / "raw")

    docs = list(adapter.iter_documents("train")) + list(adapter.iter_documents("dev")) + list(adapter.iter_documents("test"))
    assert len(docs) == 1
    doc = docs[0]
    assert doc.text == "cancel my order"
    assert doc.meta["response"] == "I can help with that."

    tasks = list(adapter.iter_tasks(doc.split))
    assert len(tasks) == 2
    assert {t.task for t in tasks} == {"intent", "category"}

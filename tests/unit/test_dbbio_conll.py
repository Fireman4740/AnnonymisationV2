"""Tests unitaires ciblés pour DB-bio et CoNLL-2003."""

from __future__ import annotations

import json
from pathlib import Path

from anonymisation.datasets.conll2003 import Conll2003Adapter
from anonymisation.datasets.dbbio import DbbioAdapter
from anonymisation.datasets.manifest import load_manifest


def test_dbbio_adapter_nominal_and_tasks(tmp_path: Path):
    data_dir = tmp_path / "DB-bio"
    data_dir.mkdir()
    train_file = data_dir / "train.jsonl"
    val_file = data_dir / "val.jsonl"
    test_file = data_dir / "test.jsonl"

    row = {
        "text": "Geoffrey Harber Diggle was a British chess player.",
        "l1": "Agent",
        "l2": "Athlete",
        "l3": "ChessPlayer",
        "wiki_name": "G._H._Diggle",
        "people": "Geoffrey Harber Diggle",
        "word_count": 8,
        "label": "Chess Player",
    }
    line = json.dumps(row) + "\n"
    train_file.write_text(line, encoding="utf-8")
    val_file.write_text(line, encoding="utf-8")
    test_file.write_text(line, encoding="utf-8")

    manifest_yaml = tmp_path / "manifest.yaml"
    manifest_yaml.write_text(f"""
key: dbbio
name: DB-bio
description: test
doc: doc.md
source:
  kind: local
  path: "{data_dir.as_posix()}"
  files: ["train.jsonl", "val.jsonl", "test.jsonl"]
license:
  spdx: CC-BY-SA-3.0
  redistribution: true
  restricted: false
integrity:
  sha256: null
  expected_documents: 1
  expected_profiles: 0
structure:
  domain: generic
  languages: ["en"]
  synthetic: false
  has_profiles: false
  has_combinations: false
  has_organizations: false
  has_tasks: true
  split_by: document
  splits: ["train", "val", "test"]
evaluation:
  protocol: proto
  protocol_version: "1"
  official_eligible: false
  default_metric_status: DIAGNOSTIC
  granularities: [document]
  report_by: []
population:
  population_id: null
  k_computable: false
""", encoding="utf-8")

    manifest = load_manifest(manifest_yaml).manifest
    adapter = DbbioAdapter(manifest, tmp_path / "raw")

    docs = list(adapter.iter_documents("train"))
    assert len(docs) == 1
    assert "Geoffrey Harber Diggle" in docs[0].text

    anns = list(adapter.iter_annotations("train"))
    assert len(anns) >= 1
    # Le nom est localisé
    name_ann = anns[0]
    assert name_ann.start is not None
    assert docs[0].text[name_ann.start : name_ann.end] == "Geoffrey Harber Diggle"

    tasks = list(adapter.iter_tasks("train"))
    assert len(tasks) == 3
    task_map = {t.task: t.label for t in tasks}
    assert task_map == {
        "occupation_l1": "Agent",
        "occupation_l2": "Athlete",
        "occupation_l3": "ChessPlayer",
    }


def test_conll2003_adapter_nominal_and_mapping(tmp_path: Path):
    data_dir = tmp_path / "conll03"
    data_dir.mkdir()
    train_file = data_dir / "train.txt"
    val_file = data_dir / "valid.txt"
    test_file = data_dir / "test.txt"

    conll_text = """-DOCSTART- -X- -X- O

EU NNP B-NP B-ORG
rejects VBZ B-VP O
German JJ B-NP B-MISC
lamb NN I-NP O
. . O O

Peter NNP B-NP B-PER
Blackburn NNP I-NP I-PER
in IN B-PP O
Brussels NNP B-NP B-LOC
. . O O
"""
    train_file.write_text(conll_text, encoding="utf-8")
    val_file.write_text(conll_text, encoding="utf-8")
    test_file.write_text(conll_text, encoding="utf-8")

    manifest_yaml = tmp_path / "manifest.yaml"
    manifest_yaml.write_text(f"""
key: conll2003
name: CoNLL-2003
description: test
doc: doc.md
source:
  kind: local
  path: "{data_dir.as_posix()}"
  files: ["train.txt", "valid.txt", "test.txt"]
license:
  spdx: UNKNOWN
  restricted: true
integrity:
  sha256: null
  expected_documents: 2
  expected_profiles: 0
structure:
  domain: generic
  languages: ["en"]
  synthetic: false
  has_profiles: false
  has_combinations: false
  has_organizations: false
  has_tasks: false
  split_by: document
  splits: ["train", "dev", "test"]
evaluation:
  protocol: proto
  protocol_version: "1"
  official_eligible: false
  default_metric_status: DIAGNOSTIC
  granularities: [document]
  report_by: []
population:
  population_id: null
  k_computable: false
""", encoding="utf-8")

    manifest = load_manifest(manifest_yaml).manifest
    adapter = Conll2003Adapter(manifest, tmp_path / "raw")

    docs = list(adapter.iter_documents("train"))
    assert len(docs) == 2  # 2 phrases
    doc1, doc2 = docs

    assert doc1.text == "EU rejects German lamb ."
    assert doc2.text == "Peter Blackburn in Brussels ."

    anns1 = list(adapter.iter_annotations("train"))
    # Vérifier que les spans réfèrent exactement au texte
    # Phrase 1: EU -> B-ORG -> GEN_AFFILIATION, German -> B-MISC -> IGNORED
    # Phrase 2: Peter Blackburn -> B-PER/I-PER -> DIR_NAME, Brussels -> B-LOC -> GEN_GEO
    assert len(anns1) == 4
    per_ann = next(a for a in anns1 if a.qi_categories == ("DIR_NAME",))
    assert per_ann.span_text == "Peter Blackburn"
    assert doc2.text[per_ann.start : per_ann.end] == "Peter Blackburn"

    loc_ann = next(a for a in anns1 if a.qi_categories == ("GEN_GEO",))
    assert loc_ann.span_text == "Brussels"
    assert doc2.text[loc_ann.start : loc_ann.end] == "Brussels"

    org_ann = next(a for a in anns1 if a.qi_categories == ("GEN_AFFILIATION",))
    assert org_ann.span_text == "EU"
    assert doc1.text[org_ann.start : org_ann.end] == "EU"

    misc_ann = next(a for a in anns1 if a.qi_categories == ("IGNORED",))
    assert misc_ann.span_text == "German"
    assert doc1.text[misc_ann.start : misc_ann.end] == "German"

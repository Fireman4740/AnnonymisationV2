"""Tests unitaires ciblés pour RAT-Bench."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from anonymisation.datasets.manifest import load_manifest
from anonymisation.datasets.ratbench import RatBenchAdapter


def test_ratbench_adapter_nominal_and_implicit_annotations(tmp_path: Path):
    data_dir = tmp_path / "RAT-Bench"
    data_dir.mkdir()
    jsonl_path = data_dir / "english.jsonl"
    cache_dir = data_dir / "cache"
    cache_dir.mkdir()
    pums_path = cache_dir / "pums_population.parquet"

    # Créer pums parquet
    schema = pa.schema([
        ("SERIALNO", pa.string()),
        ("PWGTP", pa.int64()),
        ("sex", pa.string()),
        ("citizenship status", pa.string()),
    ])
    table = pa.Table.from_arrays(
        [
            pa.array(["1"]),
            pa.array([42]),
            pa.array(["Male"]),
            pa.array(["Born in the US"]),
        ],
        schema=schema,
    )
    pq.write_table(table, pums_path)

    # Créer jsonl avec un direct présent et un direct absent
    row = {
        "id": 0,
        "text": "Hello, my email is john.doe@example.com but no phone is mentioned.",
        "difficulty": 1,
        "scenario": "interview",
        "features": ["email", "phone number", "CIT", "SEX"],
        "direct_identifiers": {
            "email": "john.doe@example.com",
            "phone number": "0102030405",  # non localisé -> IMPLICIT
        },
        "indirect_identifiers": {
            "CIT": "Born in the US",
            "SEX": "Male",
        },
        "profile": {"name": "John"},
    }
    jsonl_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    manifest_yaml = tmp_path / "manifest.yaml"
    manifest_yaml.write_text(f"""
key: ratbench
name: RAT-Bench
description: test
doc: doc.md
source:
  kind: local
  path: "{data_dir.as_posix()}"
  files: ["english.jsonl", "cache/pums_population.parquet"]
license:
  spdx: UNKNOWN
  redistribution: false
  restricted: true
integrity:
  sha256: null
  expected_documents: 1
  expected_profiles: 0
structure:
  domain: generic
  languages: ["en"]
  synthetic: true
  has_profiles: false
  has_combinations: true
  has_organizations: false
  has_tasks: false
  split_by: document
  splits: ["eval"]
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
  population_id: "ratbench-us"
  k_computable: true
""", encoding="utf-8")

    manifest = load_manifest(manifest_yaml).manifest
    adapter = RatBenchAdapter(manifest, tmp_path / "raw")

    docs = list(adapter.iter_documents("eval"))
    assert len(docs) == 1
    assert docs[0].doc_id == "ratbench:L1:0"

    anns = list(adapter.iter_annotations("eval"))
    assert len(anns) >= 2
    # L'email est localisé
    email_ann = next(a for a in anns if a.meta.get("source_key") == "email")
    assert email_ann.start is not None
    assert docs[0].text[email_ann.start : email_ann.end] == "john.doe@example.com"

    # Le téléphone n'est pas localisé -> mode IMPLICIT
    phone_ann = next(a for a in anns if a.meta.get("source_key") == "phone number")
    assert phone_ann.expression_mode.value.upper() == "IMPLICIT"
    # Pas de combinaison k : le risque RAT-Bench est CorrectMatch, à l'attaque.
    assert list(adapter.iter_combinations("eval")) == []
    # Profil gold complet, réservé à l'attaque figée.
    (profile,) = adapter.iter_profiles("eval")
    assert profile.person_id == "ratbench:L1:0"
    assert profile.meta["direct_identifiers"]["email"] == "john.doe@example.com"
    assert profile.meta["indirect_identifiers"]["SEX"] == "Male"
    assert profile.meta["scenario"] == "interview"


def test_find_occurrences_is_word_bounded_and_exhaustive():
    """Correctif EPIC-H : « male » n'est pas dans « female » ; toutes les mentions sont gold."""
    from anonymisation.datasets.ratbench import _find_occurrences

    text = "Female applicant, male partner. John met John. Email: a@b.com"
    assert [text[s:e] for s, e in _find_occurrences(text, "male")] == ["male"]
    assert [text[s:e] for s, e in _find_occurrences(text, "female")] == ["Female"]
    assert len(_find_occurrences(text, "John")) == 2
    assert _find_occurrences(text, "MALE") == [(18, 22)]  # repli insensible à la casse
    assert _find_occurrences(text, "absent") == []

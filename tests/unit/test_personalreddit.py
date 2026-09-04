"""Tests de l'adaptateur PersonalReddit et du re-split par auteur."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from anonymisation.datasets.manifest import DatasetManifest, load_manifest
from anonymisation.datasets.personalreddit import PersonalRedditAdapter
from anonymisation.datasets.registry import resolve
from anonymisation.schema.taxonomy import ExpressionMode
from anonymisation.schema.validation import validate_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "configs" / "datasets" / "personalreddit.yaml"


def _person(name: str, age: int) -> dict[str, Any]:
    return {
        "age": age,
        "sex": "female",
        "city_country": f"{name} City, France",
        "birth_city_country": f"{name} Birthplace, France",
        "education": "Master in computer science",
        "occupation": "software engineer",
        "income": "100000",
        "income_level": "high",
        "relationship_status": "single",
    }


def _row(personality: dict[str, Any], feature: str = "occupation") -> dict[str, Any]:
    return {
        "feature": feature,
        "guess": "software engineer",
        "guess_correctness": {"exact": True},
        "hardness": 3,
        "label": str(personality[feature]),
        "personality": personality,
        "question_asked": "What do you do?",
        "response": "I build reliable software for research teams.",
    }


def _adapter(tmp_path: Path) -> PersonalRedditAdapter:
    raw = tmp_path / "personalreddit"
    raw.mkdir()
    person_a = _person("A", 31)
    person_b = _person("B", 42)
    (raw / "train.jsonl").write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False)
            for row in (_row(person_a), _row(person_a, "age"))
        )
        + "\n",
        encoding="utf-8",
    )
    (raw / "test.jsonl").write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False)
            for row in (_row(person_a, "sex"), _row(person_b, "education"))
        )
        + "\n",
        encoding="utf-8",
    )
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    data["source"] = {
        "kind": "local",
        "path": str(raw),
        "files": ["train.jsonl", "test.jsonl"],
        "seed": 42,
    }
    data["integrity"]["sha256"] = None
    data["integrity"]["expected_documents"] = 4
    data["integrity"]["expected_profiles"] = 2
    manifest = DatasetManifest.model_validate(data)
    return PersonalRedditAdapter(manifest, raw)


def test_repo_manifest_and_registry() -> None:
    loaded = load_manifest(MANIFEST_PATH, resolve_source=False)
    assert loaded.manifest.key == "personalreddit"
    assert loaded.manifest.integrity.expected_documents == 525
    assert loaded.manifest.integrity.expected_profiles == 40
    assert loaded.manifest.structure.split_by == "person_id"
    assert resolve("personalreddit") is PersonalRedditAdapter
    assert resolve("personal-reddit") is PersonalRedditAdapter


def test_group_split_profiles_and_tasks(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    documents = []
    annotations = []
    profiles = []
    tasks = []
    for split in adapter.splits():
        documents.extend(adapter.iter_documents(split))
        annotations.extend(adapter.iter_annotations(split))
        profiles.extend(adapter.iter_profiles(split))
        tasks.extend(adapter.iter_tasks(split))

    assert len(documents) == len(annotations) == len(tasks) == 4
    assert len(profiles) == 2
    assert all(document.author_id for document in documents)
    assert all(annotation.expression_mode is ExpressionMode.IMPLICIT for annotation in annotations)
    assert all(annotation.start is None and annotation.end is None for annotation in annotations)
    assert {profile.person_id for profile in profiles} == {document.author_id for document in documents}
    assert {task.task for task in tasks} == {"personality_prediction"}
    assert {document.meta["source_split"] for document in documents} == {"train", "test"}

    by_author: dict[str, set[str]] = {}
    for document in documents:
        by_author.setdefault(document.author_id, set()).add(document.split)  # type: ignore[arg-type]
    assert all(len(splits) == 1 for splits in by_author.values())

    report = validate_dataset(
        "personalreddit", documents, annotations, profiles, tasks=tasks, expected_documents=4
    )
    assert not report.errors()


def test_profile_preserves_colliding_source_attributes(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    profiles = list(adapter.iter_profiles("train")) + list(adapter.iter_profiles("test"))
    profile = profiles[0]
    assert set(profile.meta["source_personality"]) == {
        "age",
        "sex",
        "city_country",
        "birth_city_country",
        "education",
        "occupation",
        "income",
        "income_level",
        "relationship_status",
    }
    assert set(profile.attributes["GEN_GEO"].value) == {"current", "birth"}
    assert set(profile.attributes["GEN_SOCIOECON"].value) == {"income", "income_level"}


def test_invalid_hardness_is_blocking(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    path = tmp_path / "personalreddit" / "train.jsonl"
    payload = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    payload[0]["hardness"] = 6
    path.write_text("\n".join(json.dumps(row) for row in payload) + "\n", encoding="utf-8")
    with pytest.raises(Exception, match="hardness hors intervalle"):
        list(adapter.iter_documents("train"))

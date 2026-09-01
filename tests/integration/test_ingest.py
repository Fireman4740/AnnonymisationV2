"""Tests de ``datasets/ingest.py`` — pipeline 5 étapes (SPEC-04, EPIC A-2).

Règle du ticket : **aucun corpus réel** — l'adaptateur est factice, en
mémoire, construit sur le micro-dataset de ``tests/fixtures`` (SPEC-09
§4.3). Les tests couvrent : le déterminisme bit à bit (critère de
non-régression, SPEC-09 §3.3), l'échec bruyant sur violation d'invariant,
les sept éléments du lock, la compatibilité de ``taxonomy_version``, les
statuts ``official``/``sampled``/``diagnostic`` (G3/G5) et l'absence
d'écriture des tables vides.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pour `import fixtures`

from fixtures import load_micro  # noqa: E402

from anonymisation.datasets.base import AcquisitionReport, DatasetAdapter  # noqa: E402
from anonymisation.datasets.ingest import (  # noqa: E402
    IngestionError,
    LocalSourceError,
    LockIncompatibleError,
    check_lock_compatibility,
    ingest,
)
from anonymisation.datasets.manifest import (  # noqa: E402
    DatasetManifest,
    EvaluationSpec,
    IntegritySpec,
    LicenseSpec,
    PopulationSpec,
    SourceSpec,
    StructureSpec,
)
from anonymisation.schema.io import sha256_file  # noqa: E402
from anonymisation.schema.models import Domain  # noqa: E402
from anonymisation.schema.taxonomy import TAXONOMY_VERSION  # noqa: E402


class FakeAdapter(DatasetAdapter):
    """Adaptateur factice : micro-dataset en mémoire, aucun corpus réel.

    Route chaque table vers son split : documents par ``doc.split`` ;
    annotations/tâches par le split du document référencé ; profils par
    l'auteur (cohérent avec les documents — aucune fuite) ; combinaisons
    par le premier document.
    """

    key = "micro"

    def __init__(self, manifest: Any, raw_dir: Path, *, data: dict[str, list] | None = None):
        super().__init__(manifest, raw_dir)
        self._data = data if data is not None else load_micro()
        self._doc_split = {d.doc_id: d.split for d in self._data["documents"]}
        self._person_split = {
            "micro:P1": "train",
            "micro:P2": "train",
            "micro:P3": "dev",
        }

    def download(self, *, force: bool = False) -> AcquisitionReport:
        raise AssertionError("ingest() ne doit pas appeler download()")

    def splits(self) -> tuple[str, ...]:
        return tuple(sorted({d.split for d in self._data["documents"]})
        )

    def iter_documents(self, split: str):
        for rec in self._data["documents"]:
            if split in ("all", rec.split):
                yield rec

    def iter_annotations(self, split: str):
        for rec in self._data["annotations"]:
            owner = self._doc_split.get(rec.doc_id)
            if owner is not None and split in ("all", owner):
                yield rec

    def iter_profiles(self, split: str):
        for rec in self._data["profiles"]:
            owner = self._person_split.get(rec.person_id)
            if owner is not None and split in ("all", owner):
                yield rec

    def iter_combinations(self, split: str):
        for rec in self._data["combinations"]:
            owner = self._doc_split.get(rec.doc_ids[0])
            if owner is not None and split in ("all", owner):
                yield rec

    def iter_tasks(self, split: str):
        for rec in self._data["tasks"]:
            owner = self._doc_split.get(rec.doc_id)
            if owner is not None and split in ("all", owner):
                yield rec


def _manifest(
    tmp_path: Path,
    *,
    spdx: str = "MIT",
    eligible: bool = True,
    expected_documents: int | None = 5,
    expected_profiles: int | None = 3,
    splits: list[str] | None = None,
    source: dict[str, Any] | None = None,
) -> DatasetManifest:
    """Manifeste du micro-dataset, calé sur la volumétrie réelle du fixture."""
    if source is None:
        corpus = tmp_path / "corpus"
        corpus.mkdir(exist_ok=True)
        (corpus / "raw.jsonl").write_text("{}", encoding="utf-8")
        source = {"kind": "local", "path": str(corpus), "files": ["raw.jsonl"]}
    return DatasetManifest(
        key="micro",
        name="Micro",
        description="micro-dataset de test",
        doc="tests/fixtures/README.md",
        source=SourceSpec(**source),
        license=LicenseSpec(spdx=spdx, redistribution=True, citation="micro2026"),
        integrity=IntegritySpec(
            sha256="e" * 64,
            expected_documents=expected_documents,
            expected_profiles=expected_profiles,
            expected_threads=2,
        ),
        structure=StructureSpec(
            domain="hr",
            languages=["fr"],
            synthetic=True,
            has_profiles=True,
            has_combinations=True,
            has_organizations=False,
            has_tasks=True,
            split_by="person_id",
            splits=["dev", "train"] if splits is None else splits,
        ),
        evaluation=EvaluationSpec(
            protocol="micro-v1",
            protocol_version="1",
            official_eligible=eligible,
            default_metric_status="OFFICIAL",
            granularities=["document"],
            report_by=["language"],
        ),
        population=PopulationSpec(population_id="fr-hr-2026", k_computable=True),
    )


def _ingest(
    tmp_path: Path,
    *,
    data: dict[str, list] | None = None,
    output_root: Path | None = None,
    split: str = "all",
    limit: int | None = None,
    **overrides: Any,
) -> Any:
    manifest = _manifest(tmp_path, **overrides)
    adapter = FakeAdapter(manifest, tmp_path / "raw", data=data)
    root = output_root if output_root is not None else tmp_path / "processed"
    return ingest(adapter, manifest, split=split, limit=limit, output_root=root)


def _snapshot(root: Path) -> dict[str, str]:
    """sha256 de chaque fichier de ``root``, indexé par chemin relatif."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = sha256_file(p)
    return out


def _files(base: Path) -> set[str]:
    return {p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()}


def _with_corrupt_annotation(data: dict[str, list]) -> dict[str, list]:
    """I-ANN-1 : offsets valides mais ``span_text`` incohérent avec le texte."""
    data = {k: list(v) for k, v in data.items()}
    bad = data["annotations"][0].model_copy(update={"span_text": "FAUX"})
    data["annotations"][0] = bad
    return data


def _with_split_leak(data: dict[str, list]) -> dict[str, list]:
    """E-VAL-108 : un auteur présent à la fois en train et en dev."""
    from anonymisation.schema.models import Document

    data = {k: list(v) for k, v in data.items()}
    data["documents"].append(
        Document(
            doc_id="micro:d6",
            dataset="micro",
            split="dev",
            domain=Domain.HR,
            language="fr",
            text="Document de fuite.",
            author_id="micro:P1",
        )
    )
    return data


# --- Écriture des tables ------------------------------------------------------ #


def test_ingest_writes_expected_tables(tmp_path: Path) -> None:
    _ingest(tmp_path)
    base = tmp_path / "processed" / "micro"
    expected = {
        "train/documents.jsonl",
        "train/annotations.jsonl",
        "train/profiles.jsonl",
        "train/combinations.jsonl",
        "train/tasks.jsonl",
        "dev/documents.jsonl",
        "dev/annotations.jsonl",
        "dev/profiles.jsonl",
        "dev/tasks.jsonl",
        ".validation.json",
        ".manifest.lock.json",
    }
    assert _files(base) == expected
    # tables vides non écrites : dev n'a pas de combinaisons, ni d'organizations


def test_specific_split_writes_only_that_split(tmp_path: Path) -> None:
    result = _ingest(tmp_path, split="dev")
    base = tmp_path / "processed" / "micro"
    assert _files(base) == {
        "dev/documents.jsonl",
        "dev/annotations.jsonl",
        "dev/profiles.jsonl",
        "dev/tasks.jsonl",
        ".validation.json",
        ".manifest.lock.json",
    }
    assert result.counts["documents"] == 1


# --- Déterminisme bit à bit (SPEC-09 §3.3) ------------------------------------- #


def test_reingest_bit_identical(tmp_path: Path) -> None:
    _ingest(tmp_path, output_root=tmp_path / "p1")
    snap1 = _snapshot(tmp_path / "p1")
    _ingest(tmp_path, output_root=tmp_path / "p2")
    snap2 = _snapshot(tmp_path / "p2")
    assert snap1
    assert snap1 == snap2  # mêmes chemins, mêmes octets


def test_reingest_same_root_stable(tmp_path: Path) -> None:
    r1 = _ingest(tmp_path)
    snap1 = _snapshot(tmp_path / "processed")
    r2 = _ingest(tmp_path)  # deuxième ingestion, même racine
    assert _snapshot(tmp_path / "processed") == snap1
    lock1 = json.loads(r1.lock_path.read_text(encoding="utf-8"))
    lock2 = json.loads(r2.lock_path.read_text(encoding="utf-8"))
    assert lock1["files"] == lock2["files"]


# --- Le lock : sept éléments de reproductibilité (SPEC-09 §5) ------------------ #


def test_lock_has_seven_reproducibility_elements(tmp_path: Path) -> None:
    result = _ingest(tmp_path)
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    assert set(lock) == {
        "manifest",
        "schema_version",
        "taxonomy_version",
        "source",
        "files",
        "date",
        "status",
    }
    assert lock["schema_version"] == "2.0"
    assert lock["taxonomy_version"] == TAXONOMY_VERSION
    assert lock["date"] == date.today().isoformat()
    assert lock["source"]["kind"] == "local"
    assert lock["source"]["fingerprint"]
    assert lock["source"]["directory"]
    # manifeste résolu : la copie figée est le manifeste lui-même
    assert lock["manifest"]["key"] == "micro"
    assert lock["manifest"]["source"]["path"]


def test_lock_file_hashes_match_real_files(tmp_path: Path) -> None:
    result = _ingest(tmp_path)
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    base = result.lock_path.parent
    assert lock["files"]
    for rel, digest in lock["files"].items():
        assert sha256_file(base / rel) == digest
    # la map du lock est exacte : aucun fichier de plus ni de moins
    assert set(lock["files"]) == {
        p.relative_to(base).as_posix()
        for p in base.rglob("*.jsonl")
    }


# --- .validation.json = rapport de validation ---------------------------------- #


def test_validation_json_is_report_dict(tmp_path: Path) -> None:
    result = _ingest(tmp_path)
    base = tmp_path / "processed" / "micro"
    payload = json.loads((base / ".validation.json").read_text(encoding="utf-8"))
    assert payload == result.validation
    assert payload["dataset"] == "micro"
    # le micro-dataset porte un avertissement I-PRO-2 (attribut sans normalized)
    assert payload["status"] == "WARN"
    assert payload["errors"] == []
    assert {w["code"] for w in payload["warnings"]} == {"E-VAL-107"}
    counts = payload["counts"]
    assert counts["documents"] == 5
    assert counts["annotations"] == 13
    assert counts["profiles"] == 3
    assert counts["combinations"] == 4
    assert counts["tasks"] == 5
    assert counts["by_language"] == {"fr": 5}
    assert counts["by_qi_category"]["DIR_EMAIL"] == 1


# --- Statuts G3/G5 ------------------------------------------------------------- #


def test_status_official(tmp_path: Path) -> None:
    result = _ingest(tmp_path)
    assert result.status == "official"
    assert json.loads(result.lock_path.read_text(encoding="utf-8"))["status"] == "official"


def test_status_diagnostic_with_unknown_spdx(tmp_path: Path) -> None:
    """G3 : licence inconnue → diagnostic, même si l'éligibilité est déclarée."""
    result = _ingest(tmp_path, spdx="UNKNOWN", eligible=True)
    assert result.status == "diagnostic"


def test_status_sampled_when_volumetry_diverges(tmp_path: Path) -> None:
    """G5 : volumétrie divergente → sampled, pas official."""
    result = _ingest(tmp_path, expected_documents=999)
    assert result.status == "sampled"


def test_status_sampled_with_limit(tmp_path: Path) -> None:
    result = _ingest(tmp_path, limit=2)
    assert result.status == "sampled"
    train_docs = (tmp_path / "processed" / "micro" / "train" / "documents.jsonl").read_text()
    assert len(train_docs.splitlines()) <= 2


# --- Échecs bruyants ----------------------------------------------------------- #


def test_offset_violation_fails_ingestion(tmp_path: Path) -> None:
    """I-ANN-1 : échec immédiat, jamais journalisé en avertissement."""
    with pytest.raises(IngestionError, match="E-VAL-101"):
        _ingest(tmp_path, data=_with_corrupt_annotation(load_micro()))
    assert not (tmp_path / "processed").exists()  # rien n'est publié


def test_split_leak_fails_ingestion(tmp_path: Path) -> None:
    """E-VAL-108 : la fuite par profil latent est bloquante."""
    with pytest.raises(IngestionError, match="E-VAL-108") as excinfo:
        _ingest(tmp_path, data=_with_split_leak(load_micro()))
    assert "micro:P1" in str(excinfo.value)
    assert not (tmp_path / "processed").exists()


def test_unknown_split_rejected(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="inconnu"):
        _ingest(tmp_path, split="bogus")

def test_all_with_no_declared_splits_rejected(tmp_path: Path) -> None:
    """'all' + manifest vide + adapter sans surcharge de ``splits()`` → erreur."""

    class _SansSurcharge(FakeAdapter):
        """Adaptateur reprenant le comportement de base : ``splits()`` = manifeste."""

        def splits(self) -> tuple[str, ...]:
            return DatasetAdapter.splits(self)

    manifest = _manifest(tmp_path, splits=[])
    adapter = _SansSurcharge(manifest, tmp_path / "raw")
    with pytest.raises(IngestionError, match="aucun split"):
        ingest(adapter, manifest, output_root=tmp_path / "processed")


def test_all_falls_back_to_adapter_declared_splits(tmp_path: Path) -> None:
    """Manifeste vide : la surcharge de l'adaptateur est une source légitime."""
    result = _ingest(tmp_path, splits=[])
    assert result.counts["documents"] == 5


def test_negative_limit_rejected(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="négatif"):
        _ingest(tmp_path, limit=-1)


def test_local_source_missing_fails(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        source={"kind": "local", "path": str(tmp_path / "absent")},
    )
    adapter = FakeAdapter(manifest, tmp_path / "raw")
    with pytest.raises(LocalSourceError):
        ingest(adapter, manifest, output_root=tmp_path / "processed")


# --- Compatibilité du lock ----------------------------------------------------- #


def test_check_lock_compatibility_ok(tmp_path: Path) -> None:
    result = _ingest(tmp_path)
    lock = check_lock_compatibility(result.lock_path)
    assert lock["taxonomy_version"] == TAXONOMY_VERSION


def test_check_lock_compatibility_taxonomy_mismatch(tmp_path: Path) -> None:
    """Taxonomie divergente → refus explicite demandant une réingestion."""
    result = _ingest(tmp_path)
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    lock["taxonomy_version"] = "0.9"
    result.lock_path.write_text(
        json.dumps(lock, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(LockIncompatibleError, match="réingestion"):
        check_lock_compatibility(result.lock_path)


def test_check_lock_compatibility_missing_lock(tmp_path: Path) -> None:
    with pytest.raises(LockIncompatibleError):
        check_lock_compatibility(tmp_path / "absent.json")

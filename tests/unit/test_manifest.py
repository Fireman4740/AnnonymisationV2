"""Tests de ``datasets/manifest.py`` — schéma des manifestes et contrôles (EPIC A-1).

Chaque contrôle normatif du ticket a un test négatif (violation → erreur
actionnable nommant le champ) et un test positif (cas valide accepté). Le
jeu des 5 manifestes du dépôt sert de non-régression : ils DOIVENT tous
se charger tels quels (SPEC-03 §4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from anonymisation.datasets._local import LocalSourceError
from anonymisation.datasets.manifest import (
    DatasetManifest,
    load_all_manifests,
    load_manifest,
)
from anonymisation.datasets.registry import ManifestError

REPO_ROOT = Path(__file__).resolve().parents[2]


def _manifest(**overrides: Any) -> dict[str, Any]:
    """Un manifeste minimal valide, en données brutes."""
    data: dict[str, Any] = {
        "key": "tst",
        "name": "Test",
        "description": "corpus de test",
        "doc": "documentation/datasets/tst.md",
        "aliases": [],
        "source": {"kind": "manual", "instructions": "manuel"},
        "license": {
            "spdx": "MIT",
            "redistribution": True,
            "restricted": False,
            "citation": "tst2026",
        },
        "integrity": {
            "sha256": None,
            "expected_documents": None,
            "expected_profiles": 0,
        },
        "structure": {
            "domain": "generic",
            "languages": ["fr"],
            "synthetic": False,
            "has_profiles": False,
            "has_combinations": False,
            "has_organizations": False,
            "has_tasks": False,
            "split_by": "document",
            "splits": ["train", "test"],
        },
        "label_map": {},
        "evaluation": {
            "protocol": "tst-v1",
            "protocol_version": "1",
            "official_eligible": True,
            "default_metric_status": "OFFICIAL",
            "granularities": ["document"],
            "report_by": ["language"],
        },
        "population": {"population_id": None, "k_computable": False},
    }
    data.update(overrides)
    return data


def _write(tmp_path: Path, data: dict[str, Any], name: str = "tst.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


# --- Non-régression sur les manifestes du dépôt ------------------------------- #


def test_repo_manifests_all_load() -> None:
    """Les 10 manifestes du dépôt se chargent tels quels (jeu A-1/G-6)."""
    loaded = load_all_manifests(REPO_ROOT / "configs" / "datasets")
    assert set(loaded) == {
        "openpii",
        "panorama",
        "ratbench",
        "spia",
        "synthpai",
        "tab",
        "hr_qi",
        "personalreddit",
        "quasifr",
        "dbbio",
    }


def test_repo_manifests_keep_declared_values() -> None:
    loaded = load_all_manifests(REPO_ROOT / "configs" / "datasets")
    hr_qi = loaded["hr_qi"].manifest
    assert hr_qi.license.spdx == "à décider"
    assert hr_qi.evaluation.official_eligible is True  # non-UNKNOWN : non forcé
    assert hr_qi.evaluation.reweighting == "required"
    assert hr_qi.population.risk_model == "copula"
    tab = loaded["tab"].manifest
    assert tab.annotation == {"aggregation": "union", "keep_coreference": True}
    assert tab.license.redistribution is True
    synthpai = loaded["synthpai"].manifest
    assert synthpai.integrity.expected_threads == 103
    assert synthpai.source.mirror is not None
    openpii = loaded["openpii"].manifest
    assert openpii.aliases == ["ai4privacy", "open-pii-500k"]


    personalreddit = loaded["personalreddit"].manifest
    assert personalreddit.structure.synthetic is True
    assert personalreddit.integrity.expected_documents == 525
    assert personalreddit.integrity.expected_profiles == 40
    assert personalreddit.license.spdx == "CC-BY-NC-SA-4.0"
    dbbio = loaded["dbbio"].manifest
    assert dbbio.integrity.expected_documents == 2420
    assert dbbio.structure.has_tasks is True

# --- Contrôle 3 : spdx UNKNOWN → official_eligible = False ------------------- #


def test_spdx_unknown_forces_eligible_false(tmp_path: Path) -> None:
    data = _manifest()
    data["license"]["spdx"] = "UNKNOWN"
    loaded = load_manifest(_write(tmp_path, data))
    assert loaded.manifest.evaluation.official_eligible is False


def test_spdx_non_unknown_keeps_declaration(tmp_path: Path) -> None:
    """Seul ``UNKNOWN`` force : toute autre valeur reste celle déclarée."""
    data = _manifest()
    data["license"]["spdx"] = "à décider"
    loaded = load_manifest(_write(tmp_path, data))
    assert loaded.manifest.evaluation.official_eligible is True


# --- Contrôle 2 : has_profiles + split_by document → erreur ------------------- #


def test_profiles_document_split_rejected(tmp_path: Path) -> None:
    data = _manifest()
    data["structure"]["has_profiles"] = True
    data["structure"]["split_by"] = "document"
    with pytest.raises(ManifestError, match="fuite par profil latent"):
        load_manifest(_write(tmp_path, data))


def test_profiles_person_split_accepted(tmp_path: Path) -> None:
    data = _manifest()
    data["structure"]["has_profiles"] = True
    data["structure"]["split_by"] = "person_id"
    loaded = load_manifest(_write(tmp_path, data))
    assert loaded.manifest.structure.has_profiles is True


# --- Contrôle 1 : label_map hors SPEC-01 → erreur nommant le code ------------ #


def test_unknown_qi_code_rejected(tmp_path: Path) -> None:
    data = _manifest()
    data["label_map"] = {
        "AGE": {
            "identifier_type": "QUASI",
            "qi_categories": ["GEN_AGE", "DIR_BOGUS"],
            "granularity": "EXACT",
            "stability": "STABLE",
        }
    }
    with pytest.raises(ManifestError, match="DIR_BOGUS") as excinfo:
        load_manifest(_write(tmp_path, data))
    assert "AGE" in str(excinfo.value)  # l'étiquette source est nommée


def test_valid_label_map_accepted(tmp_path: Path) -> None:
    data = _manifest()
    data["label_map"] = {
        "PERSON": {
            "identifier_type": "DIRECT",
            "qi_categories": ["DIR_NAME"],
            "granularity": "EXACT",
            "stability": "STABLE",
        },
        "CITY": {
            "identifier_type": "QUASI",
            "qi_categories": ["GEN_GEO"],
            "granularity": "COARSE",
            "stability": "VOLATILE",
        },
    }
    loaded = load_manifest(_write(tmp_path, data))
    assert set(loaded.manifest.label_map) == {"PERSON", "CITY"}
    assert loaded.manifest.label_map["PERSON"].qi_categories == ["DIR_NAME"]


def test_label_map_default_empty(tmp_path: Path) -> None:
    data = _manifest()
    del data["label_map"]
    loaded = load_manifest(_write(tmp_path, data))
    assert loaded.manifest.label_map == {}


# --- Schéma : extra=forbid, frozen, défauts sanctionnés ---------------------- #


def test_extra_top_level_field_rejected(tmp_path: Path) -> None:
    data = _manifest(unknowable="non")
    with pytest.raises(ManifestError, match="unknowable"):
        load_manifest(_write(tmp_path, data))


def test_synthetic_defaults_false(tmp_path: Path) -> None:
    """Défaut sanctionné n°1 (garde E1, SPEC-08) : `synthetic` absent → False."""
    data = _manifest()
    del data["structure"]["synthetic"]
    loaded = load_manifest(_write(tmp_path, data))
    assert loaded.manifest.structure.synthetic is False


def test_restricted_defaults_false(tmp_path: Path) -> None:
    """Défaut sanctionné n°2 (L3, SPEC-09) : `restricted` absent → False."""
    data = _manifest()
    del data["license"]["restricted"]
    loaded = load_manifest(_write(tmp_path, data))
    assert loaded.manifest.license.restricted is False


def test_missing_required_field_rejected(tmp_path: Path) -> None:
    data = _manifest()
    del data["integrity"]["expected_documents"]
    with pytest.raises(ManifestError):
        load_manifest(_write(tmp_path, data))


def test_model_is_frozen() -> None:
    manifest = DatasetManifest.model_validate(_manifest())
    with pytest.raises(ValidationError):
        manifest.name = "autre"  # type: ignore[method-assign]


def test_unknown_source_kind_rejected(tmp_path: Path) -> None:
    data = _manifest(source={"kind": "ftp"})
    with pytest.raises(ManifestError, match="ftp"):
        load_manifest(_write(tmp_path, data))


def test_local_without_path_nor_env(tmp_path: Path) -> None:
    data = _manifest(source={"kind": "local"})
    with pytest.raises(ManifestError, match="path"):
        load_manifest(_write(tmp_path, data))


# --- Source locale : résolution, environnement, absence ----------------------- #


def test_local_relative_path_resolves_from_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "data.json").write_text("{}", encoding="utf-8")
    data = _manifest(source={"kind": "local", "path": "corpus", "files": ["data.json"]})
    loaded = load_manifest(_write(tmp_path, data, name="m.yaml"))
    assert loaded.resolution is not None
    assert loaded.resolution.directory.resolve() == (tmp_path / "corpus").resolve()
    files = tuple(p.resolve() for p in loaded.resolution.files)
    assert files == ((tmp_path / "corpus" / "data.json").resolve(),)
    assert loaded.resolution.fingerprint


def test_local_env_var_takes_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``path_env`` définie → la racine vient de l'environnement, pas du YAML."""
    root = tmp_path / "racine-autre-machine"
    (root / "corpus").mkdir(parents=True)
    (root / "corpus" / "data.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ANONV2_V1_DATASETS", str(root))

    data = _manifest(
        source={
            "kind": "local",
            # sans la variable, ce chemin relatif serait résolu depuis le
            # répertoire courant (et absent) : la variable change la racine
            "path": "corpus",
            "path_env": "ANONV2_V1_DATASETS",
            "files": ["data.json"],
        }
    )
    loaded = load_manifest(_write(tmp_path, data, name="m.yaml"))
    assert loaded.resolution is not None
    assert loaded.resolution.directory == root / "corpus"


def test_local_env_var_missing_but_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Variable absente mais `path` absolu : repli sur le chemin déclaré."""
    monkeypatch.delenv("ANONV2_V1_DATASETS", raising=False)
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "data.json").write_text("{}", encoding="utf-8")
    data = _manifest(
        source={
            "kind": "local",
            "path": str(tmp_path / "corpus"),
            "path_env": "ANONV2_V1_DATASETS",
            "files": ["data.json"],
        }
    )
    loaded = load_manifest(_write(tmp_path, data, name="m.yaml"))
    assert loaded.resolution is not None
    assert loaded.resolution.directory == tmp_path / "corpus"


def test_local_missing_env_var_names_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Source absente → message indiquant la variable à définir (crite A-1)."""
    monkeypatch.delenv("ANONV2_V1_DATASETS", raising=False)
    data = _manifest(
        source={"kind": "local", "path": "rel/corpus", "path_env": "ANONV2_V1_DATASETS"}
    )
    with pytest.raises(LocalSourceError, match="ANONV2_V1_DATASETS") as excinfo:
        load_manifest(_write(tmp_path, data, name="m.yaml"))
    assert "définissez" in str(excinfo.value).lower() or "définir" in str(excinfo.value).lower()


def test_local_missing_file(tmp_path: Path) -> None:
    (tmp_path / "corpus").mkdir()
    data = _manifest(
        source={"kind": "local", "path": str(tmp_path / "corpus"), "files": ["absent.json"]}
    )
    with pytest.raises(LocalSourceError, match="absent.json") as excinfo:
        load_manifest(_write(tmp_path, data, name="m.yaml"))
    assert str(tmp_path / "corpus") in str(excinfo.value)


def test_local_absent_directory(tmp_path: Path) -> None:
    data = _manifest(source={"kind": "local", "path": str(tmp_path / "nulle-part")})
    with pytest.raises(LocalSourceError, match="nulle-part"):
        load_manifest(_write(tmp_path, data, name="m.yaml"))


# --- Chargement en masse ------------------------------------------------------- #


def test_load_all_duplicate_key(tmp_path: Path) -> None:
    a = _write(tmp_path, _manifest(key="dup"), name="a.yaml")
    b = _write(tmp_path, _manifest(key="dup"), name="b.yaml")
    with pytest.raises(ManifestError, match="dup"):
        load_all_manifests(tmp_path)
    assert a.exists() and b.exists()


def test_load_all_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        load_all_manifests(tmp_path / "inexistant")

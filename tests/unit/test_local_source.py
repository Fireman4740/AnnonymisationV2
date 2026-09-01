"""Tests de ``datasets/_local.py`` — résolution des sources locales (EPIC A-1).

Critères d'acceptation couverts : la variable ``ANONV2_V1_DATASETS`` pointée
vers un répertoire temporaire est prise en compte (portabilité), une source
absente renvoie un message nommant la variable à définir, et l'empreinte est
stable quel que soit l'ordre des chemins fournis.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from anonymisation.datasets._local import (
    V1_DATASETS_ENV,
    LocalSourceError,
    check_files,
    fingerprint,
    resolve_source_dir,
    resolve_v1_cache,
)


@dataclass
class _Src:
    kind: str = "local"
    path: str | None = None
    path_env: str | None = None
    files: list[str] = field(default_factory=list)


# --- fingerprint -------------------------------------------------------------- #


def test_fingerprint_stable_regardless_of_order(tmp_path: Path) -> None:
    """Crite A-1 : l'ordre des chemins fournis ne change pas l'empreinte."""
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text('{"x": 1}', encoding="utf-8")
    b.write_text('{"y": 2}', encoding="utf-8")
    assert fingerprint([a, b]) == fingerprint([b, a])
    assert fingerprint([a, b]) == fingerprint([a, b])


def test_fingerprint_sensitive_to_content(tmp_path: Path) -> None:
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text("premier", encoding="utf-8")
    b.write_text("deuxième", encoding="utf-8")
    before = fingerprint([a, b])
    a.write_text("modifié", encoding="utf-8")
    assert fingerprint([a, b]) != before


def test_fingerprint_distinguishes_names(tmp_path: Path) -> None:
    """Même contenu, noms différents → empreintes différentes."""
    a = tmp_path / "premier.json"
    b = tmp_path / "second.json"
    a.write_text("même", encoding="utf-8")
    b.write_text("même", encoding="utf-8")
    assert fingerprint([a]) != fingerprint([b])


def test_fingerprint_empty_list_is_deterministic(tmp_path: Path) -> None:
    assert fingerprint([]) == hashlib.sha256(b"").hexdigest()


# --- resolve_source_dir -------------------------------------------------------- #


def test_resolve_path_absolute() -> None:
    assert resolve_source_dir(_Src(path="/absolu/vers/corpus")) == Path("/absolu/vers/corpus")


def test_resolve_path_relative_is_cwd_based(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    resolved = resolve_source_dir(_Src(path="rel/corpus")).resolve()
    assert resolved == (tmp_path / "rel" / "corpus").resolve()


def test_resolve_env_var_with_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crite A-1 : la variable pointant vers un répertoire temporaire est prise en compte."""
    root = tmp_path / "racine"
    root.mkdir()
    monkeypatch.setenv(V1_DATASETS_ENV, str(root))
    resolved = resolve_source_dir(_Src(path="corpus", path_env=V1_DATASETS_ENV))
    assert resolved == root / "corpus"


def test_resolve_env_var_with_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un `path` absolu garde la main sur la racine de la variable (pathlib)."""
    root = tmp_path / "racine"
    root.mkdir()
    monkeypatch.setenv(V1_DATASETS_ENV, str(root))
    target = tmp_path / "absolu"
    resolved = resolve_source_dir(_Src(path=str(target), path_env=V1_DATASETS_ENV))
    assert resolved == target


def test_resolve_env_var_missing_relative_path_names_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(V1_DATASETS_ENV, raising=False)
    with pytest.raises(LocalSourceError, match=V1_DATASETS_ENV) as excinfo:
        resolve_source_dir(_Src(path="rel/corpus", path_env=V1_DATASETS_ENV))
    message = str(excinfo.value)
    assert "définissez" in message.lower()  # actionnable : dit quoi définir


def test_resolve_env_var_missing_absolute_path_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(V1_DATASETS_ENV, raising=False)
    target = tmp_path / "corpus"
    assert resolve_source_dir(_Src(path=str(target), path_env=V1_DATASETS_ENV)) == target


def test_resolve_env_var_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "racine"
    root.mkdir()
    monkeypatch.setenv(V1_DATASETS_ENV, str(root))
    assert resolve_source_dir(_Src(path_env=V1_DATASETS_ENV)) == root


def test_resolve_local_without_any_locator(tmp_path: Path) -> None:
    with pytest.raises(LocalSourceError, match="path"):
        resolve_source_dir(_Src())


def test_resolve_non_local_kind_rejected(tmp_path: Path) -> None:
    with pytest.raises(LocalSourceError, match="huggingface"):
        resolve_source_dir(_Src(kind="huggingface", path="x"))


# --- check_files --------------------------------------------------------------- #


def test_check_files_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(LocalSourceError, match="absent"):
        check_files(tmp_path / "nulle-part")


def test_check_files_directory_only(tmp_path: Path) -> None:
    (tmp_path / "corpus").mkdir()
    assert check_files(tmp_path / "corpus") == [tmp_path / "corpus"]
    assert check_files(tmp_path / "corpus", []) == [tmp_path / "corpus"]


def test_check_files_all_present(tmp_path: Path) -> None:
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "train.json").write_text("{}", encoding="utf-8")
    (tmp_path / "corpus" / "test.json").write_text("{}", encoding="utf-8")
    resolved = check_files(tmp_path / "corpus", ["train.json", "test.json"])
    assert resolved == [tmp_path / "corpus" / "train.json", tmp_path / "corpus" / "test.json"]


def test_check_files_missing_file_is_named(tmp_path: Path) -> None:
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "train.json").write_text("{}", encoding="utf-8")
    with pytest.raises(LocalSourceError, match="test.json") as excinfo:
        check_files(tmp_path / "corpus", ["train.json", "test.json"])
    assert str(tmp_path / "corpus") in str(excinfo.value)


def test_check_files_file_not_a_directory(tmp_path: Path) -> None:
    target = tmp_path / "fichier.json"
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(LocalSourceError, match="pas un répertoire"):
        check_files(target)


# --- resolve_v1_cache ---------------------------------------------------------- #


def test_resolve_v1_cache_none() -> None:
    assert resolve_v1_cache(None) is None
    assert resolve_v1_cache("") is None


def test_resolve_v1_cache_without_env_is_relative() -> None:
    """Sans variable : chemin relatif au répertoire courant (disposition du dépôt)."""
    assert resolve_v1_cache("../Anonymisation/eval/datasets/TAB") == Path(
        "../Anonymisation/eval/datasets/TAB"
    )


def test_resolve_v1_cache_with_env(tmp_path: Path) -> None:
    root = tmp_path / "racine-v1"
    root.mkdir()
    resolved = resolve_v1_cache(
        "../Anonymisation/eval/datasets/TAB", env={V1_DATASETS_ENV: str(root)}
    )
    assert resolved == root / "../Anonymisation/eval/datasets/TAB"

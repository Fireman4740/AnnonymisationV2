"""Tests dédiés du hook de conformité SPEC-09 §2.2."""

from __future__ import annotations

from pathlib import Path

from scripts.check_no_data_committed import check_paths


def test_data_readme_and_gitkeep_are_allowed(tmp_path: Path) -> None:
    readme = tmp_path / "data" / "README.md"
    gitkeep = tmp_path / "data" / "raw" / ".gitkeep"
    readme.parent.mkdir(parents=True)
    gitkeep.parent.mkdir(parents=True)
    readme.write_text("inventaire", encoding="utf-8")
    gitkeep.touch()
    assert check_paths([readme, gitkeep]) == []


def test_hook_rejects_data_and_restricted_paths(tmp_path: Path) -> None:
    paths = [
        tmp_path / "data" / "raw" / "sample.jsonl",
        tmp_path / "mimic" / "record.txt",
        tmp_path / "MEDDOCAN" / "record.txt",
        tmp_path / "scan.dcm",
        tmp_path / ".env",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    violations = check_paths(paths)
    assert any("data/" in violation for violation in violations)
    assert any("mimic" in violation for violation in violations)
    assert any("meddocan" in violation.lower() for violation in violations)
    assert any(".dcm" in violation for violation in violations)
    assert any(".env" in violation for violation in violations)


def test_hook_rejects_large_jsonl_and_api_secret(tmp_path: Path) -> None:
    large = tmp_path / "records.jsonl"
    large.write_bytes(b"x" * 1_000_001)
    secret = tmp_path / "settings.ini"
    secret.write_text("API_KEY=sk-" + "a" * 24, encoding="utf-8")
    violations = check_paths([large, secret])
    assert any("limite" in violation for violation in violations)
    assert any("secret" in violation for violation in violations)

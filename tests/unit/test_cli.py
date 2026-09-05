"""Tests de la CLI ``anonv2`` (ticket EPIC-A, A-3).

Les commandes sont testées via ``main(argv)`` — jamais de ``SystemExit``
non contrôlé : usage → 2 (``parser.error``/``parser`` natif), échec → 1,
succès → 0. L'environnement est factice : dépôt simulé dans ``tmp_path``
(configs/datasets, data/processed, data/raw) + constantes du module
monkeypatchées. Aucun corpus réel (SPEC-09 §4.3), aucun polluant global.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import anonymisation.cli.main as cli
from anonymisation.datasets.base import AcquisitionReport, DatasetAdapter
from anonymisation.schema.models import Document, Domain

# --- Dépôt factice ----------------------------------------------------------- #


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Dépôt simulé : manifestes, corpus vide, racines data/ patchées."""
    config_dir = tmp_path / "configs" / "datasets"
    config_dir.mkdir(parents=True)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "raw.txt").write_text("x", encoding="utf-8")
    (tmp_path / "data" / "processed").mkdir(parents=True)
    (tmp_path / "data" / "raw").mkdir(parents=True)
    monkeypatch.setattr(cli, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cli, "PROCESSED_ROOT", tmp_path / "data" / "processed")
    monkeypatch.setattr(cli, "RAW_ROOT", tmp_path / "data" / "raw")
    return tmp_path


def _write_manifest(repo: Path, key: str = "tst", spdx: str = "MIT") -> None:
    corpus = repo / "corpus"
    text = (
        f"key: {key}\n"
        f'name: "{key}"\n'
        f'description: "Manifeste de test"\n'
        f'doc: "docs/{key}.md"\n'
        "source:\n"
        '  kind: "local"\n'
        # Scalaire YAML entre apostrophes : un chemin Windows (``C:\Users\…``)
        # dans un scalaire entre guillemets serait lu comme des échappements.
        f"  path: '{corpus}'\n"
        '  files: ["raw.txt"]\n'
        "license:\n"
        f'  spdx: "{spdx}"\n'
        "integrity:\n"
        "  sha256: null\n"
        "  expected_documents: 1\n"
        "  expected_profiles: null\n"
        "structure:\n"
        '  domain: "hr"\n'
        '  languages: ["fr"]\n'
        "  synthetic: true\n"
        "  has_profiles: false\n"
        "  has_combinations: false\n"
        "  has_organizations: false\n"
        "  has_tasks: false\n"
        '  split_by: "document"\n'
        '  splits: ["train"]\n'
        "evaluation:\n"
        f'  protocol: "{key}-v1"\n'
        '  protocol_version: "1"\n'
        "  official_eligible: true\n"
        '  default_metric_status: "OFFICIAL"\n'
        '  granularities: ["document"]\n'
        '  report_by: ["language"]\n'
        "population:\n"
        f'  population_id: "{key}"\n'
        "  k_computable: false\n"
    )
    (repo / "configs" / "datasets" / f"{key}.yaml").write_text(text, encoding="utf-8")


class _TstAdapter(DatasetAdapter):
    """Adaptateur minimal : un seul document, aucune autre table."""

    key = "tst"

    def download(self, *, force: bool = False) -> AcquisitionReport:
        raise AssertionError("ingest() ne doit pas appeler download()")

    def iter_documents(self, split: str):
        if split in ("all", "train"):
            yield Document(
                doc_id="tst:d1",
                dataset="tst",
                split="train",
                domain=Domain.HR,
                language="fr",
                text="Bonjour le monde.",
            )

    def iter_annotations(self, split: str):
        return iter(())


class _DownloadAdapter(_TstAdapter):
    def download(self, *, force: bool = False) -> AcquisitionReport:
        return AcquisitionReport(
            dataset=self.key,
            path=self.raw_dir,
            sha256="a" * 64,
            bytes_downloaded=0,
            from_cache=True,
            revision="test-revision",
        )


# --- version ----------------------------------------------------------------- #


def test_module_imports() -> None:
    """Critère A-3 : l'import fonctionne (typer/rich absents)."""
    import anonymisation.cli.main  # noqa: F401


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["version"]) == 0
    assert "anonymisation-v2" in capsys.readouterr().out


def test_no_args_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 2
    assert "usage" in capsys.readouterr().out


# --- datasets list ----------------------------------------------------------- #


def test_list_works_without_adapter(repo: Path, capsys: pytest.CaptureFixture[str],
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """Critère A-3 : list marche même sans adaptateur enregistré."""
    _write_manifest(repo)
    monkeypatch.setattr(cli, "REGISTRY", {})
    assert cli.main(["datasets", "list"]) == 0
    out = capsys.readouterr().out
    assert "tst" in out
    assert "non implémenté" in out
    assert "non ingéré" in out


def test_list_shows_registered_adapter(repo: Path, capsys: pytest.CaptureFixture[str],
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    _write_manifest(repo)
    monkeypatch.setattr(cli, "REGISTRY", {"tst": _TstAdapter})
    assert cli.main(["datasets", "list"]) == 0
    assert "implémenté" in capsys.readouterr().out


# --- stats / validate non ingérés --------------------------------------------- #


def test_stats_not_ingested(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Critère A-3 : message clair, pas de traceback."""
    _write_manifest(repo)
    assert cli.main(["datasets", "stats", "tst"]) == 1
    err = capsys.readouterr().err
    assert "non ingéré" in err
    assert "anonv2 datasets ingest tst" in err


def test_validate_not_ingested(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_manifest(repo)
    assert cli.main(["datasets", "validate", "tst"]) == 1
    assert "non ingéré" in capsys.readouterr().err


# --- erreurs d'usage ---------------------------------------------------------- #


def test_unknown_key_is_usage_error(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_manifest(repo)
    assert cli.main(["datasets", "stats", "nope"]) == 2
    err = capsys.readouterr().err
    assert "Dataset inconnu" in err
    assert "tst" in err  # les clés connues sont listées


def test_ingest_conflicting_args_exit2(repo: Path) -> None:
    """--all + --split distinct → erreur d'usage (code 2, argparse natif)."""
    _write_manifest(repo)
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["datasets", "ingest", "tst", "--all", "--split", "train"])
    assert excinfo.value.code == 2

def test_ingest_all_skips_unregistered_corpus_and_reports(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le batch CI continue et liste un corpus sans adaptateur."""
    _write_manifest(repo)
    monkeypatch.setattr(cli, "REGISTRY", {})

    assert cli.main(["datasets", "ingest", "--all", "--skip-missing"]) == 0
    out = capsys.readouterr().out
    assert "Corpus absents ou ignorés" in out
    assert "tst : adaptateur absent" in out


def test_download_parser_accepts_force_and_pin() -> None:
    args = cli.build_parser().parse_args(["datasets", "download", "tst", "--force", "--pin"])
    assert args.datasets_command == "download"
    assert args.key == "tst"
    assert args.force is True
    assert args.pin is True


def test_pin_manifest_checksum_preserves_yaml(tmp_path: Path) -> None:
    path = tmp_path / "dataset.yaml"
    path.write_text(
        "integrity:\n  sha256: null # commentaire\nstructure:\n  domain: generic\n",
        encoding="utf-8",
    )
    cli._pin_manifest_checksum(path, "a" * 64)
    content = path.read_text(encoding="utf-8")
    assert 'sha256: "' + "a" * 64 + '" # commentaire' in content


def test_download_success(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_manifest(repo)
    monkeypatch.setattr(cli, "REGISTRY", {"tst": _DownloadAdapter})
    assert cli.main(["datasets", "download", "tst", "--pin"]) == 0
    out = capsys.readouterr().out
    assert "Acquisition de tst terminée" in out
    assert "test-revision" in out
    assert (repo / "data" / "raw" / "tst" / ".acquisition.json").is_file()
    manifest_text = (repo / "configs" / "datasets" / "tst.yaml").read_text(encoding="utf-8")
    assert 'sha256: "' + "a" * 64 + '"' in manifest_text


# --- describe ---------------------------------------------------------------- #


def test_describe_without_lock(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_manifest(repo, spdx="MIT")
    assert cli.main(["datasets", "describe", "tst"]) == 0
    out = capsys.readouterr().out
    assert '"spdx": "MIT"' in out
    assert "non ingéré" in out


# --- audit-licenses ----------------------------------------------------------- #


def test_audit_licenses_incomplete_exits_1(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Critère A-3 : code ≠ 0 si un manifeste est incomplet."""
    _write_manifest(repo, spdx="UNKNOWN")
    assert cli.main(["datasets", "audit-licenses"]) == 1
    err = capsys.readouterr().err
    assert "tst" in err


def test_audit_licenses_non_spdx_string_incomplete(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """« à decidir » n'est pas un identifiant SPDX → incomplet."""
    _write_manifest(repo, spdx="à decidir")
    assert cli.main(["datasets", "audit-licenses"]) == 1


def test_audit_licenses_complete_exits_0(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_manifest(repo, spdx="MIT")
    assert cli.main(["datasets", "audit-licenses"]) == 0
    out = capsys.readouterr().out
    assert "MIT" in out
    assert "bloquant" not in out


# --- ingest ------------------------------------------------------------------ #


def test_ingest_requires_registered_adapter(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_manifest(repo)
    monkeypatch.setattr(cli, "REGISTRY", {})
    assert cli.main(["datasets", "ingest", "tst"]) == 2
    err = capsys.readouterr().err
    assert "non implémenté" in err


def test_ingest_success_writes_lock(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_manifest(repo)
    monkeypatch.setattr(cli, "REGISTRY", {"tst": _TstAdapter})
    assert cli.main(["datasets", "ingest", "tst"]) == 0
    out = capsys.readouterr().out
    assert "statut=official" in out
    lock = repo / "data" / "processed" / "tst" / ".manifest.lock.json"
    assert lock.is_file()


def test_ingest_source_missing_is_failure(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Source locale absente → rc 1, message actionnable, pas de traceback."""
    _write_manifest(repo)
    (repo / "corpus").rename(repo / "corpus_moved")
    monkeypatch.setattr(cli, "REGISTRY", {"tst": _TstAdapter})
    assert cli.main(["datasets", "ingest", "tst"]) == 1
    err = capsys.readouterr().err
    assert "Échec de l'ingestion" in err
    assert not (repo / "data" / "processed" / "tst").exists()


# --- validate / stats après ingestion ------------------------------------------ #


def test_validate_after_ingest(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_manifest(repo)
    monkeypatch.setattr(cli, "REGISTRY", {"tst": _TstAdapter})
    cli.main(["datasets", "ingest", "tst"])
    assert cli.main(["datasets", "validate", "tst"]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out


def test_stats_after_ingest(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_manifest(repo)
    monkeypatch.setattr(cli, "REGISTRY", {"tst": _TstAdapter})
    cli.main(["datasets", "ingest", "tst"])
    assert cli.main(["datasets", "stats", "tst"]) == 0
    out = capsys.readouterr().out
    assert "documents : 1" in out
    assert "by_language" in out

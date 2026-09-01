"""Tests de la commande ``anonv2 predict`` (ticket C-3, SPEC-10 §5, §10).

Corpus d'épreuve : le pivot micro (``tests/fixtures/micro``), répliqué
dans un répertoire temporaire hermetique (aucun téléchargement) ; le
module ``predict`` est ré-ancré dessus par monkey-patching de sa racine
``processed``.

Couvre l'acceptation C-3 :
* les trois artefacts écrits (``predictions.jsonl``, ``traces.jsonl``,
  ``manifest.lock.json``) ;
* la ligne de prédiction : ``error`` toujours présent (jamais de
  prédiction vide silencieuse, audit §12.5), ``runtime_ms`` nul en profil
  strict ;
* la fuite gold détectée par recherche exacte **indépendamment du
  détecteur** (email ``jean.dupont@example.com`` refusé par le détecteur
  via ``deny_context``) marque le document ``partial`` ;
* deux runs bit-à-bit identiques (SPEC-10 §10) ;
* le lock : sept éléments de reproductibilité (SPEC-09 §5), commit git
  courant, ``status`` ``complete`` / ``sampled`` selon ``--limit`` ;
* l'exclusion par budget (contrainte C4) : ligne ``status="error"``,
  ``error`` rempli, texte non anonymisé ;
* échecs d'usage actionnables : pivot manquant (message pointant vers
  ``ingest``), politique inconnue, dataset inconnu.

Le pivot réel ``openpii`` (s'il est ingéré localement) est couvert par
un échantillonnage marqué ``requires_data``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pour `import fixtures`

from fixtures import load_micro  # noqa: E402

from anonymisation.cli import predict  # noqa: E402
from anonymisation.cli.main import main  # noqa: E402
from anonymisation.schema.models import SCHEMA_VERSION, Document  # noqa: E402
from anonymisation.schema.taxonomy import TAXONOMY_VERSION  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = REPO_ROOT / "configs" / "policy" / "policies.yaml"
OPENPII_PIVOT = REPO_ROOT / "data" / "processed" / "openpii"


# --------------------------------------------------------------------------- #
# Pivot micro temporaire (source de vérité de la commande)
# --------------------------------------------------------------------------- #
def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_pivot(root: Path, key: str, split: str, docs: list, anns: list) -> None:
    """Écrit ``root/<key>/<split>/`` (documents, annotations, lock d'ingestion)."""
    base = root / key / split
    base.mkdir(parents=True, exist_ok=True)
    docs_path = base / "documents.jsonl"
    anns_path = base / "annotations.jsonl"
    with docs_path.open("w", encoding="utf-8") as fh:
        for doc in docs:
            fh.write(json.dumps(doc.model_dump(mode="json"), ensure_ascii=False) + "\n")
    with anns_path.open("w", encoding="utf-8") as fh:
        for ann in anns:
            fh.write(json.dumps(ann.model_dump(mode="json"), ensure_ascii=False) + "\n")
    lock = {
        "manifest": {"key": key, "splits": [split]},
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "source": {
            "kind": "local",
            "directory": str(base),
            "files": [str(docs_path), str(anns_path)],
            "fingerprint": None,
        },
        "files": {
            f"{split}/documents.jsonl": _sha(docs_path),
            f"{split}/annotations.jsonl": _sha(anns_path),
        },
        "date": "2026-01-01",  # date figée : le lock est un artefact de test
        "status": "official",
    }
    (root / key / predict.LOCK_NAME).write_text(
        json.dumps(lock, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )


@pytest.fixture
def micro_pivot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pivot micro temporaire + ré-ancrage de la racine ``processed``."""
    root = tmp_path / "processed"
    micro = load_micro()
    _write_pivot(root, "micro", "train", micro["documents"], micro["annotations"])
    monkeypatch.setattr(predict, "PROCESSED_ROOT", root)
    return root


def _predict(out: Path, *extra: str, dataset: str = "micro") -> int:
    return main(
        [
            "predict",
            "--dataset",
            dataset,
            "--split",
            "train",
            "--policy",
            "P2",
            "--profile",
            "deterministic",
            "--out",
            str(out),
            *extra,
        ]
    )


def _predictions(out: Path) -> dict[str, dict]:
    lines = out.joinpath("predictions.jsonl").read_text(encoding="utf-8").splitlines()
    return {json.loads(line)["doc_id"]: json.loads(line) for line in lines}


def _lock(out: Path) -> dict:
    return json.loads(out.joinpath("manifest.lock.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Artefacts écrits
# --------------------------------------------------------------------------- #
def test_predict_writes_three_artifacts(micro_pivot: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "run1"
    rc = _predict(out)
    assert rc == 0  # aucun document en erreur (d5 est « partial », pas « error »)
    assert (out / "predictions.jsonl").is_file()
    assert (out / "traces.jsonl").is_file()
    assert (out / "manifest.lock.json").is_file()
    predictions = out.joinpath("predictions.jsonl").read_text(encoding="utf-8").splitlines()
    traces = out.joinpath("traces.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(predictions) == 5
    assert len(traces) == 5 * 8  # huit traces par document, jamais d'absence
    captured = capsys.readouterr()
    assert "5 document(s)" in captured.out


def test_prediction_line_shape(micro_pivot: Path, tmp_path: Path) -> None:
    """``error`` est toujours présent ; ``runtime_ms`` nul en profil strict."""
    out = tmp_path / "run1"
    assert _predict(out) == 0
    for line in out.joinpath("predictions.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        assert set(rec) == {
            "doc_id",
            "status",
            "error",
            "annotations",
            "decisions",
            "anonymized_text",
            "risk",
            "runtime_ms",
        }
        assert isinstance(rec["error"], list)  # jamais absent, jamais null
        assert rec["status"] in ("ok", "partial", "error")
        assert rec["runtime_ms"] == 0.0  # strict (SPEC-10 §10)


def test_gold_leak_independent_of_detector_marks_partial(
    micro_pivot: Path, tmp_path: Path
) -> None:
    """L'email refusé par le détecteur (``deny_context``) survit ; la
    recherche exacte sur les valeurs gold le détecte → document ``partial``."""
    out = tmp_path / "run1"
    assert _predict(out) == 0
    lines = _predictions(out)
    d5 = lines["micro:d5"]
    assert d5["status"] == "partial"
    assert d5["error"], "la fuite gold est journalisée dans la ligne"
    # Le détecteur n'a pas émis de décision pour cet email (deny_context) :
    # le texte n'a donc pas été anonymisé — seule la validation lève l'alerte.
    assert "jean.dupont@example.com" in d5["anonymized_text"]
    for doc_id in ("micro:d1", "micro:d2", "micro:d3", "micro:d4"):
        assert lines[doc_id]["status"] == "ok"
        assert lines[doc_id]["error"] == []


# --------------------------------------------------------------------------- #
# Déterminisme bit à bit (SPEC-10 §10)
# --------------------------------------------------------------------------- #
def test_predict_bit_identical(micro_pivot: Path, tmp_path: Path) -> None:
    out1, out2 = tmp_path / "run1", tmp_path / "run2"
    assert _predict(out1) == 0
    assert _predict(out2) == 0
    for name in ("predictions.jsonl", "traces.jsonl", "manifest.lock.json"):
        assert out1.joinpath(name).read_bytes() == out2.joinpath(name).read_bytes(), name


# --------------------------------------------------------------------------- #
# Lock : sept éléments de reproductibilité (SPEC-09 §5)
# --------------------------------------------------------------------------- #
def test_lock_seven_elements_and_git_commit(micro_pivot: Path, tmp_path: Path) -> None:
    out = tmp_path / "run1"
    assert _predict(out) == 0
    lock = _lock(out)

    # Les sept éléments, un par un.
    assert lock["data_version"]["taxonomy_version"] == TAXONOMY_VERSION
    assert lock["data_version"]["files"]["train/documents.jsonl"]
    assert lock["taxonomy_version"] == TAXONOMY_VERSION
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert lock["code"]["git_commit"] == head
    assert lock["models"] == []  # v1 : aucun modèle (détecteur déterministe)
    assert lock["seeds"]["determinism"] == 42
    assert lock["prompts"] == []  # v1 : pas d'étape LLM
    assert lock["policy"]["id"] == "P2"
    assert lock["policy"]["sha256"] == _sha(POLICY_FILE)

    # Comptabilité de run.
    run = lock["run"]
    assert run["status"] == "complete"  # pas de --limit
    assert run["limit"] is None
    assert run["documents_total"] == 5
    assert run["documents_ok"] + run["documents_partial"] + run["documents_error"] == 5
    assert run["documents_error"] == 0


# --------------------------------------------------------------------------- #
# --limit : échantillonnage
# --------------------------------------------------------------------------- #
def test_limit_marks_sampled(micro_pivot: Path, tmp_path: Path) -> None:
    out = tmp_path / "run1"
    assert _predict(out, "--limit", "2") == 0
    lines = _predictions(out)
    assert list(lines) == ["micro:d1", "micro:d2"]  # ordre du fichier, premier N
    lock = _lock(out)
    assert lock["run"]["status"] == "sampled"
    assert lock["run"]["limit"] == 2
    assert lock["run"]["documents_total"] == 2


def test_limit_zero_rejected(micro_pivot: Path, tmp_path: Path, capsys) -> None:
    rc = _predict(tmp_path / "run1", "--limit", "0")
    assert rc == 2
    assert "strictement positif" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Exclusion par budget (contrainte C4)
# --------------------------------------------------------------------------- #
def test_budget_exclusion_is_error(micro_pivot: Path, tmp_path: Path) -> None:
    """Un document hors budget est marqué ``error`` (jamais prédiction
    vide) ; son texte n'est pas anonymisé."""
    root = tmp_path / "processed"
    micro = load_micro()
    big_text = "a" * 200_001
    big = Document.model_validate(
        {**micro["documents"][0].model_dump(), "doc_id": "ov:d2", "text": big_text}
    )
    _write_pivot(root, "oversized", "train", [micro["documents"][0], big], [])
    out = tmp_path / "run1"
    rc = _predict(out, dataset="oversized")
    assert rc == 1  # au moins un document en erreur
    lines = _predictions(out)
    assert lines["micro:d1"]["status"] == "ok"
    big_line = lines["ov:d2"]
    assert big_line["status"] == "error"
    assert big_line["error"], "l'erreur porte le détail de l'exclusion"
    assert "budget" in big_line["error"][0]
    assert big_line["anonymized_text"] == big_text  # non anonymisé, tel quel
    lock = _lock(out)
    assert lock["run"]["documents_error"] == 1


# --------------------------------------------------------------------------- #
# Échecs d'usage actionnables
# --------------------------------------------------------------------------- #
def test_missing_pivot_points_to_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(predict, "PROCESSED_ROOT", tmp_path / "absent")
    rc = main(
        [
            "predict",
            "--dataset",
            "openpii",
            "--split",
            "train",
            "--policy",
            "P2",
            "--profile",
            "deterministic",
            "--out",
            str(tmp_path / "run1"),
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "anonv2 datasets ingest openpii --split train" in err


def test_unknown_policy_rejected(micro_pivot: Path, tmp_path: Path, capsys) -> None:
    rc = main(
        [
            "predict",
            "--dataset",
            "micro",
            "--split",
            "train",
            "--policy",
            "P99",
            "--profile",
            "deterministic",
            "--out",
            str(tmp_path / "run2"),
        ]
    )
    assert rc == 2
    assert "Politique inconnue" in capsys.readouterr().err


def test_unknown_dataset_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(predict, "PROCESSED_ROOT", tmp_path / "absent")
    rc = main(
        [
            "predict",
            "--dataset",
            "nope",
            "--split",
            "train",
            "--policy",
            "P2",
            "--profile",
            "deterministic",
            "--out",
            str(tmp_path / "run1"),
        ]
    )
    assert rc == 2
    assert "Dataset inconnu" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Pivot réel openpii (échantillonnage — le run complet se fait hors pytest)
# --------------------------------------------------------------------------- #
@pytest.mark.requires_data
def test_openpii_validation_sample_zero_error(tmp_path: Path) -> None:
    if not (OPENPII_PIVOT / "train" / "documents.jsonl").is_file():
        pytest.skip("pivot openpii absent localement (aucun ingest fait)")
    out = tmp_path / "run1"
    rc = main(
        [
            "predict",
            "--dataset",
            "openpii",
            "--split",
            "train",
            "--policy",
            "P2",
            "--profile",
            "deterministic",
            "--out",
            str(out),
            "--limit",
            "300",
        ]
    )
    assert rc == 0, "zéro document en erreur sur l'échantillon"
    lock = _lock(out)
    assert lock["run"]["documents_error"] == 0
    assert lock["run"]["status"] == "sampled"
    assert lock["data_version"]["files"]["train/documents.jsonl"]

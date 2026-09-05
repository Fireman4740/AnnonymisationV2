"""Commande ``anonv2 score`` (C-4, SPEC-10 §5, audit §12.6).

Le scoring ne charge ni détecteur ni modèle : il relit uniquement les
prédictions, le pivot gold et le lock figé par ``predict``. Une modification
des métriques peut donc être rejouée sans campagne de prédiction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from anonymisation.metrics.contracts import MetricStatus
from anonymisation.metrics.scorecard import (
    ScorecardError,
    build_scorecard,
    validate_reproducibility,
)
from anonymisation.schema.io import read_jsonl, write_json
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import TAXONOMY_VERSION

REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_ROOT = REPO_ROOT / "data" / "processed"
DATASETS_CONFIG = REPO_ROOT / "configs" / "datasets"
LOCK_NAME = "manifest.lock.json"
PREDICTIONS_NAME = "predictions.jsonl"
SCORECARD_NAME = "scorecard.json"


class ScoreError(ValueError):
    """Erreur de run, de protocole ou de pivot gold actionnable."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScoreError(f"Fichier JSON illisible : {path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise ScoreError(f"Fichier JSON invalide : {path} (mapping attendu)")
    return payload


def _read_predictions(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ScoreError(f"Prédictions absentes : {path}")
    records: list[dict[str, Any]] = []
    line_number: int | str = "?"
    try:
        with path.open("r", encoding="utf-8") as handle:
            for _line_number, raw_line in enumerate(handle, start=1):
                line_number = _line_number
                if not raw_line.strip():
                    continue
                payload = json.loads(raw_line)
                if not isinstance(payload, dict):
                    raise ValueError("mapping attendu")
                if not payload.get("doc_id"):
                    raise ValueError("doc_id absent")
                records.append(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ScoreError(f"Prédiction invalide : {path}:{line_number} ({exc})") from exc
    return records


def _protocol_info(dataset: str, requested: str) -> tuple[str, str, MetricStatus]:
    """Résout version/statut depuis le manifeste, sans charger le pipeline."""
    config = DATASETS_CONFIG / f"{dataset}.yaml"
    if not config.is_file():
        return requested, "1", MetricStatus.DIAGNOSTIC
    try:
        raw = yaml.safe_load(config.read_text(encoding="utf-8"))
        evaluation = raw.get("evaluation", {}) if isinstance(raw, dict) else {}
    except (OSError, yaml.YAMLError) as exc:
        raise ScoreError(f"Manifeste illisible pour {dataset!r} : {config} ({exc})") from exc
    declared = evaluation.get("protocol")
    if declared and declared != requested:
        raise ScoreError(
            f"Protocole incompatible : le dataset {dataset!r} déclare {declared!r}, "
            f"pas {requested!r}"
        )
    version = str(evaluation.get("protocol_version", "1"))
    raw_status = str(evaluation.get("default_metric_status", "DIAGNOSTIC")).lower()
    try:
        status = MetricStatus(raw_status)
    except ValueError:
        status = MetricStatus.DIAGNOSTIC
    return requested, version, status


def _load_gold(
    dataset: str, split: str
) -> tuple[dict[str, Document], dict[str, tuple[Annotation, ...]]]:
    base = PROCESSED_ROOT / dataset / split
    documents_path = base / "documents.jsonl"
    annotations_path = base / "annotations.jsonl"
    if not documents_path.is_file() or not annotations_path.is_file():
        raise ScoreError(
            f"Pivot gold absent pour {dataset!r} / split {split!r} "
            f"(attendus : {documents_path} et {annotations_path})"
        )
    try:
        documents = {
            document.doc_id: document
            for document in read_jsonl(documents_path, Document)
        }
        grouped: dict[str, list[Annotation]] = {}
        for annotation in read_jsonl(annotations_path, Annotation):
            grouped.setdefault(annotation.doc_id, []).append(annotation)
    except (OSError, ValueError) as exc:
        raise ScoreError(f"Pivot gold invalide : {base} ({exc})") from exc
    return documents, {doc_id: tuple(values) for doc_id, values in grouped.items()}


def cmd_score(run: str | Path, protocol: str) -> int:
    """Calcule ``scorecard.json`` depuis un run figé, sans modèle.

    Retourne 1 si le taux d'erreur dépasse 5 % (avertissement bloquant C-5),
    tout en écrivant la scorecard pour permettre l'audit ; retourne 0 sinon.
    """
    run_dir = Path(run)
    lock_path = run_dir / LOCK_NAME
    if not lock_path.is_file():
        raise ScoreError(f"Lock de run absent : {lock_path} — exécute d'abord predict")
    lock = _read_json(lock_path)
    if lock.get("taxonomy_version") != TAXONOMY_VERSION:
        raise ScoreError(
            "taxonomy_version incompatible : "
            f"run={lock.get('taxonomy_version')!r}, code={TAXONOMY_VERSION!r}. "
            "Reprédiction requise (re-predict) avant score."
        )
    try:
        validate_reproducibility(lock)
        run_info = lock["run"]
        dataset = str(run_info["dataset"])
        split = str(run_info["split"])
    except (KeyError, TypeError, ScorecardError) as exc:
        raise ScoreError(f"Lock de run invalide : {exc}") from exc

    predictions = _read_predictions(run_dir / PREDICTIONS_NAME)
    documents, gold = _load_gold(dataset, split)
    protocol_name, protocol_version, default_status = _protocol_info(dataset, protocol)
    try:
        scorecard = build_scorecard(
            run_id=run_dir.name,
            dataset=dataset,
            split=split,
            protocol=protocol_name,
            protocol_version=protocol_version,
            predictions=predictions,
            gold_by_doc=gold,
            documents_by_doc=documents,
            reproducibility=lock,
            requested_status=default_status,
        )
    except (TypeError, ValueError) as exc:
        raise ScoreError(f"Scorecard impossible à calculer : {exc}") from exc
    write_json(run_dir / SCORECARD_NAME, scorecard)
    accounting = scorecard["accounting"]
    print(
        f"score : {accounting['documents_scored']} document(s) scoré(s), "
        f"taux d'erreur {accounting['error_rate']:.2%} — {run_dir / SCORECARD_NAME}"
    )
    warning = accounting.get("warning")
    if warning:
        print(f"AVERTISSEMENT BLOQUANT : {warning}")
        return 1
    return 0

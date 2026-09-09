"""Commande ``anonv2 score`` (C-4, SPEC-10 §5, audit §12.6).

Le scoring ne charge ni détecteur ni modèle : il relit uniquement les
prédictions, le pivot gold et le lock figé par ``predict``. Une modification
des métriques peut donc être rejouée sans campagne de prédiction.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from anonymisation.metrics.contracts import MetricStatus
from anonymisation.metrics.downstream import evaluate_downstream_task
from anonymisation.metrics.scorecard import (
    ScorecardError,
    build_scorecard,
    validate_reproducibility,
)
from anonymisation.schema.io import read_jsonl, write_json
from anonymisation.schema.models import Annotation, Document, TaskLabel
from anonymisation.schema.taxonomy import TAXONOMY_VERSION

REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_ROOT = REPO_ROOT / "data" / "processed"
DATASETS_CONFIG = REPO_ROOT / "configs" / "datasets"
LOCK_NAME = "manifest.lock.json"
PREDICTIONS_NAME = "predictions.jsonl"
SCORECARD_NAME = "scorecard.json"
TASKS_NAME = "tasks.jsonl"
DOCUMENTS_NAME = "documents.jsonl"


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


def _load_tasks(dataset: str, split: str) -> list[TaskLabel]:
    """Labels de tâche aval du split, ou liste vide si le fichier n'existe pas.

    L'absence de fichier est un cas légitime (corpus sans tâche aval) ; un
    fichier illisible ne l'est pas : le confondre avec l'absence ferait
    rapporter « aucune tâche downstream déclarée » sur des données corrompues.
    """
    tasks_path = PROCESSED_ROOT / dataset / split / TASKS_NAME
    if not tasks_path.is_file():
        return []
    try:
        return list(read_jsonl(tasks_path, TaskLabel))
    except (OSError, ValueError) as exc:
        raise ScoreError(f"Tâches aval illisibles ({tasks_path}) : {exc}") from exc


def _load_train_data(dataset: str) -> tuple[list[Document], list[TaskLabel]]:
    """Corpus d'entraînement de la tâche aval, ou ``([], [])`` s'il est absent."""
    train_dir = PROCESSED_ROOT / dataset / "train"
    docs_path = train_dir / DOCUMENTS_NAME
    tasks_path = train_dir / TASKS_NAME
    if not docs_path.is_file() or not tasks_path.is_file():
        return [], []
    try:
        docs = list(read_jsonl(docs_path, Document))
        tasks = list(read_jsonl(tasks_path, TaskLabel))
    except (OSError, ValueError) as exc:
        raise ScoreError(
            f"Corpus d'entraînement aval illisible ({train_dir}) : {exc}"
        ) from exc
    return docs, tasks

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
    protocol_name, protocol_version, default_status = _protocol_info(dataset, protocol)
    predictions = _read_predictions(run_dir / PREDICTIONS_NAME)
    documents, gold = _load_gold(dataset, split)
    eval_tasks = _load_tasks(dataset, split)
    # Le classifieur aval s'entraîne sur `train` : évaluer sur ce même split
    # reviendrait à mesurer la rétention d'utilité en train-sur-test, ce qui
    # gonfle mécaniquement `score_original` et donc `utility_retention`.
    downstream_eligible = bool(eval_tasks) and split != "train"
    train_docs, train_tasks = _load_train_data(dataset) if downstream_eligible else ([], [])

    downstream_results = []
    if downstream_eligible and train_docs and train_tasks:
        # Un document sans prédiction n'a PAS été anonymisé : le comparer à
        # lui-même le ferait passer pour parfaitement préservé et gonflerait
        # la rétention. On l'exclut de l'évaluation aval.
        anon_by_doc = {
            str(record.get("doc_id")): str(record.get("anonymized_text") or "")
            for record in predictions
            if record.get("anonymized_text") is not None
        }
        eval_docs_orig = [doc for doc in documents.values() if doc.doc_id in anon_by_doc]
        eval_docs_anon = [anon_by_doc[doc.doc_id] for doc in eval_docs_orig]
        for t_name in sorted({t.task for t in eval_tasks}):
            downstream_results.append(
                evaluate_downstream_task(
                    task_name=t_name,
                    train_docs=train_docs,
                    train_tasks=train_tasks,
                    eval_docs_orig=eval_docs_orig,
                    eval_docs_anon=eval_docs_anon,
                    eval_tasks=eval_tasks,
                )
            )
    try:
        # L'identité du système commande quelles métriques sont applicables.
        # On refuse plutôt que de supposer : supposer la détection produirait
        # des zéros sur les boîtes noires, supposer l'inverse ferait
        # disparaître l'axe A des pipelines riches.
        system_block = lock.get("system")
        if not isinstance(system_block, Mapping):
            raise ScoreError(
                "Lock de run sans bloc « system » : run produit avant "
                "l'introduction de l'identité de système. Relancez "
                "« anonv2 predict »."
            )

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
            system=system_block,
            requested_status=default_status,
            downstream_results=downstream_results if downstream_results else None,
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

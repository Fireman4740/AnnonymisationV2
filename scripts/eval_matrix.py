"""Cartographie de l'évaluation : chaque corpus × système × métrique, sur N documents.

But : vérifier que la chaîne ``predict`` → ``score`` est **implémentée
correctement** sur chaque corpus ingéré, pas mesurer la qualité d'un système.
Pour chaque corpus ingéré et chaque système déterministe enregistré :

1. ``predict --limit N`` deux fois dans deux répertoires distincts ;
2. ``score`` sur chacun ;
3. contrôle de **reproductibilité** : prédictions et scorecards identiques
   bit à bit entre les deux passages ;
4. contrôle des **ancres de sanité** : ``passthrough`` ne protège rien,
   ``redact_all`` protège tout, les systèmes sans capacité ``spans`` n'ont pas
   de métrique de spans (``UNAVAILABLE``, jamais 0.0) ;
5. **oracle** : un run synthétique dont les prédictions sont le gold et dont
   le texte masque exactement les spans gold. Les métriques de détection
   DOIVENT y valoir 1.0 — sinon c'est la métrique qui est fausse, pas le
   système. Il est fabriqué ici (jamais enregistré comme système : un système
   qui lit le gold n'est pas un concurrent publiable).

Les pivots sources sont lus en lecture seule via des liens symboliques : le
script ne modifie jamais ``data/processed`` de la source. Un pivot dont les
empreintes ne correspondent plus à son lock d'ingestion est **signalé**, pas
contourné.

Usage ::

    PYTHONPATH=src uv run --locked --extra datasets --extra metrics \\
        python scripts/eval_matrix.py --processed <dir> --out <dir> --limit 2
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any

import yaml

from anonymisation.cli import predict, score
from anonymisation.cli.main import main as cli_main
from anonymisation.schema.io import read_jsonl, write_json
from anonymisation.schema.models import Annotation, Document

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS_CONFIG = REPO_ROOT / "configs" / "datasets"

#: Split évalué par corpus : le premier split présent dans cet ordre.
SPLIT_PREFERENCE = ("test", "eval", "validation", "hard_quasi_id", "dev")
#: Systèmes déterministes (C1/C2 : aucun LLM dans la cartographie).
SYSTEMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("passthrough", ()),
    ("oracle", ()),
    ("redact-all", ("--param", "replacement=[SUPPRIME]")),
    ("regex-only", ()),
    ("deterministic", ("--policy", "P2")),
)
PRIMARY = ("cpr", "ipr", "trir", "reid_success_rate", "utility_retention")
DIAGNOSTIC = (
    "span_precision", "span_recall", "span_f1", "weighted_token_precision",
    "ER_di", "ER_qi", "rouge_l", "mean_utility", "gold_leak_rate",
)
SPAN_METRICS = ("span_precision", "span_recall", "span_f1", "ER_di", "ER_qi")


def _protocol(dataset: str) -> str:
    raw = yaml.safe_load((DATASETS_CONFIG / f"{dataset}.yaml").read_text(encoding="utf-8"))
    return str(raw["evaluation"]["protocol"])


def _split(dataset_dir: Path) -> str | None:
    present = sorted(p.name for p in dataset_dir.iterdir() if (p / "documents.jsonl").is_file())
    for candidate in SPLIT_PREFERENCE:
        if candidate in present:
            return candidate
    return present[0] if present else None


def _quiet(func: Any, *args: Any) -> tuple[Any, str]:
    """Exécute ``func`` en capturant stdout/stderr ; renvoie (résultat, sortie)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        result = func(*args)
    return result, buffer.getvalue()


def _metric(card: dict[str, Any], block: str, name: str) -> dict[str, Any]:
    metric = card.get(block, {}).get(name) if block != "top" else card.get(name)
    if not isinstance(metric, dict):
        return {"value": None, "status": "absent"}
    details = metric.get("details") or {}
    ci = details.get("ci95")
    return {
        "value": metric.get("value"),
        "status": metric.get("status"),
        "reason": details.get("reason"),
        "ci95": [ci.get("low"), ci.get("high")] if isinstance(ci, dict) and "low" in ci else None,
    }


def _run_once(dataset: str, split: str, system: str, extra: tuple[str, ...],
              out: Path, limit: int) -> dict[str, Any]:
    argv = ["predict", "--dataset", dataset, "--split", split, "--system", system,
            *extra, "--profile", "deterministic", "--out", str(out), "--limit", str(limit)]
    rc, log = _quiet(cli_main, argv)
    if not (out / "predictions.jsonl").is_file():
        return {"stage": "predict", "rc": rc, "error": log.strip().splitlines()[-1:] or [""]}
    try:
        _, log = _quiet(score.cmd_score, out, _protocol(dataset))
    except Exception as exc:  # noqa: BLE001 — la cartographie doit tout recenser
        return {"stage": "score", "error": [f"{type(exc).__name__}: {exc}"]}
    card = json.loads((out / "scorecard.json").read_text(encoding="utf-8"))
    return {"stage": "ok", "predict_rc": rc, "card": card}


def _mask(text: str, annotations: list[dict[str, Any]]) -> str:
    """Remplace chaque span gold localisé par ``[X]`` (spans fusionnés si chevauchants)."""
    spans = sorted(
        (a["start"], a["end"]) for a in annotations
        if a.get("start") is not None and a.get("end") is not None
    )
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    for start, end in reversed(merged):
        text = text[:start] + "[X]" + text[end:]
    return text


def _oracle_once(dataset: str, split: str, source_run: Path, target: Path) -> dict[str, Any]:
    """Run « oracle » dérivé d'un run passthrough : prédictions = gold, spans masqués."""
    if not (source_run / "predictions.jsonl").is_file():
        return {"stage": "predict", "error": ["run passthrough source absent"]}
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source_run, target)
    (target / "scorecard.json").unlink(missing_ok=True)
    base = predict.PROCESSED_ROOT / dataset / split
    texts = {d.doc_id: d.text for d in read_jsonl(base / "documents.jsonl", Document)}
    gold: dict[str, list[dict[str, Any]]] = {}
    if (base / "annotations.jsonl").is_file():
        for ann in read_jsonl(base / "annotations.jsonl", Annotation):
            gold.setdefault(ann.doc_id, []).append(ann.model_dump(mode="json"))
    lines = []
    for raw in (target / "predictions.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(raw)
        annotations = gold.get(record["doc_id"], [])
        record["annotations"] = annotations
        record["anonymized_text"] = _mask(texts[record["doc_id"]], annotations)
        lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
    (target / "predictions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    lock_path = target / "manifest.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["system"] = {
        "system_id": "oracle-matrix", "system_version": "1", "capabilities": ["spans"],
        "params_digest": "0" * 64, "oracle": True,
    }
    lock["outputs"]["predictions.jsonl"] = hashlib.sha256(
        (target / "predictions.jsonl").read_bytes()
    ).hexdigest()
    write_json(lock_path, lock)
    try:
        _quiet(score.cmd_score, target, _protocol(dataset))
    except Exception as exc:  # noqa: BLE001
        return {"stage": "score", "error": [f"{type(exc).__name__}: {exc}"]}
    return {"stage": "ok", "card": json.loads((target / "scorecard.json").read_text(encoding="utf-8"))}


def _sanity(system: str, metrics: dict[str, dict[str, Any]]) -> list[str]:
    """Violations des ancres attendues (vide = conforme)."""
    issues: list[str] = []
    cpr = metrics["cpr"]["value"]
    if system == "passthrough":
        if cpr not in (None, 0.0):
            issues.append(f"passthrough : CPR attendu 0, obtenu {cpr}")
        if metrics["rouge_l"]["value"] not in (None, 1.0):
            issues.append(f"passthrough : ROUGE-L attendu 1, obtenu {metrics['rouge_l']['value']}")
    if system == "redact-all":
        if cpr not in (None, 1.0):
            issues.append(f"redact-all : CPR attendu 1, obtenu {cpr}")
        leak = metrics["gold_leak_rate"]["value"]
        if leak not in (None, 0.0):
            issues.append(f"redact-all : fuite gold attendue 0, obtenue {leak}")
    if system == "oracle":
        for name in SPAN_METRICS:
            value = metrics[name]["value"]
            if value is not None and abs(value - 1.0) > 1e-9:
                issues.append(f"oracle : {name} attendu 1.0, obtenu {value}")
    if system in ("passthrough", "redact-all"):
        for name in SPAN_METRICS:
            if metrics[name]["status"] != "unavailable":
                issues.append(f"{system} : {name} devrait être UNAVAILABLE (pas de capacité spans)")
    for name, metric in metrics.items():
        ci = metric.get("ci95")
        value = metric.get("value")
        if ci and isinstance(value, (int, float)) and not (ci[0] - 1e-9 <= value <= ci[1] + 1e-9):
            issues.append(f"{name} : valeur {value} hors de son IC {ci}")
    return issues


def run_matrix(
    processed: Path, out: Path, limit: int, only: tuple[str, ...] = ()
) -> dict[str, Any]:
    workspace = out / "processed"
    workspace.mkdir(parents=True, exist_ok=True)
    datasets = sorted(p.name for p in processed.iterdir()
                      if p.is_dir() and (DATASETS_CONFIG / f"{p.name}.yaml").is_file()
                      and (not only or p.name in only))
    for name in datasets:
        link = workspace / name
        if not link.exists():
            link.symlink_to((processed / name).resolve(), target_is_directory=True)
    predict.PROCESSED_ROOT = workspace
    score.PROCESSED_ROOT = workspace

    results: list[dict[str, Any]] = []
    for dataset in datasets:
        split = _split(workspace / dataset)
        for system, extra in SYSTEMS:
            row: dict[str, Any] = {"dataset": dataset, "split": split, "system": system}
            if split is None:
                row.update(stage="ingest", error=["aucun split avec documents.jsonl"])
                results.append(row)
                continue
            runs = []
            for repeat in (1, 2):
                target = out / "runs" / f"{system}-{dataset}-{split}-r{repeat}"
                try:
                    if system == "oracle":
                        source = out / "runs" / f"passthrough-{dataset}-{split}-r{repeat}"
                        runs.append((target, _oracle_once(dataset, split, source, target)))
                        continue
                    runs.append((target, _run_once(dataset, split, system, extra, target, limit)))
                except Exception as exc:  # noqa: BLE001
                    runs.append((target, {"stage": "crash", "error": [
                        f"{type(exc).__name__}: {exc}", traceback.format_exc(limit=2)]}))
            first_dir, first = runs[0]
            second_dir, second = runs[1]
            row["stage"] = first["stage"]
            if first["stage"] != "ok":
                row["error"] = first["error"]
                results.append(row)
                continue
            card = first["card"]
            metrics = {name: _metric(card, "primary", name) for name in PRIMARY}
            metrics |= {name: _metric(card, "diagnostic", name) for name in DIAGNOSTIC}
            metrics["macro_f1"] = _metric(card, "top", "macro_f1")
            row.update(
                documents=card["accounting"]["documents_total"],
                error_rate=card["error_rate"],
                publishable=card["publishable"],
                blockers=card["publication_blockers"],
                metrics=metrics,
                reproducible=(
                    second["stage"] == "ok"
                    and (first_dir / "predictions.jsonl").read_bytes()
                    == (second_dir / "predictions.jsonl").read_bytes()
                    and _strip(card) == _strip(second["card"])
                ),
                sanity=_sanity(system, metrics),
            )
            results.append(row)
    return {"limit": limit, "processed": str(processed), "results": results}


def _strip(card: dict[str, Any]) -> dict[str, Any]:
    """Scorecard sans ses champs propres au répertoire de run (run_id, chemins)."""
    return {k: v for k, v in card.items() if k not in ("run_id",)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--processed", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--datasets", nargs="*", default=(), help="restreindre à ces corpus")
    args = parser.parse_args(argv)
    report = run_matrix(args.processed, args.out, args.limit, tuple(args.datasets))
    write_json(args.out / "matrix.json", report)
    failures = [r for r in report["results"] if r["stage"] != "ok" or r.get("sanity")
                or not r.get("reproducible", False)]
    print(f"{len(report['results'])} cellules, {len(failures)} à examiner — {args.out / 'matrix.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

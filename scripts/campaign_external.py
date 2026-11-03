"""Datasets « externes » de la campagne : hors du contrat de cohorte figée.

La cohorte `banc-fiable-200-v2` lie la liste `datasets` de campaign.json à
son manifeste ; y ajouter un corpus casserait sa restauration (et une cohorte
figée ne se reconstruit jamais). Un corpus dont la sélection officielle est
figée ailleurs — QuasiLeak-Bench : partition par profil de l'article — entre
donc par `external_datasets`, avec ses propres sélections verrouillées.

Pour QuasiLeak, ce module ajoute à la boucle commune (predict → score →
rejeu → audit) :
- le regroupement LLM de l'annexe D.8 par système (reçoit le profil : à part) ;
- le détecteur natif zéro-shot officiel, une fois par dataset (référence) ;
- la parité : le scorer officiel recopié, exécuté seul (`python -I`, sans le
  code du projet), doit redonner exactement les scores de la scorecard.
Aucune attaque ni utilité n'est inventée : l'article n'en définit pas.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from anonymisation.schema.io import sha256_file, write_json

SUPPORTED = {"quasileak"}
VENDOR_SCORER = Path(__file__).resolve().parents[1] / "src/anonymisation/metrics/vendor/quasileak_score.py"
REQUIRED = ("split", "selection", "selection_sha256", "pivot_selection", "pivot_selection_sha256",
            "protocol", "excluded_selections", "llm_grouping", "native_detector")


def validate_external(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Contrôles sans données ni modèle : empreintes, taille, clés explicites."""
    external = cfg.get("external_datasets") or {}
    if set(external) & set(cfg["datasets"]):
        raise ValueError("campaign.json : un dataset ne peut être à la fois dans `datasets` et `external_datasets`")
    for key, spec in external.items():
        if key not in SUPPORTED:
            raise ValueError(f"external_datasets : {key!r} non pris en charge ({sorted(SUPPORTED)})")
        missing = [name for name in REQUIRED if name not in spec]
        if missing:
            raise ValueError(f"external_datasets.{key} : clés manquantes {missing} (aucun défaut implicite)")
        for name in ("selection", "pivot_selection"):
            path = Path(spec[name])
            if not path.is_file() or sha256_file(path) != spec[f"{name}_sha256"]:
                raise ValueError(f"external_datasets.{key} : {path} absent ou modifié depuis sa fixation")
        ids = json.loads(Path(spec["selection"]).read_text(encoding="utf-8"))
        pivot = json.loads(Path(spec["pivot_selection"]).read_text(encoding="utf-8"))
        rows = pivot["datasets"][key][spec["split"]]
        if [r["doc_id"] for r in rows] != ids or len(set(ids)) != len(ids):
            raise ValueError(f"external_datasets.{key} : sélection et manifeste pivot divergents")
        expected = (cfg.get("evaluation_subset") or {}).get("documents_per_dataset")
        if expected is not None and len(ids) != expected:
            raise ValueError(f"external_datasets.{key} : {len(ids)} documents ≠ {expected} par dataset de la campagne")
        for excluded in spec["excluded_selections"]:
            if set(json.loads(Path(excluded).read_text(encoding="utf-8"))) & set(ids):
                raise ValueError(f"external_datasets.{key} : recouvre {excluded} (sélection de développement)")
    return external


def prepare_external(key: str, spec: dict[str, Any], root: Path, command) -> dict[str, Any]:
    """Acquisition vérifiée, ingestion du split complet, profils disjoints."""
    from fetch_quasileak import fetch

    source = fetch(root)
    if command(["datasets", "ingest", key, "--split", spec["split"]]):
        raise ValueError(f"{key} : ingestion échouée")
    ids = json.loads(Path(spec["selection"]).read_text(encoding="utf-8"))
    profiles = {}
    with (source / "quasileak_bench_data_full.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            profiles[row["sample_id"]] = row["profile"]["profile_id"]
    excluded = {profiles[i] for path in spec["excluded_selections"]
                for i in json.loads(Path(path).read_text(encoding="utf-8"))}
    if {profiles[i] for i in ids} & excluded:
        raise ValueError(f"{key} : profils communs avec une sélection de développement")
    return {"dataset": key, "status": "external", "synthetic": True, "external": True,
            "source": str(source), "evaluation_splits": [spec["split"]],
            "evaluation_documents": len(ids), "split_budget": {spec["split"]: len(ids)},
            "protocol": spec["protocol"], "selection": spec["selection"],
            "selection_sha256": spec["selection_sha256"]}


def llm_grouping(spec: dict[str, Any], source: Path, directory: Path) -> dict[str, Any]:
    from quasileak_llm_grouping import group_run

    from anonymisation.metrics import quasileak_official as official

    out = directory / "quasileak_llm_groups.jsonl"
    lock = group_run(source, directory, Path(spec["selection"]), out, backend_name=spec["grouping_backend"])
    if lock["errors"]:
        return {"lock": lock, "official": None, "error": f"{lock['errors']} document(s) en erreur"}
    result = official.score_official(source / "quasileak_bench_data_full.jsonl", source / "split_manifest.json",
                                     out, split=spec["split"], selection=Path(spec["selection"]))
    return {"lock": lock, "official": result, "receives_profile": True}


def native_detector(spec: dict[str, Any], source: Path, out_dir: Path) -> dict[str, Any]:
    from predict_quasileak_local import predict

    from anonymisation.metrics import quasileak_official as official

    out = out_dir / "predictions.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    errors = predict(source, Path(spec["selection"]), out, backend_name=spec["detector_backend"],
                     max_tokens=spec["detector_max_tokens"])
    if errors:
        return {"official": None, "error": f"{errors} document(s) en erreur"}
    result = official.score_official(source / "quasileak_bench_data_full.jsonl", source / "split_manifest.json",
                                     out, split=spec["split"], selection=Path(spec["selection"]))
    write_json(out_dir / "scores.json", result)
    return {"official": result, "receives_profile": True, "protocol": "quasileak-zero-shot-local-v1"}


def parity(runs: list[Path], source: Path, out: Path) -> dict[str, Any]:
    """Scorer officiel isolé sur les groupes figés == scores de la scorecard."""
    out.mkdir(parents=True, exist_ok=True)
    report = []
    for directory in runs:
        groups = directory / "quasileak_d8_groups.jsonl"
        card = json.loads((directory / "scorecard.json").read_text(encoding="utf-8"))
        expected = card["diagnostic"]["quasileak_pgf1_d8"]["details"]["official"]["scores_0_100"]
        ids = set(json.loads((directory / "quasileak_d8_selection.json").read_text(encoding="utf-8")))
        gold = out / f"{directory.name}-gold.jsonl"
        with (source / "quasileak_bench_data_full.jsonl").open(encoding="utf-8") as stream, \
                gold.open("w", encoding="utf-8") as sink:
            for line in stream:
                if json.loads(line)["sample_id"] in ids:
                    sink.write(line)
        proc = subprocess.run([sys.executable, "-I", str(VENDOR_SCORER), "--predictions", str(groups),
                               "--dataset", str(gold)], capture_output=True, text=True, check=False)
        actual = json.loads(proc.stdout) if proc.returncode == 0 else None
        report.append({"run": str(directory), "exit_code": proc.returncode, "identical": actual == expected,
                       "stderr": proc.stderr[-400:]})
    write_json(out / "parity.json", report)
    return {"runs": report, "ok": bool(report) and all(r["identical"] for r in report)}

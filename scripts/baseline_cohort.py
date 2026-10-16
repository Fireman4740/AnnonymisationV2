"""Matérialise une cohorte une fois, puis restaure ses octets sans rééchantillonner.

Phase freeze : préparation supervisée, sans clé API ni modèle. Phase evaluate :
manifeste commité obligatoire ; aucun repli vers une nouvelle sélection.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from anonymisation.schema.io import sha256_file, write_json

PROCESSED = Path("data/processed")
MANIFEST = "cohort.lock.json"
EXPORT = Path("runs/campaign/cohort.lock.json")


def selection_contract(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Les paramètres des modèles ne changent pas l'identité des données."""
    return {key: cfg.get(key) for key in (
        "datasets", "documents_per_dataset", "cap_documents", "sampling_seed",
        "max_document_chars", "conditional_evaluations",
    )}


def snapshot_root(cfg: Mapping[str, Any]) -> Path:
    baseline = cfg["baseline"]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}", baseline["id"]):
        raise ValueError("identifiant de cohorte invalide")
    return Path(baseline.get("snapshot_root", str(Path.home() / ".cache/anonymisation-v2/baselines"))).expanduser() / baseline["id"]


def _relative_file(root: Path, name: str) -> Path:
    parts = PurePosixPath(name)
    if parts.is_absolute() or ".." in parts.parts or not parts.parts:
        raise ValueError("chemin de cohorte invalide")
    return root.joinpath(*parts.parts)


def verify_dataset(root: Path, descriptor: Mapping[str, Any]) -> None:
    expected = descriptor["files"]
    actual_names = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual_names != set(expected):
        raise ValueError(f"snapshot incomplet ou fichiers supplémentaires : {root}")
    for name, digest in expected.items():
        if sha256_file(_relative_file(root, name)) != digest:
            raise ValueError(f"snapshot modifié : {root}/{name}")
    # L'ordre et les identifiants font partie du contrat de relance.
    for split, expected_items in descriptor["items"].items():
        documents = [json.loads(line) for line in (root / split / "documents.jsonl").read_text().splitlines() if line.strip()]
        actual = [{"doc_id": d["doc_id"], "text_sha256": hashlib.sha256(d["text"].encode()).hexdigest()} for d in documents]
        if actual != expected_items:
            raise ValueError(f"ordre, identifiants ou textes modifiés : {root}/{split}")
        if len({d["doc_id"] for d in documents}) != len(documents):
            raise ValueError(f"documents dupliqués : {root}/{split}")


def _validate_manifest(payload: Mapping[str, Any], cfg: Mapping[str, Any]) -> None:
    if (payload.get("schema_version") != "1" or payload.get("cohort_id") != cfg["baseline"]["id"]
            or payload.get("selection_contract") != selection_contract(cfg)
            or set(payload.get("datasets", {})) != set(cfg["datasets"])):
        raise ValueError("manifeste incompatible avec la cohorte/configuration demandée")


def _print_manifest(path: Path, payload: Mapping[str, Any], phase: str) -> None:
    print(f"COHORT_{phase}", json.dumps({"id": payload["cohort_id"], "manifest": str(path),
        "sha256": sha256_file(path), "documents_evaluated": sum(d["info"]["evaluation_documents"] for d in payload["datasets"].values()),
        "datasets": {key: {"evaluation_documents": d["info"]["evaluation_documents"], "split_budget": d["info"]["split_budget"]}
                     for key, d in payload["datasets"].items()}}, sort_keys=True), flush=True)


def freeze_cohort(cfg: Mapping[str, Any], prepare: Callable[..., Any], cache: Path,
                  official_rat_root: Path) -> dict[str, Any]:
    root = snapshot_root(cfg)
    if root.exists():
        payload = json.loads((root / MANIFEST).read_text())
        _validate_manifest(payload, cfg)
        for key, descriptor in payload["datasets"].items():
            verify_dataset(root / "processed" / key, descriptor)
        write_json(EXPORT, payload)
        _print_manifest(EXPORT, payload, "REUSED")
        return payload
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{root.name}-preparing-", dir=root.parent) as temp:
        staging = Path(temp) / "snapshot"
        staging.mkdir()
        payload: dict[str, Any] = {"schema_version": "1", "cohort_id": cfg["baseline"]["id"],
                                   "selection_contract": selection_contract(cfg), "datasets": {}}
        for key, splits in cfg["datasets"].items():
            info = prepare(key, splits, cfg, cache, official_rat_root)
            directory = PROCESSED / key
            files = {p.relative_to(directory).as_posix(): sha256_file(p) for p in sorted(directory.rglob("*")) if p.is_file()}
            items = {}
            for split in info["split_budget"]:
                if not info["split_budget"][split]:
                    continue
                documents = [json.loads(line) for line in (directory / split / "documents.jsonl").read_text().splitlines() if line.strip()]
                items[split] = [{"doc_id": d["doc_id"], "text_sha256": hashlib.sha256(d["text"].encode()).hexdigest()} for d in documents]
            descriptor = {"info": {k: v for k, v in info.items() if k != "selection"}, "files": files, "items": items}
            destination = staging / "processed" / key
            shutil.copytree(directory, destination)
            verify_dataset(destination, descriptor)
            payload["datasets"][key] = descriptor
        _validate_manifest(payload, cfg)
        write_json(staging / MANIFEST, payload)
        # Publication atomique d'un nouveau snapshot ; un snapshot existant
        # n'est jamais remplacé ni reconstruit pendant l'évaluation.
        if root.exists():
            raise ValueError(f"cohorte créée concurremment : {root}")
        staging.rename(root)
    write_json(EXPORT, payload)
    _print_manifest(EXPORT, payload, "PREPARED")
    return payload


def restore_cohort(cfg: Mapping[str, Any]) -> dict[str, Any]:
    manifest = Path(cfg["baseline"]["manifest"])
    if not manifest.is_file():
        raise ValueError(f"manifeste figé obligatoire absent : {manifest} — aucun rééchantillonnage")
    payload = json.loads(manifest.read_text())
    _validate_manifest(payload, cfg)
    root = snapshot_root(cfg)
    if not (root / MANIFEST).is_file():
        raise ValueError(f"snapshot figé absent : {root} — restaurer l'archive, ne pas rééchantillonner")
    if json.loads((root / MANIFEST).read_text()) != payload:
        raise ValueError("snapshot et manifeste commité divergents")
    # Tout vérifier avant de copier et avant le moindre appel à un modèle.
    for key, descriptor in payload["datasets"].items():
        verify_dataset(root / "processed" / key, descriptor)
    for key, descriptor in payload["datasets"].items():
        destination = PROCESSED / key
        if not destination.exists():
            shutil.copytree(root / "processed" / key, destination)
        verify_dataset(destination, descriptor)
    write_json(EXPORT, payload)
    _print_manifest(EXPORT, payload, "RESTORED")
    return {key: descriptor["info"] for key, descriptor in payload["datasets"].items()}

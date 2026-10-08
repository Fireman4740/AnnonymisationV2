"""Campagne fonctionnelle sur échantillons relationnellement complets.

Les documents sont choisis avant prédiction et identiques entre systèmes.
Les tables gold ne sont jamais tronquées au nombre de documents. Ce protocole
exerce les métriques disponibles ; il ne produit pas une mesure de performance
représentative ni des chiffres comparables aux publications.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Iterator
from contextlib import nullcontext
from itertools import islice
from pathlib import Path
from typing import Any
from unittest.mock import patch

from anonymisation.datasets import REGISTRY
from anonymisation.datasets.base import DatasetAdapter
from anonymisation.datasets.ingest import ingest
from anonymisation.datasets.manifest import load_manifest
from anonymisation.llm.config import load_backends_config
from anonymisation.schema.io import sha256_file, write_json

CONFIG = Path("configs/evaluation/campaign.json")
SPIA_REVISION = "3fa78a1b3c75788c6294f40024fc79e1ef42923f"
SPIA_FILES = {
    "spia_tab_144.jsonl": "6b76fe4c26ea619a12913aa3601b31c61acef29b99a7293098876f6ec56b03ac",
    "spia_panorama_531.jsonl": "0d94babe7e2ce19c82a7d4eda4f9d169f1797e0ba5170d291bb01ace0fd0d139",
}


def fetch(url: str, path: Path, expected: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        temporary = path.with_suffix(path.suffix + ".download")
        headers = {}
        if url.startswith("https://huggingface.co/") and os.environ.get("HF_TOKEN"):
            headers["Authorization"] = "Bearer " + os.environ["HF_TOKEN"]
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=120) as source, temporary.open("wb") as out:
            for chunk in iter(lambda: source.read(1 << 20), b""):
                out.write(chunk)
        temporary.replace(path)
    actual = sha256_file(path)
    if expected is not None and actual != expected:
        raise ValueError(f"Source divergente : {path.name}")
    print("SOURCE", json.dumps({"url": url, "sha256": actual, "bytes": path.stat().st_size}), flush=True)


def choose(candidates: list[Any], key: str, count: int, max_chars: int) -> list[Any]:
    eligible = [doc for doc in candidates if 0 < len(doc.text) <= max_chars]
    if key in ("ratbench", "spia"):
        groups = (1, 2, 3) if key == "ratbench" else ("tab", "panorama")
        field = "difficulty" if key == "ratbench" else "source_corpus"
        selected = []
        for group in groups:
            members = [doc for doc in eligible if doc.meta.get(field) == group]
            if not members:
                raise ValueError(f"{key} : aucun document admissible pour {field}={group}")
            selected.append(members[0])
        return selected
    if not eligible:
        raise ValueError(f"{key} : aucun document admissible")
    if len(eligible) < count:
        print("SAMPLE_SMALL", json.dumps({"dataset": key, "requested": count,
                                          "available": len(eligible)}), flush=True)
    return eligible[:count]


class CompleteSample(DatasetAdapter):
    """Vue des documents sélectionnés et de TOUTES leurs annotations/tâches."""

    def __init__(self, source: DatasetAdapter, documents: dict[str, list[Any]],
                 scan_ids: dict[str, set[str]]) -> None:
        super().__init__(source.manifest, source.raw_dir)
        self.key = source.key
        self.source = source
        self.documents = documents
        self.ids = {split: {doc.doc_id for doc in docs} for split, docs in documents.items()}
        self.people = {
            split: ids | {person for doc in documents[split]
                          for person in (*doc.subject_ids, doc.author_id) if person}
            for split, ids in self.ids.items()
        }
        self.scan_ids = scan_ids

    def splits(self) -> tuple[str, ...]:
        return tuple(self.documents)

    def download(self, *, force: bool = False) -> Any:
        return self.source.download(force=force)

    def iter_documents(self, split: str) -> Iterator[Any]:
        yield from self.documents[split]

    def iter_annotations(self, split: str) -> Iterator[Any]:
        for row in self.source.iter_annotations(split):
            # OpenPII parcourt les mêmes lignes JSONL, dans le même ordre,
            # pour documents et annotations. Le premier document hors de la
            # fenêtre prouve que toutes les annotations sélectionnées sont lues.
            if self.key == "openpii" and row.doc_id not in self.scan_ids[split]:
                break
            if row.doc_id in self.ids[split]:
                yield row

    def iter_profiles(self, split: str) -> Iterator[Any]:
        for row in self.source.iter_profiles(split):
            if row.person_id in self.people[split]:
                yield row

    def iter_tasks(self, split: str) -> Iterator[Any]:
        for row in self.source.iter_tasks(split):
            if row.doc_id in self.ids[split]:
                yield row


def prepare(key: str, splits: list[str], cfg: dict[str, Any], cache: Path,
            official_rat_root: Path) -> dict[str, Any]:
    os.environ["ANONV2_V1_DATASETS"] = str(official_rat_root if key == "ratbench"
                                             else Path(cfg["legacy_root"]))
    raw = Path("data/raw") / key
    if key == "spia":
        raw = cache / "SPIA"
        for name, digest in SPIA_FILES.items():
            fetch(f"https://raw.githubusercontent.com/maisonOP/spia/{SPIA_REVISION}/data/spia/{name}",
                  raw / name, digest)
        os.environ["ANONV2_SPIA_ROOT"] = str(raw.resolve())
    elif key == "panorama":
        raw = cache / "PANORAMA"
        os.environ["ANONV2_PANORAMA_ROOT"] = str(raw.resolve())
        fetch("https://huggingface.co/datasets/srirxml/PANORAMA/resolve/"
              "f0037fdba4d2f2be771079c3388d48a1242af3e0/data/train-00000-of-00001.parquet",
              raw / "train.parquet")
    elif key == "openpii":
        raw = cache / "OpenPII"
    loaded = load_manifest(Path("configs/datasets") / f"{key}.yaml")
    adapter = REGISTRY[key](loaded.manifest, raw)
    if key == "openpii":
        adapter.download()  # vérifie le SHA-256 agrégé de la release figée
    selected = {}
    windows = {}
    with_train = loaded.manifest.structure.has_tasks and "train" in loaded.manifest.structure.splits
    target_splits = list(dict.fromkeys((["train"] if with_train else []) + splits))
    for split in target_splits:
        size = 300 if key in ("ratbench", "spia") else cfg["candidate_documents"]
        if split == "train" and with_train:
            size = cfg["train_documents"]
        candidates = list(islice(adapter.iter_documents(split), size))
        # SPIA : TAB précède PANORAMA ; lire assez pour inclure les deux origines.
        windows[split] = {doc.doc_id for doc in candidates}
        selected[split] = candidates if split == "train" and with_train else choose(
            candidates, key, cfg["documents_per_split"], cfg["max_document_chars"])
    sampled = CompleteSample(adapter, selected, windows)
    result = ingest(sampled, loaded.manifest, split="all", output_root=Path("data/processed"),
                    resolution=loaded.resolution)
    info = {"dataset": key, "status": result.status, "counts": result.counts,
            "synthetic": loaded.manifest.structure.synthetic,
            "selection": {split: [{"doc_id": doc.doc_id, "chars": len(doc.text),
                                      "language": doc.language, "meta": doc.meta}
                                    for doc in docs] for split, docs in selected.items()},
            "files": result.files, "protocol": loaded.manifest.evaluation.protocol}
    write_json(Path("runs/campaign/selection") / f"{key}.json", info)
    print("INGEST_RESULT", json.dumps({k: v for k, v in info.items() if k != "selection"},
                                      ensure_ascii=False, sort_keys=True), flush=True)
    return info


def run_campaign() -> int:
    from evaluation_smoke import command, load_key

    load_key()
    cfg = json.loads(CONFIG.read_text())
    llm_cfg = load_backends_config()
    models = {}
    for role in ("anonymizer_backend", "attacker_backend", "judge_backend"):
        backend = llm_cfg.resolve(name=cfg[role])
        if not backend.model.endswith(":free") or backend.extra_body.get("provider", {}).get(
                "max_price") != {"prompt": 0, "completion": 0}:
            raise ValueError(f"Backend non garanti gratuit : {role}")
        models[role] = {"backend": backend.name, "model": backend.model}
    print("CAMPAIGN_CONFIG", json.dumps({**cfg, "models": models}, sort_keys=True), flush=True)
    official_rat_root = Path(os.environ["ANONV2_V1_DATASETS"])
    cache = Path.home() / ".cache/anonymisation-v2/datasets"
    # Clé de pseudonymisation réservée à ce test public, jamais une clé réelle.
    os.environ["ANONV2_PSEUDO_SECRET"] = "functional-evaluation-public-not-for-production"
    summary: dict[str, Any] = {"purpose": cfg["purpose"], "models": models,
                              "datasets": [], "results": [], "failures": [],
                              "remote_skipped": [],
                              "unimplemented": ["hr_qi", "synthpai", "hybrid_qi",
                                                "SPIA adversarial subject matching", "QICR/RCR@k"]}
    for key, splits in cfg["datasets"].items():
        try:
            info = prepare(key, splits, cfg, cache, official_rat_root)
        except (OSError, ValueError, KeyError) as exc:
            failure = {"dataset": key, "stage": "ingest", "error": f"{type(exc).__name__}: {exc}"}
            summary["failures"].append(failure)
            print("CAMPAIGN_ERROR", json.dumps(failure, ensure_ascii=False), flush=True)
            continue
        summary["datasets"].append(info)
        remote_allowed = info["synthetic"] or cfg["remote_real_corpora_authorized"]
        if not remote_allowed:
            summary["remote_skipped"].append({"dataset": key, "stages": ["llm-full", "judge"],
                "reason": "autorisation explicite d'envoi externe des textes réels en attente"})

        def call(args: list[str], *, allow_api: bool = remote_allowed) -> int:
            guard = nullcontext() if allow_api else patch(
                "anonymisation.llm.client.LlmClient.complete",
                side_effect=RuntimeError("Corpus réel : appels LLM externes non autorisés"))
            with guard:
                return command(args)

        for split in splits:
            systems = ["regex-only", "deterministic"]
            if remote_allowed:
                systems.append("llm-full")
            if key == "ratbench":
                systems = ["passthrough", "redact-all", *systems]
            for system in systems:
                directory = Path("runs/campaign") / key / split / system
                entry: dict[str, Any] = {"dataset": key, "split": split, "system": system, "stages": {}}
                stages = entry["stages"]
                args = ["predict", "--dataset", key, "--split", split, "--system", system,
                        "--profile", "llm_full" if system == "llm-full" else "deterministic",
                        "--out", str(directory)]
                if system == "deterministic":
                    args += ["--policy", "P2"]
                elif system == "redact-all":
                    args += ["--param", "replacement="]
                elif system == "llm-full":
                    args += ["--param", f"backend={cfg['anonymizer_backend']}"]
                try:
                    stages["predict"] = call(args)
                    if not (directory / "manifest.lock.json").is_file():
                        raise ValueError("prédiction sans lock")
                    if key == "ratbench":
                        stages["attack"] = call(["attack", "--run", str(directory), "--attacker",
                            "ratbench", "--backend", cfg["attacker_backend"], "--workers", "1"])
                    if remote_allowed:
                        stages["judge"] = call(["judge", "--run", str(directory), "--backend",
                                                cfg["judge_backend"], "--workers", "1"])
                    args = ["score", "--run", str(directory), "--protocol", info["protocol"]]
                    with patch("anonymisation.llm.client.LlmClient.complete",
                               side_effect=RuntimeError("Scoring hors ligne : LLM interdit")):
                        stages["score"] = command(args)
                        card = json.loads((directory / "scorecard.json").read_text())
                        before = sha256_file(directory / "scorecard.json")
                        stages["replay"] = command(args)
                        entry["replay_identical"] = before == sha256_file(directory / "scorecard.json")
                    entry.update({name: card[name] for name in (
                        "primary", "diagnostic", "publishable", "publication_blockers")})
                    entry["scorecard_sha256"] = before
                    entry["prediction_counts"] = card["accounting"]
                    if stages["predict"] or stages.get("attack", 0) or stages.get("judge", 0) or not entry["replay_identical"]:
                        summary["failures"].append({"dataset": key, "split": split,
                                                    "system": system, "stage": "pipeline", "stages": stages})
                except (OSError, ValueError, KeyError, RuntimeError) as exc:
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                    summary["failures"].append({"dataset": key, "split": split,
                                                "system": system, "error": entry["error"]})
                summary["results"].append(entry)
                print("CAMPAIGN_RESULT", json.dumps(entry, ensure_ascii=False, sort_keys=True), flush=True)
                write_json(Path("runs/campaign/summary.json"), summary)
    write_json(Path("runs/campaign/summary.json"), summary)
    compact = {"purpose": summary["purpose"], "models": models, "failures": summary["failures"],
               "unimplemented": summary["unimplemented"], "remote_skipped": summary["remote_skipped"],
               "results": [{k: r.get(k) for k in ("dataset", "split", "system", "stages",
                   "prediction_counts", "replay_identical", "publishable", "error")} for r in summary["results"]]}
    print("FINAL_CAMPAIGN_SUMMARY", json.dumps(compact, ensure_ascii=False, sort_keys=True), flush=True)
    return 1 if summary["failures"] else 0

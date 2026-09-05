"""Utilitaires d'intégration pour exécuter le micro-dataset sans données externes."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from fixtures import load_micro  # noqa: E402

from anonymisation.schema.models import SCHEMA_VERSION  # noqa: E402
from anonymisation.schema.taxonomy import TAXONOMY_VERSION  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_micro_pivot(root: Path) -> Path:
    """Écrit un pivot ``micro/train`` compatible avec ``anonv2 predict``."""
    data = load_micro()
    documents = [document for document in data["documents"] if document.split == "train"]
    document_ids = {document.doc_id for document in documents}
    annotations = [
        annotation
        for annotation in data["annotations"]
        if annotation.doc_id in document_ids
    ]

    base = root / "micro" / "train"
    base.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, records in (("documents", documents), ("annotations", annotations)):
        path = base / f"{name}.jsonl"
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(
                    json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
                    + "\n"
                )
        paths[f"train/{name}.jsonl"] = path

    lock: dict[str, Any] = {
        "manifest": {"key": "micro", "splits": ["train"]},
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "source": {
            "kind": "local",
            "directory": str(base),
            "files": [str(path) for path in paths.values()],
            "fingerprint": None,
        },
        "files": {name: _sha256(path) for name, path in paths.items()},
        "date": "2026-01-01",
        "status": "official",
    }
    (root / "micro" / ".manifest.lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return root

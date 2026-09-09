"""Commande CLI `anonv2 compare` et gestion de l'index des runs (SPEC-07, SPEC-10).

Exécute la comparaison de scorecards, valide la compatibilité, génère le rapport
Markdown et met à jour de façon atomique `runs/index.json`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from anonymisation.metrics.comparison import (
    MetricComparisonError,
    assert_comparable_across_systems,
    render_comparison_markdown,
)
from anonymisation.schema.io import sha256_file, write_json

# Ancré sur la racine du dépôt, comme les autres chemins de la CLI : un index
# relatif au répertoire courant se dupliquerait à chaque `cd`, et le garde-fou
# de collision de run_id n'aurait alors plus rien à comparer.
REPO_ROOT = Path(__file__).resolve().parents[3]
INDEX_PATH = REPO_ROOT / "runs" / "index.json"


class CompareError(ValueError):
    """Erreur de validation ou d'exécution de la comparaison."""


def load_scorecard(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise CompareError(f"Fichier scorecard introuvable : {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CompareError(f"Fichier scorecard illisible ({p}) : {exc}") from exc
    if not isinstance(data, dict):
        raise CompareError(f"Scorecard invalide dans {p} : attendu objet JSON.")
    return data


def update_runs_index(
    runs: Sequence[tuple[Path, dict[str, Any]]], index_path: Path = INDEX_PATH
) -> None:
    """Met à jour atomiquement runs/index.json trié et sans collision de run_id."""
    index: dict[str, dict[str, Any]] = {}
    if index_path.is_file():
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for entry in raw:
                    if isinstance(entry, dict) and "run_id" in entry:
                        index[entry["run_id"]] = entry
            elif isinstance(raw, dict):
                index = raw
        except Exception as exc:
            # Un index illisible n'est pas un index vide : l'écraser ferait
            # disparaître les run_id déjà enregistrés, et avec eux le contrôle
            # de collision.
            raise CompareError(
                f"Index des runs illisible ({index_path}) : {exc}"
            ) from exc

    for run_dir, sc in runs:
        run_id = sc.get("run_id") or run_dir.name
        system = sc.get("system") or {}
        digest = system.get("params_digest") or system.get("digest") or ""
        system_id = system.get("system_id", "")

        # Chemin normalisé : sans cela, `run` et `./run` passeraient pour deux
        # emplacements différents et déclencheraient une fausse collision.
        rel_path = str(Path(run_dir).resolve())

        if run_id in index and index[run_id].get("path") != rel_path:
            raise CompareError(
                f"Collision de run_id : {run_id!r} pointe déjà vers {index[run_id].get('path')!r} "
                f"(tentative vers {rel_path!r})."
            )

        sc_file = run_dir / "scorecard.json"
        sc_hash = sha256_file(sc_file) if sc_file.is_file() else ""

        entry = {
            "run_id": run_id,
            "path": rel_path,
            "system_id": system_id,
            "system_digest": digest,
            "dataset": sc.get("dataset", ""),
            "split": sc.get("split", ""),
            "protocol": sc.get("protocol", ""),
            "status": sc.get("status", ""),
            "scorecard_sha256": sc_hash,
        }
        index[run_id] = entry

    # Trier par run_id
    sorted_entries = [index[k] for k in sorted(index.keys())]
    write_json(index_path, sorted_entries)


def cmd_compare(
    run_dirs: Sequence[str | Path],
    out_path: str | Path | None = None,
    index_path: Path | None = None,
) -> int:
    """Charge les scorecards, vérifie la comparabilité, écrit le rapport et met à jour l'index."""
    if len(run_dirs) < 2:
        raise CompareError("Au moins deux runs sont requis pour la comparaison.")

    scorecards: list[dict[str, Any]] = []
    run_tuples: list[tuple[Path, dict[str, Any]]] = []

    for r in run_dirs:
        r_path = Path(r)
        sc_path = r_path / "scorecard.json" if r_path.is_dir() else r_path
        sc = load_scorecard(sc_path)
        actual_dir = r_path if r_path.is_dir() else r_path.parent
        scorecards.append(sc)
        run_tuples.append((actual_dir, sc))

    # Valide la comparabilité
    try:
        assert_comparable_across_systems(scorecards)
    except MetricComparisonError as exc:
        raise CompareError(f"Runs non comparables : {exc}") from exc

    md = render_comparison_markdown(scorecards)

    if out_path is not None:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"Rapport de comparaison écrit : {out}")
    else:
        print(md)

    # Une collision de run_id est une erreur d'usage, pas un avertissement :
    # la taire laisserait l'index désigner un autre run que celui comparé.
    update_runs_index(run_tuples, index_path=index_path or INDEX_PATH)

    return 0

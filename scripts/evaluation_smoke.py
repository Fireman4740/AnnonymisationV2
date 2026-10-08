"""Sanité fonctionnelle sur deux documents, pas une estimation de performance.

Ce contrat lance les deux ancres passthrough/redact-all, un attaquant et un
juge Gemma gratuits, puis prouve la relecture bit-à-bit hors ligne du score.
Les échecs de quota sont rapportés explicitement, jamais interprétés comme
de la protection. Les résultats sont imprimés dans le journal supervisé.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from anonymisation.cli.main import main
from anonymisation.schema.io import sha256_file, write_json


def load_key() -> None:
    if os.environ.get("OPENROUTER_API_KEY"):
        return
    # Fichier externe à l'archive, lu sans évaluation shell et jamais affiché.
    explicit = os.environ.get("ANONV2_SECRETS_FILE")
    paths = [Path(explicit)] if explicit else [Path("/mnt/f/IA/AnnonymisationV2/.env"), Path(".env")]
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "OPENROUTER_API_KEY":
                value = value.strip().strip("\"'")
                if value:
                    os.environ[key.strip()] = value
                    return
    raise RuntimeError("OPENROUTER_API_KEY absent : définir ANONV2_SECRETS_FILE ou la variable")


def command(args: list[str]) -> int:
    print("COMMAND", " ".join(args), flush=True)
    return main(args)


def run() -> int:
    load_key()
    if command(["datasets", "ingest", "ratbench", "--split", "eval"]):
        return 2
    summary = {"purpose": "functional_sanity_only", "documents_per_system": 2,
               "backend": "openrouter_gemma4_26b", "results": [], "failures": []}
    for system in ("passthrough", "redact-all"):
        directory = Path("runs") / f"sanity-{system}"
        stages = {}
        stages["predict"] = command(["predict", "--dataset", "ratbench", "--split", "eval",
            "--system", system, "--profile", "deterministic", "--limit", "2", "--out", str(directory)])
        if stages["predict"]:
            summary["failures"].append(f"{system}:predict")
            continue
        stages["attack"] = command(["attack", "--run", str(directory), "--attacker", "ratbench",
                                    "--backend", "openrouter_gemma4_26b", "--workers", "1"])
        stages["judge"] = command(["judge", "--run", str(directory),
                                   "--backend", "openrouter_gemma4_26b", "--workers", "1"])
        if stages["attack"] or stages["judge"]:
            summary["failures"].append(f"{system}:attack/judge")
        args = ["score", "--run", str(directory), "--protocol", "ratbench-v1"]
        stages["score"] = command(args)
        card = json.loads((directory / "scorecard.json").read_text())
        before = sha256_file(directory / "scorecard.json")
        command(args)
        replay = before == sha256_file(directory / "scorecard.json")
        if not replay:
            summary["failures"].append(f"{system}:offline_replay")
        entry = {"system": system, "stages": stages, "replay_identical": replay,
                 "publishable": card["publishable"], "blockers": card["publication_blockers"],
                 "reid": card["primary"]["reid_success_rate"],
                 "utility": card["diagnostic"]["mean_utility"]}
        summary["results"].append(entry)
        print("SANITY_RESULT", json.dumps(entry, ensure_ascii=False, sort_keys=True), flush=True)
    write_json(Path("runs/sanity-summary.json"), summary)
    print("FINAL_SUMMARY", json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(run())

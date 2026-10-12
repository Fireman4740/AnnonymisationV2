"""Contrôle d'équivalence du portage RAT-Bench contre le code officiel (EPIC-H H-3).

Le portage (``anonymisation.attack.ratbench``) n'est jamais présumé conforme :
ce script télécharge les modules officiels au commit figé
``imperial-aisp/rat-bench@8e9f03d`` (empreintes SHA-256 vérifiées avant toute
exécution), en extrait les fonctions utiles par AST — sans exécuter leurs
imports lourds (torch, transformers, lecture des CSV serbes) — puis rejoue, sur
les sorties FIGÉES d'une attaque, chaque décision du protocole :

1. prompt rendu (``get_staab_prompt``) ;
2. lecture de la réponse (``parse_output_gpt``) ;
3. jugement des attributs (``check_guesses_one_profile``) ;
4. encodage PUMS des attributs justes, dates et PUMA_FULL compris
   (``process_col`` et la boucle de ``compute_reid_risk``) ;
5. moyenne des tirages CorrectMatch (NaN écartés) et règle de succès
   (``_is_reided``).

CorrectMatch lui-même n'est pas relancé : ses tirages sont figés dans
``attacks.jsonl`` ; on vérifie que leur agrégation officielle redonne la valeur
figée. Le dépôt officiel ne publie pas de licence : son code n'est donc pas
recopié dans le dépôt, seulement téléchargé et exécuté ici, au commit figé.

Usage (dépendances isolées, hors projet) ::

    uv run --isolated --no-project --with levenshtein --with numpy \\
        python scripts/parity_ratbench.py --profiles data/processed/ratbench/eval/profiles.jsonl \\
        --maps <source>/cache/maps --out runs/parity-ratbench.json runs/campaign/ratbench/eval/*

Code de sortie 1 au premier écart : un écart de portage invalide R_succ.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import pickle
import re
import sys
import tempfile
import urllib.request
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO = "imperial-aisp/rat-bench"
COMMIT = "8e9f03d00cb0559508d8ee86bc743875aa6bcf95"
OFFICIAL_FILES = {
    "pii_benchmark/utils.py": "7f301419b1356d83ce25f6d995f7c275c930398998d4e6efe9931f42d257fc08",
    "pii_benchmark/evaluation.py": "b6cd9c917c06a754fc1c48e76be5b58e27cb6af97f7386f7fc6b386c23af10dc",
    "pii_benchmark/prompts.py": "a4863e9cb742519e14e9f694e317884e6d5e3ca3ef662dc3c0bc890b9855de01",
    "pii_benchmark/uniqueness.py": "a1eb1f8db603142a8a95d5d5736fa9515a3034ab1972929bdafb545a9d9556da",
}
DATE_PARTS = ("DOB-Day", "DOB-Month", "DOB-Year")


class ParityError(RuntimeError):
    """Source officielle introuvable ou divergente."""


def fetch_official(cache: Path) -> dict[str, str]:
    """Sources officielles, téléchargées une fois et vérifiées à chaque lecture."""
    sources: dict[str, str] = {}
    for path, digest in OFFICIAL_FILES.items():
        target = cache / COMMIT / path
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            url = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{path}"
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 — URL figée
                target.write_bytes(response.read())
        data = target.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest:
            raise ParityError(f"{path} : empreinte {actual} ≠ {digest} (commit {COMMIT})")
        sources[path] = data.decode("utf-8")
    return sources


def extract(source: str, keep: Callable[[ast.stmt], bool], namespace: dict[str, Any]) -> None:
    """Exécute les seules instructions de premier niveau retenues par ``keep``."""
    module = ast.Module(body=[node for node in ast.parse(source).body if keep(node)], type_ignores=[])
    exec(compile(module, "<rat-bench officiel>", "exec"), namespace)  # noqa: S102 — code figé vérifié


def _named(*names: str) -> Callable[[ast.stmt], bool]:
    wanted = set(names)

    def keep(node: ast.stmt) -> bool:
        if isinstance(node, ast.FunctionDef):
            return node.name in wanted
        if isinstance(node, ast.Assign):
            return any(isinstance(t, ast.Name) and t.id in wanted for t in node.targets)
        return False

    return keep


def _utils_assignments(node: ast.stmt) -> bool:
    """Constantes de ``utils.py`` : toutes ses affectations de premier niveau sont littérales."""
    return isinstance(node, ast.Assign)


def build_official(sources: dict[str, str]) -> dict[str, Any]:
    from typing import List, Tuple, Union  # noqa: UP035 — noms attendus par le code officiel

    import Levenshtein  # dépendance du code officiel (`str_is_close`)

    ns: dict[str, Any] = {"re": re, "json": json, "pickle": pickle,  # noqa: UP006
                          "Levenshtein": Levenshtein, "List": List, "Tuple": Tuple, "Union": Union}  # noqa: UP006
    utils = sources["pii_benchmark/utils.py"]
    extract(utils, _utils_assignments, ns)
    extract(utils, lambda n: isinstance(n, ast.FunctionDef) and n.name != "load_data", ns)
    extract(sources["pii_benchmark/prompts.py"], _named("get_scenario_prompt", "get_staab_prompt"), ns)
    extract(sources["pii_benchmark/evaluation.py"], _named(
        "get_match", "compare_ages", "check_age", "check_occupation", "check_education",
        "check_state", "check_dob", "filter_non_digits", "check_numeric_direct_identifiers",
        "check_correctness", "check_guesses_one_profile"), ns)
    # `uniqueness.py` a son propre espace de noms : ses constantes homonymes
    # (`PUMS_MAPS_PATH`, `pums_cols`) diffèrent de celles de `utils.py`.
    import numpy as np

    uniq: dict[str, Any] = {"pickle": pickle, "np": np, "List": List}  # noqa: UP006
    uniqueness = sources["pii_benchmark/uniqueness.py"]
    extract(uniqueness, _named("PUMS_MAPS_PATH", "PUMS_DOB_MAP_PATH", "pums_cols",
                               "REID_CORRECTNESS_THRESHOLD", "process_col", "_is_reided"), uniq)
    # `PUMS_OCCUPATION_TYPE_TO_CODE` : le bloc `with open(OCCP_type_map)` puis la
    # boucle d'inversion, extraits tels quels.
    extract(uniqueness, lambda n: (
        (isinstance(n, ast.With) and "OCCP_type_map" in ast.unparse(n))
        or (isinstance(n, ast.Assign) and ast.unparse(n).startswith("PUMS_OCCUPATION_TYPE_TO_CODE"))
        or (isinstance(n, ast.For) and "PUMS_OCCUPATION_TYPE_TO_CODE" in ast.unparse(n))
    ), uniq)
    ns["uniqueness"] = uniq
    return ns


def write_pickled_maps(maps_dir: Path, workdir: Path) -> None:
    """Pickles attendus par le code officiel, reconstruits depuis les tables JSON vérifiées."""
    target = workdir / "data" / "maps"
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(maps_dir.glob("*.json")):
        pairs = json.loads(path.read_text(encoding="utf-8"))["pairs"]
        name = "zip_to_puma.pickle" if path.stem == "zip_to_puma" else f"{path.stem}_map.pickle"
        (target / name).write_bytes(pickle.dumps(dict((k, v) for k, v in pairs)))


@contextmanager
def chdir(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def official_record(ns: dict[str, Any], correctness: dict[str, Any], indirect: dict[str, Any]
                    ) -> tuple[dict[str, int], list[str]]:
    """Boucle PUMS de ``compute_reid_risk`` officiel : enregistrement + identifiants directs."""
    record: dict[str, int] = {}
    direct: list[str] = []
    cols_to_fit: list[str] = []
    uniq = ns["uniqueness"]
    for column in correctness:
        if column in uniq["pums_cols"]:
            value, cols_to_fit = uniq["process_col"](column, correctness, indirect, cols_to_fit)
            if value is not None:
                record["PUMA_FULL" if column == "zip code" else column] = int(value)
        else:
            guess = correctness[column]
            if guess is not None and len(guess) > 0 and guess[0] == 1:
                direct.append(column)
    ordered = {}
    for column in uniq["pums_cols"]:
        key = "PUMA_FULL" if column == "zip code" else column
        if key in record:
            ordered[key] = record[key]
    return ordered, direct


def compare_row(ns: dict[str, Any], row: dict[str, Any], record: dict[str, Any],
                profile: dict[str, Any]) -> list[str]:
    meta = profile["meta"]
    features = list(meta["features"])
    gaps: list[str] = []
    prompt = ns["get_staab_prompt"](attributes=features, text=record["anonymized_text"],
                                    scenario=meta["scenario"], language="English")
    guesses = ns["parse_output_gpt"](row.get("response", ""), interactive=False) if "response" in row else {}
    if row["status"] != "ok":
        if "aucune devinette" in str(row.get("error")) and guesses:
            gaps.append("erreur « aucune devinette » mais l'officiel lit des devinettes")
        return gaps
    if prompt != row["prompt"]:
        gaps.append("prompt rendu différent")
    ours = {k: v for k, v in row["guesses"].items()}
    theirs = {k: v.get("Guess") for k, v in guesses.items()}
    if ours != theirs:
        gaps.append(f"devinettes lues : port={ours} officiel={theirs}")
    attributes = list(features)
    if "DOB" in attributes and not set(DATE_PARTS) & set(attributes):
        attributes += list(DATE_PARTS)
    truth = {**meta["direct_identifiers"], **meta["indirect_identifiers"]}
    correctness, _ = ns["check_guesses_one_profile"](guesses, truth, attributes)
    if {k: list(v) for k, v in correctness.items()} != row["correctness"]:
        gaps.append(f"jugement : port={row['correctness']} officiel={correctness}")
    encoded, direct = official_record(ns, correctness, meta["indirect_identifiers"])
    if encoded != row["encoded_record"]:
        gaps.append(f"encodage PUMS : port={row['encoded_record']} officiel={encoded}")
    if sorted(direct) != row["correct_direct_ids"]:
        gaps.append(f"identifiants directs : port={row['correct_direct_ids']} officiel={direct}")
    draws = [math.nan if d is None else d for d in row["correctmatch_draws"]]
    if encoded:
        import numpy as np

        kept = [c for c in draws if not np.isnan(c)]
        official_mean = float(np.mean(kept)) if kept else math.nan
    else:
        official_mean = 0.0  # « No cols to fit » officiel
    frozen = math.nan if row["correctmatch_correctness"] is None else row["correctmatch_correctness"]
    if not (math.isnan(official_mean) and math.isnan(frozen)) and not math.isclose(
            official_mean, frozen, rel_tol=0, abs_tol=1e-12):
        gaps.append(f"moyenne CorrectMatch : figée={frozen} officielle={official_mean}")
    import numpy as np

    official_success = bool(ns["uniqueness"]["_is_reided"](np.array([len(direct)]), np.array([official_mean]))[0])
    if official_success != row["reidentified"]:
        gaps.append(f"succès : port={row['reidentified']} officiel={official_success}")
    return gaps


def _jsonl(path: Path) -> Iterable[dict[str, Any]]:
    return (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", nargs="+", type=Path, help="répertoires de run attaqués")
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--maps", type=Path, required=True, help="cache/maps (JSON vérifiés)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path,
                        default=Path.home() / ".cache" / "anonymisation-v2" / "rat-bench-official")
    args = parser.parse_args(argv)

    runs = [run.resolve() for run in args.runs]
    maps_dir = args.maps.resolve()
    profiles_path = args.profiles.resolve()
    sources = fetch_official(args.cache)
    profiles = {p["person_id"]: p for p in _jsonl(profiles_path)}
    report: dict[str, Any] = {"official": {"repo": REPO, "commit": COMMIT, "files": OFFICIAL_FILES},
                              "runs": {}, "rows_compared": 0, "gaps": 0}
    with tempfile.TemporaryDirectory(prefix="ratbench-parity-") as tmp:
        workdir = Path(tmp)
        write_pickled_maps(maps_dir, workdir)
        with chdir(workdir):
            ns = build_official(sources)
            for run in runs:
                if not (run / "attacks.jsonl").is_file():
                    continue
                predictions = {r["doc_id"]: r for r in _jsonl(run / "predictions.jsonl")}
                per_run: dict[str, list[str]] = {}
                for row in _jsonl(run / "attacks.jsonl"):
                    gaps = compare_row(ns, row, predictions[row["doc_id"]], profiles[row["doc_id"]])
                    report["rows_compared"] += 1
                    if gaps:
                        per_run[row["doc_id"]] = gaps
                        report["gaps"] += len(gaps)
                report["runs"][str(run)] = per_run
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print("PARITY_RATBENCH", json.dumps({"rows": report["rows_compared"], "gaps": report["gaps"]}),
          flush=True)
    return 1 if report["gaps"] else 0


if __name__ == "__main__":
    sys.exit(main())

"""Étape figée ``anonv2 attack`` pour RAT-Bench : run → ``attacks.jsonl``.

Lit un run ``predict`` (textes anonymisés), le profil gold de chaque document
(``profiles.jsonl`` du pivot, jamais visible des systèmes), interroge
l'attaquant LLM, juge les devinettes, estime le risque CorrectMatch, et fige
le tout. Le scoring (``score``) relit ``attacks.jsonl`` sans rien relancer.

Garanties :

* empreintes vérifiées : le run attaqué est bien celui du lock (prédictions),
  le profil gold est celui de l'ingestion ;
* une réponse vide, illisible ou un backend injoignable après réessais est
  une ERREUR du document (C3), comptée, jamais « rien deviné » ;
* au-delà de 5 % de documents en erreur, l'attaque est non publiable (C4) ;
* ``attack.lock.json`` fige attaquant, modèle, température, prompt, tables,
  population, N, seuil, commit du protocole officiel et empreinte des sorties.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anonymisation.attack.ratbench import (
    CORRECTMATCH_REPEATS,
    OFFICIAL_COMMIT,
    OFFICIAL_REPO,
    POPULATION_N,
    REID_CORRECTNESS_THRESHOLD,
)
from anonymisation.attack.ratbench.correctness import check_profile
from anonymisation.attack.ratbench.maps import PUMS_COLUMNS, RatBenchMaps
from anonymisation.attack.ratbench.parse import AttackParseError, parse_guesses
from anonymisation.attack.ratbench.prompts import SYSTEM_PROMPT, staab_prompt
from anonymisation.attack.ratbench.risk import (
    CorrectMatchRisk,
    CorrectMatchUnavailable,
    encode_correct_attributes,
)
from anonymisation.datasets._local import fingerprint
from anonymisation.llm.client import LlmBackendUnavailableError, LlmClient, LlmError
from anonymisation.schema.integrity import locked_files, verify_pivot_files, verify_run_outputs
from anonymisation.schema.io import atomic_write, read_jsonl, sha256_file, write_json
from anonymisation.schema.models import Profile

PROTOCOL = "ratbench-staab-correctmatch"
PROTOCOL_VERSION = "1"
ATTACKS_NAME = "attacks.jsonl"
ATTACK_LOCK_NAME = "attack.lock.json"
#: Attentes entre réessais quand le palier gratuit renvoie 429/502.
RETRY_DELAYS_S = (5, 15, 30)
MAX_ERROR_RATE = 0.05


class AttackError(ValueError):
    """Run inattaquable : corpus non RAT-Bench, empreinte divergente, source absente."""


@dataclass(frozen=True)
class AttackInputs:
    run_dir: Path
    dataset_root: Path
    split: str
    source_dir: Path
    predictions_sha256: str


def _resolve_inputs(run_dir: Path, processed_root: Path) -> AttackInputs:
    lock_path = run_dir / "manifest.lock.json"
    if not lock_path.is_file():
        raise AttackError(f"lock de run absent : {lock_path}")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    run = lock.get("run") or {}
    if run.get("dataset") != "ratbench":
        raise AttackError(
            f"l'attaque RAT-Bench ne s'applique qu'au corpus `ratbench` (run : {run.get('dataset')!r})"
        )
    split = str(run["split"])
    context = f"Attaque {run_dir}"
    outputs = verify_run_outputs(run_dir, lock.get("outputs"), ("predictions.jsonl",), context=context)
    files = locked_files(lock.get("data_version"), context=context)
    dataset_root = processed_root / "ratbench"
    verify_pivot_files(dataset_root, split, ("profiles.jsonl",), files, context=context,
                       required=("profiles.jsonl",))
    source = (lock.get("data_version") or {}).get("source") or {}
    directory = source.get("directory")
    if not directory or not Path(directory).is_dir():
        raise AttackError(
            f"répertoire source RAT-Bench introuvable ({directory!r}) : tables et population "
            "PUMS y sont lues — lancer scripts/fetch_ratbench.py puis réingérer."
        )
    source_files = [Path(p) for p in source.get("files", [])]
    if not source_files or any(not p.is_file() for p in source_files):
        raise AttackError("sources RAT-Bench manquantes : réingérer après acquisition")
    if fingerprint(source_files) != source.get("fingerprint"):
        raise AttackError("sources RAT-Bench modifiées depuis l'ingestion : réingérer")
    source_manifest = Path(directory) / "SOURCES.json"
    if source_manifest not in source_files:
        raise AttackError("SOURCES.json non verrouillé : réingérer RAT-Bench")
    declared = json.loads(source_manifest.read_text(encoding="utf-8")).get("files", {})
    for path in source_files:
        if path == source_manifest:
            continue
        relative = path.relative_to(directory).as_posix()
        if declared.get(relative) != sha256_file(path):
            raise AttackError(f"source RAT-Bench divergente : {relative}")
    return AttackInputs(run_dir, dataset_root, split, Path(directory), outputs["predictions.jsonl"])


def _complete_with_retries(
    client: LlmClient, prompt: str, *, sleep: Callable[[float], None] = time.sleep
) -> tuple[str, bool]:
    for attempt, delay in enumerate((0, *RETRY_DELAYS_S)):
        if delay:
            sleep(delay)
        try:
            completion = client.complete(prompt, system=SYSTEM_PROMPT)
            return completion.content, completion.cached
        except LlmBackendUnavailableError:
            if attempt == len(RETRY_DELAYS_S):
                raise
    raise AssertionError("inatteignable")


def attack_one(
    record: Mapping[str, Any],
    profile: Profile,
    maps: RatBenchMaps,
    complete: Callable[[str], tuple[str, bool]],
    risk: CorrectMatchRisk,
) -> dict[str, Any]:
    """Attaque un document ; renvoie la ligne figée (statut ``ok`` ou ``error``)."""
    meta = profile.meta
    features = list(meta["features"])
    ground_truth = {**meta["direct_identifiers"], **meta["indirect_identifiers"]}
    base: dict[str, Any] = {"doc_id": record["doc_id"], "difficulty": meta.get("difficulty")}
    try:
        prompt = staab_prompt(features, str(record["anonymized_text"]), str(meta["scenario"]), maps)
        response, cached = complete(prompt)
        guesses = parse_guesses(response)
        required = [f for f in features if f not in ("DOB-Day", "DOB-Month", "DOB-Year")]
        missing = [f for f in required if f not in guesses or "Guess" not in guesses[f]]
        if missing:
            raise AttackParseError(f"réponse incomplète : attributs absents {missing}")
        for feature in required:
            guess = guesses[feature]["Guess"]
            if not isinstance(guess, (str, list)) or (isinstance(guess, list)
                    and any(not isinstance(g, str) for g in guess)):
                raise AttackParseError(f"devinette `{feature}` : chaîne ou liste de chaînes attendue")
    except (LlmError, AttackParseError) as exc:
        return {**base, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    correctness = check_profile(guesses, ground_truth, features)
    direct_hits = sorted(
        att for att, flags in correctness.items()
        if att not in PUMS_COLUMNS and flags and flags[0] == 1
    )
    try:
        encoded = encode_correct_attributes(correctness, meta["indirect_identifiers"], maps)
        estimate = risk.estimate(encoded)
    except CorrectMatchUnavailable as exc:
        return {**base, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    return {
        **base,
        "status": "ok",
        "error": None,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "cached": cached,
        "response": response,
        "guesses": {k: v.get("Guess") for k, v in sorted(guesses.items())},
        "correctness": {k: v for k, v in sorted(correctness.items())},
        "correct_direct_ids": direct_hits,
        "correct_indirect_columns": list(estimate.columns),
        "correctmatch_correctness": estimate.correctness,
        "correctmatch_uniqueness": estimate.uniqueness,
        "reidentified": bool(direct_hits) or estimate.correctness >= REID_CORRECTNESS_THRESHOLD,
    }


def run_attack(
    run_dir: Path, *, backend: str, processed_root: Path, workers: int | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    inputs = _resolve_inputs(run_dir, processed_root)
    maps = RatBenchMaps.load(inputs.source_dir / "cache" / "maps")
    population = inputs.source_dir / "cache" / "pums_population.parquet"
    risk = CorrectMatchRisk(population)
    client = LlmClient.for_backend(backend)
    profiles = {
        p.person_id: p
        for p in read_jsonl(inputs.dataset_root / inputs.split / "profiles.jsonl", Profile)
    }
    predictions = [
        json.loads(line) for line in (run_dir / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    targets = [p for p in predictions if str(p.get("status")) in ("ok", "partial")]
    if len({p["doc_id"] for p in targets}) != len(targets):
        raise AttackError("doc_id dupliqué dans les prédictions")
    if any(not isinstance(p.get("anonymized_text"), str) for p in targets):
        raise AttackError("texte anonymisé absent : relancer predict")
    missing = [p["doc_id"] for p in targets if p["doc_id"] not in profiles]
    if missing:
        raise AttackError(f"profil gold absent pour {len(missing)} document(s), ex. {missing[0]!r}")

    def complete(prompt: str) -> tuple[str, bool]:
        return _complete_with_retries(client, prompt)

    # Seule la phase réseau est parallélisée : CorrectMatch passe par Julia
    # (juliacall), qui n'est pas sûr en multi-thread — il reste séquentiel.
    pool = max(1, workers or client.backend.max_concurrency)
    with ThreadPoolExecutor(max_workers=pool) as executor:
        responses = list(executor.map(
            lambda rec: _prefetch(rec, profiles[rec["doc_id"]], maps, complete), targets
        ))
    rows = [
        attack_one(rec, profiles[rec["doc_id"]], maps, lambda _p, r=resp: r, risk)
        if not isinstance(resp, Exception)
        else {"doc_id": rec["doc_id"], "status": "error",
              "error": f"{type(resp).__name__}: {resp}",
              "difficulty": profiles[rec["doc_id"]].meta.get("difficulty")}
        for rec, resp in zip(targets, responses, strict=True)
    ]
    rows.sort(key=lambda row: row["doc_id"])
    with atomic_write(run_dir / ATTACKS_NAME) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    errors = sum(1 for row in rows if row["status"] != "ok")
    error_rate = errors / len(rows) if rows else 1.0
    lock = {
        "protocol": PROTOCOL,
        "protocol_version": PROTOCOL_VERSION,
        "official": {"repo": OFFICIAL_REPO, "commit": OFFICIAL_COMMIT},
        "attacker": {
            "backend": client.backend.name,
            "model": client.backend.model,
            "temperature": client.backend.temperature,
            "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
            "prompt_module_sha256": sha256_file(Path(__file__).with_name("prompts.py")),
        },
        "risk": {
            "model": "CorrectMatch (Rocher et al., 2019)",
            "population_n": POPULATION_N,
            "repeats": CORRECTMATCH_REPEATS,
            "threshold": REID_CORRECTNESS_THRESHOLD,
            "population_sha256": sha256_file(population),
            "maps_source": maps.source,
            "maps_sha256": {p.name: sha256_file(p) for p in sorted((inputs.source_dir / "cache" / "maps").glob("*.json"))},
            "encoding": "sorted-dense-1-based",
            "stochastic": True,
            "protocol_module_sha256": sha256_file(Path(__file__).with_name("risk.py")),
        },
        "inputs": {
            "predictions.jsonl": inputs.predictions_sha256,
            "profiles.jsonl": sha256_file(inputs.dataset_root / inputs.split / "profiles.jsonl"),
        },
        "outputs": {ATTACKS_NAME: sha256_file(run_dir / ATTACKS_NAME)},
        "documents": len(rows),
        "documents_error": errors,
        "error_rate": error_rate,
        "publishable": error_rate <= MAX_ERROR_RATE,
    }
    write_json(run_dir / ATTACK_LOCK_NAME, lock)
    return lock


def _prefetch(
    record: Mapping[str, Any], profile: Profile, maps: RatBenchMaps,
    complete: Callable[[str], tuple[str, bool]],
) -> tuple[str, bool] | Exception:
    """Phase réseau seule : renvoie la réponse, ou l'exception (jamais avalée)."""
    meta = profile.meta
    try:
        prompt = staab_prompt(list(meta["features"]), str(record["anonymized_text"]),
                              str(meta["scenario"]), maps)
        return complete(prompt)
    except LlmError as exc:
        return exc


__all__ = ["ATTACKS_NAME", "ATTACK_LOCK_NAME", "AttackError", "attack_one", "run_attack"]

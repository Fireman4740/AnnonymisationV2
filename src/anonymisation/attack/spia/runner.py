"""Étape figée ``anonv2 attack --attacker spia`` : run → ``spia_attacks.jsonl``.

Enchaîne, document par document, les fonctions ORIGINALES de SPIA :

1. ``infer_spia`` sur le **texte anonymisé** : analyse des sujets (SA),
   profilage des PII « code » (SPC) puis « non code » (SPNC), fusion
   (``merge_results``, repli SPNC désactivé comme par défaut) ;
2. ``align_subject_based_ground_truth`` : alignement des sujets inférés sur
   les sujets gold (prompt « anon » : texte original + anonymisé), puis
   ``transform_to_gt_aligned_format`` — un sujet gold non apparié reçoit des
   PII vides, donc compte comme protégé, exactement comme l'original ;
3. ``check_human_labels_gt.evaluate_subject_annotations`` : score d'accord par
   attribut (1 / 0,5 / 0) — règles puis modèle (``decider=rule_model``).

Écart déclaré : la configuration officielle termine par un arbitrage
**humain** interactif (``rule_model_human``), impossible dans un banc
automatisé ; on s'arrête à ``rule_model``, branche existante de l'original
(réponse du modèle non concluante → 0).

C3 : le code original avale certaines pannes du modèle (``except Exception``
→ score 0, repli sans réparation JSON). Le transport les journalise ; un
document qui en a subi une est classé en **erreur**, jamais compté comme
« non inféré ». Le gold vient du fichier SPIA source verrouillé à
l'ingestion, empreinte revérifiée.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from anonymisation.attack.spia import OFFICIAL_COMMIT, OFFICIAL_REPO
from anonymisation.attack.spia.vendored import original_spia, tree_sha256
from anonymisation.datasets._local import fingerprint
from anonymisation.llm.client import LlmBackendUnavailableError, LlmClient, LlmError
from anonymisation.schema.integrity import verify_run_outputs
from anonymisation.schema.io import atomic_write, sha256_file, write_json

PROTOCOL = "spia-original"
PROTOCOL_VERSION = "1"
ATTACKS_NAME = "spia_attacks.jsonl"
ATTACK_LOCK_NAME = "spia_attack.lock.json"
RETRY_DELAYS_S = (5, 15, 30, 60, 120)
MAX_ERROR_RATE = 0.05
#: Configuration officielle (`config/evaluate_gt_config.yaml`), sauf le décideur.
CHECK_CONFIG: Mapping[str, Any] = {
    "tags_to_evaluate": None,
    "location_max_depth": 4,
    "decider": "rule_model",
}
MIN_CERTAINTY = 3
#: Passes d'alignement de l'original (`main(iteration)`, iteration < 3).
ALIGNMENT_PASSES = 3


class SpiaAttackError(ValueError):
    """Run inattaquable : corpus non SPIA, gold source absent ou divergent."""


class _Transport:
    """``call_api_with_param`` du code original → client du projet, appels journalisés."""

    def __init__(self, client: LlmClient, sleep: Callable[[float], None] = time.sleep,
                 *, max_output_tokens: int | None = None) -> None:
        self._client = client
        # Le code original n'envoie aucun max_tokens : sans plafond explicite,
        # celui du backend s'applique et tronque les profils multi-sujets longs.
        self._max_output_tokens = max_output_tokens
        self._sleep = sleep
        self._local = threading.local()

    def begin(self) -> None:
        self._local.calls = []
        self._local.fresh = False

    def fresh_samples(self, enabled: bool) -> None:
        """Nouvel échantillon du modèle (cache contourné) : ré-essai de l'original."""
        self._local.fresh = enabled

    def calls(self) -> list[dict[str, Any]]:
        return list(getattr(self._local, "calls", []))

    def __call__(self, prompt: str, temperature: float, max_tokens: int | None) -> str:
        record: dict[str, Any] = {"prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
        self._local.calls.append(record)
        for attempt, delay in enumerate((0, *RETRY_DELAYS_S)):
            if delay:
                self._sleep(delay)
            try:
                completion = self._client.complete(
                    prompt, temperature=temperature,
                    max_tokens=max_tokens if max_tokens is not None else self._max_output_tokens,
                    use_cache=not getattr(self._local, "fresh", False),
                )
                record.update(ok=True, cached=completion.cached)
                return completion.content
            except LlmBackendUnavailableError as exc:
                if not exc.retryable or attempt == len(RETRY_DELAYS_S):
                    record.update(ok=False, error=f"{type(exc).__name__}: {exc}")
                    raise
            except LlmError as exc:
                record.update(ok=False, error=f"{type(exc).__name__}: {exc}")
                raise
        raise AssertionError("inatteignable")


def _gold_rows(lock: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    source = (lock.get("data_version") or {}).get("source") or {}
    files = [Path(p) for p in source.get("files") or ()]
    if not files or any(not p.is_file() for p in files):
        raise SpiaAttackError("sources SPIA du lock d'ingestion introuvables : réacquérir SPIA")
    if fingerprint(files) != source.get("fingerprint"):
        raise SpiaAttackError("sources SPIA modifiées depuis l'ingestion : réingérer")
    rows: dict[str, dict[str, Any]] = {}
    for path in files:
        if path.suffix != ".jsonl":
            continue
        origin = "tab" if "tab" in path.stem.lower() else "panorama"
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            data_id = str(row["metadata"].get("data_id", row.get("id")))
            rows[f"spia:{data_id}"] = {**row, "_origin": origin, "_data_id": data_id}
    return rows


def attack_document(
    original: Any, transport: _Transport, gold: Mapping[str, Any], anonymized_text: str,
) -> dict[str, Any]:
    """Une ligne figée : sorties de chaque étape originale, ou l'erreur nommée."""
    data_id, dataset_type = gold["_data_id"], gold["_origin"]
    transport.begin()
    row: dict[str, Any] = {"data_id": data_id, "dataset_type": dataset_type}

    def failed(stage: str, error: Any) -> dict[str, Any]:
        return {**row, "status": "error", "error": f"{stage}: {error}", "llm_calls": transport.calls()}

    with tempfile.TemporaryDirectory(prefix="spia-") as tmp:
        files = {name: str(Path(tmp) / f"{name}.jsonl") for name in ("sa", "spc", "spnc")}
        ok, sa, number, error = original.infer.process_sa(
            anonymized_text, data_id, {}, files["sa"], dataset_type, False)
        if not ok:
            return failed("SA", error)
        ok, spc, error = original.infer.process_spc(anonymized_text, sa, data_id, files["spc"])
        if not ok:
            return failed("SPC", error)
        ok, spnc, error = original.infer.process_spnc(anonymized_text, sa, data_id, files["spnc"])
        if not ok:
            return failed("SPNC", error)
        responses = {name: Path(path).read_text(encoding="utf-8") for name, path in files.items()}
    ok, inference, used_fallback = original.infer.merge_results(spc, spnc, False)
    if not ok:
        return failed("concat", "fusion SPC/SPNC impossible")
    row.update(responses=responses, number_of_subjects=number, inference=inference,
               used_fallback=used_fallback)
    gt_subjects = gold["subjects"]
    # `main(iteration)` officiel : un document dont l'alignement échoue est
    # repris jusqu'à 3 passes (nouvel échantillon du modèle), puis évalué en
    # sujets gold seuls (`gt_only_subject`) — l'attaquant n'a relié aucun
    # sujet : ses PII gold comptent comme protégées.
    attempts: list[str] = []
    ok, pairs, response, stats = False, [], None, None
    for attempt in range(ALIGNMENT_PASSES):
        if not gt_subjects or not inference:
            attempts.append(f"annotations manquantes : A={len(gt_subjects)}, B={len(inference)}")
            continue
        transport.fresh_samples(attempt > 0)
        ok, pairs, response, error, stats = original.align.process_alignment(
            gold["text"], gt_subjects, inference, data_id, anonymized_text=anonymized_text)
        transport.fresh_samples(False)
        if ok:
            break
        attempts.append(str(error))
    row["alignment_attempts"] = attempts
    if ok:
        aligned = original.align.transform_to_gt_aligned_format(gt_subjects, inference, pairs)
        row["alignment_fallback"] = None
    else:
        if any(not call.get("ok") for call in transport.calls()):
            return failed("alignment", attempts[-1])
        fallback = original.align.gt_only_subject(
            [{"metadata": {"data_id": data_id}, "text": gold["text"], "annotation_A": gt_subjects}],
            data_id,
        )
        aligned = [{**subject, "matched": False} for subject in fallback["subjects"]]
        row["alignment_fallback"] = "gt_only_subject"
    subjects = []
    for subject in aligned:
        try:
            evaluations = original.check.evaluate_subject_annotations({
                "id": subject["id"], "description": subject["description"],
                "annotation_A": subject["PIIs"]["annotation_A"],
                "annotation_B": subject["PIIs"]["annotation_B"],
            }, dict(CHECK_CONFIG))
        except Exception as exc:  # noqa: BLE001 — `process_subject_wrapper` officiel
            # L'original vide alors les évaluations du sujet, qui sort du
            # calcul : une exclusion silencieuse. Ici : erreur du document.
            return failed("evaluation", f"sujet {subject['id']} : {type(exc).__name__}: {exc}")
        subjects.append({"subject_id": subject["id"], "matched": subject["matched"],
                         "description": subject["description"], "evaluations": evaluations})
    calls = transport.calls()
    swallowed = [call for call in calls if not call.get("ok")]
    if swallowed:
        # Panne avalée par le code original : le score 0 qui en résulte
        # passerait pour une protection (C3).
        return failed("llm", f"{len(swallowed)} appel(s) en échec masqué(s) par le code original : "
                             f"{swallowed[0].get('error')}")
    return {**row, "status": "ok", "error": None, "alignment_response": response,
            "matched_pairs": [list(pair) for pair in pairs or ()], "match_stats": stats,
            "evaluation": {"data_id": data_id, "number_of_subjects": number, "subjects": subjects},
            "llm_calls": calls}


def run_spia_attack(
    run_dir: Path, *, backend: str, workers: int | None = None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    if max_output_tokens is not None and max_output_tokens < 1:
        raise SpiaAttackError("max_output_tokens doit être un entier positif")
    run_dir = Path(run_dir)
    lock = json.loads((run_dir / "manifest.lock.json").read_text(encoding="utf-8"))
    run = lock.get("run") or {}
    if run.get("dataset") != "spia":
        raise SpiaAttackError(f"l'attaque SPIA ne s'applique qu'au corpus `spia` (run : {run.get('dataset')!r})")
    outputs = verify_run_outputs(run_dir, lock.get("outputs"), ("predictions.jsonl",),
                                 context=f"Attaque SPIA {run_dir}")
    gold = _gold_rows(lock)
    predictions = [json.loads(line) for line in
                   (run_dir / "predictions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    targets = [p for p in predictions if str(p.get("status")) in ("ok", "partial")]
    missing = [p["doc_id"] for p in targets if p["doc_id"] not in gold]
    if missing:
        raise SpiaAttackError(f"gold SPIA absent pour {len(missing)} document(s), ex. {missing[0]!r}")
    if any(not isinstance(p.get("anonymized_text"), str) for p in targets):
        raise SpiaAttackError("texte anonymisé absent : relancer predict")
    client = LlmClient.for_backend(backend)
    transport = _Transport(client, max_output_tokens=max_output_tokens)
    with original_spia() as original:
        original.client.install_transport(transport)
        try:
            def task(record: Mapping[str, Any]) -> dict[str, Any]:
                try:
                    result = attack_document(original, transport, gold[record["doc_id"]],
                                             str(record["anonymized_text"]))
                except LlmError as exc:
                    result = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
                return {"doc_id": record["doc_id"], **result}

            with ThreadPoolExecutor(max_workers=max(1, workers or client.backend.max_concurrency)) as pool:
                rows = sorted(pool.map(task, targets), key=lambda row: row["doc_id"])
        finally:
            original.client.install_transport(None)
    with atomic_write(run_dir / ATTACKS_NAME) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    errors = sum(1 for row in rows if row["status"] != "ok")
    error_rate = errors / len(rows) if rows else 1.0
    attack_lock = {
        "protocol": PROTOCOL,
        "protocol_version": PROTOCOL_VERSION,
        "official": {"repo": OFFICIAL_REPO, "commit": OFFICIAL_COMMIT,
                     "vendored_tree_sha256": tree_sha256(),
                     "shims": {"parsing.py": sha256_file(Path(__file__).with_name("parsing.py")),
                               "deviation": "JSON valide parsé avant clean_json_response"}},
        "attacker": {"backend": client.backend.name, "model": client.backend.model,
                     "extra_body": client.backend.extra_body,
                     "default_max_output_tokens": client.backend.max_output_tokens,
                     "max_output_tokens": max_output_tokens,
                     "temperature": 0.1, "temperature_source": "défaut de call_api_with_param officiel"},
        "config": {**CHECK_CONFIG, "min_certainty": MIN_CERTAINTY, "allow_fallback": False,
                   "deviation": "decider rule_model (arbitrage humain officiel non automatisable)"},
        "inputs": {"predictions.jsonl": outputs["predictions.jsonl"],
                   "gold_source_fingerprint": (lock.get("data_version") or {}).get("source", {}).get("fingerprint")},
        "outputs": {ATTACKS_NAME: sha256_file(run_dir / ATTACKS_NAME)},
        "documents": len(rows),
        "documents_error": errors,
        "error_rate": error_rate,
        "publishable": error_rate <= MAX_ERROR_RATE,
    }
    write_json(run_dir / ATTACK_LOCK_NAME, attack_lock)
    return attack_lock


__all__ = ["ATTACKS_NAME", "ATTACK_LOCK_NAME", "PROTOCOL", "SpiaAttackError", "attack_document",
           "run_spia_attack"]

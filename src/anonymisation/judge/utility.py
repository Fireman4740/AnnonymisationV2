"""Juge d'utilité « Mean Utility » (Staab et al., 2025 ; SPIA, Oh et al., 2026).

Reproduit ``UtilityEvaluator`` de SPIA (``maisonOP/spia@3fa78a1``, licence MIT),
lui-même repris de ``eth-sri/llm-anonymization`` (licence MIT) :

* prompt du juge mot pour mot (système + utilisateur concaténés, comme SPIA) ;
* lisibilité et sens notés 1-10, hallucinations 0/1 ;
* ROUGE-L F1 avec le paquet ``rouge_score`` et stemmer de Porter (SPIA) ;
* ``utility_comb = (lisibilité/10 + sens/10 + ROUGE-L) / 3`` = Mean Utility.

Écart assumé avec le code d'origine : les deux dépôts remplacent une réponse
illisible par des notes par défaut (lisibilité = sens = 1). C'est une valeur
par défaut silencieuse — ici, la réponse illisible est une ERREUR du document
(C3), comptée, jamais notée. Note : Staab et al. utilisent ROUGE-1 dans leur
combinaison, SPIA ROUGE-L ; on suit SPIA (cité par SPEC-07) et l'on fige les
deux valeurs pour permettre la comparaison.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from anonymisation.llm.client import LlmBackendUnavailableError, LlmClient, LlmError
from anonymisation.schema.integrity import locked_files, verify_pivot_files, verify_run_outputs
from anonymisation.schema.io import atomic_write, read_jsonl, sha256_file, write_json
from anonymisation.schema.models import Document

PROTOCOL = "mean-utility-spia"
PROTOCOL_VERSION = "1"
SOURCE = {"repo": "maisonOP/spia", "commit": "3fa78a1b3c75788c6294f40024fc79e1ef42923f"}
JUDGMENTS_NAME = "judgments.jsonl"
JUDGE_LOCK_NAME = "judge.lock.json"
RETRY_DELAYS_S = (5, 15, 30, 60, 120)
MAX_ERROR_RATE = 0.05
#: Nouveaux échantillons (cache contourné) quand la réponse du juge n'est pas
#: un JSON exploitable. Écart déclaré à SPIA, qui note alors 1/1/0 en
#: silence : on préfère un nouvel échantillon tracé à une note inventée ;
#: au-delà, le document reste en erreur.
PARSE_RESAMPLES = 2
#: Défaut de `call_api_with_param` dans le code SPIA d'origine.
JUDGE_TEMPERATURE = 0.1

SYSTEM_PROMPT = (
    "You are an expert text similarity scorer that carefully compares two texts and gives a "
    "score based on how similar they are. You follow the instructions and format precisely "
    "and you try to give a score as close to the ground truth as possible."
)
_USER_TEMPLATE = """You are a judge that must decide on a scale from 1-10 whether two texts, the original and the adapted, have the same meaning and content. 10 means they have exactly the same content and message while 1 means they are nothing alike. Before giving your final score give a brief step-by-step reasoning of your decision. Give your answer in the JSON format below:
{{
    "readability": {{
        "explanation": "<Is the adapted text as readable and understandable as the original text? Could a human read it without issues? Focus only on the adapted text without your knowledge of the original one.>",
        "score": <Number between 1 (unreadable) to 10 (equally readable as the original text)>
    }},
    "meaning": {{
        "explanation": "<Does the adapted text have the same meaning as the original text? Does it convey the same message?>",
        "score": <Number between 1 (different meaning) to 10 (same meaning)>
    }},
    "hallucinations": {{
        "explanation": "<Does the adapted text contain any information that was not present in the original text and that does not reflect the original text or did it correctly abstract and generalize the original text?>",
        "score": <Either 0 (contains new information) or 1 (contains no new information)>
    }}
}}

Original text:
{original_text}

Adapted text:
{anonymized_text}
"""


class JudgeError(ValueError):
    """Run non jugeable, ou réponse du juge inexploitable."""


def judge_prompt(original: str, anonymized: str) -> str:
    """Prompt complet, tel que SPIA l'envoie (``system\\n\\nuser``)."""
    user = _USER_TEMPLATE.format(original_text=original, anonymized_text=anonymized)
    return f"{SYSTEM_PROMPT}\n\n{user}"


def parse_judgment(response: str) -> dict[str, float]:
    """Notes du juge ; lève si une note manque ou sort de son échelle (jamais de défaut)."""
    start, end = response.find("{"), response.rfind("}") + 1
    try:
        payload = json.loads(response[start:end])
    except (json.JSONDecodeError, ValueError) as exc:
        raise JudgeError(f"réponse du juge non JSON : {response[:160]!r}") from exc
    if not isinstance(payload, dict):
        raise JudgeError("réponse du juge : mapping attendu")
    scores: dict[str, float] = {}
    for key, low, high in (("readability", 1, 10), ("meaning", 1, 10), ("hallucinations", 0, 1)):
        try:
            raw = payload[key]["score"]
            if isinstance(raw, bool):
                raise JudgeError(f"note `{key}` booléenne")
            value = float(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise JudgeError(f"note `{key}` absente ou non numérique") from exc
        if not low <= value <= high:
            raise JudgeError(f"note `{key}` = {value} hors de [{low}, {high}]")
        if key == "hallucinations" and value not in (0.0, 1.0):
            raise JudgeError("note `hallucinations` doit valoir 0 ou 1")
        scores[key] = value
    return scores


def rouge_scores(original: str, anonymized: str) -> dict[str, float]:
    try:
        from rouge_score import rouge_scorer
    except ImportError as exc:
        raise JudgeError("paquet `rouge-score` requis (extra `attack`)") from exc
    scorer = rouge_scorer.RougeScorer(["rouge1", "rougeL"], use_stemmer=True)
    result = scorer.score(original, anonymized)
    return {"rouge1": result["rouge1"].fmeasure, "rougeL": result["rougeL"].fmeasure}


def judge_one(
    doc_id: str, original: str, anonymized: str, complete: Callable[[str], tuple[str, bool]],
    resample: Callable[[str], tuple[str, bool]] | None = None,
) -> dict[str, Any]:
    prompt = judge_prompt(original, anonymized)
    base: dict[str, Any] = {
        "doc_id": doc_id,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    rejected: list[dict[str, Any]] = []
    try:
        response, cached = complete(prompt)
        while True:
            try:
                scores = parse_judgment(response)
                break
            except JudgeError as exc:
                if resample is None or len(rejected) >= PARSE_RESAMPLES:
                    raise
                rejected.append({"error": str(exc), "response": response, "cached": cached})
                response, cached = resample(prompt)
    except (LlmError, JudgeError) as exc:
        return {**base, "status": "error", "error": f"{type(exc).__name__}: {exc}",
                **({"rejected_responses": rejected} if rejected else {})}
    if rejected:
        base["rejected_responses"] = rejected
    rouge = rouge_scores(original, anonymized)
    readability = scores["readability"] / 10
    meaning = scores["meaning"] / 10
    return {
        **base,
        "status": "ok",
        "error": None,
        "cached": cached,
        "response": response,
        "readability": scores["readability"],
        "meaning": scores["meaning"],
        "hallucinations": scores["hallucinations"],
        "rouge1": rouge["rouge1"],
        "rougeL": rouge["rougeL"],
        "utility_model": (readability + meaning) / 2,
        "utility_comb": (readability + meaning + min(max(rouge["rougeL"], 0.0), 1.0)) / 3,
    }


def _complete(
    client: LlmClient, prompt: str, sleep: Callable[[float], None] = time.sleep, *, use_cache: bool = True,
) -> tuple[str, bool]:
    for attempt, delay in enumerate((0, *RETRY_DELAYS_S)):
        if delay:
            sleep(delay)
        try:
            # `call_api_with_param` SPIA : température 0,1 par défaut.
            completion = client.complete(prompt, temperature=JUDGE_TEMPERATURE, use_cache=use_cache)
            return completion.content, completion.cached
        except LlmBackendUnavailableError:
            if attempt == len(RETRY_DELAYS_S):
                raise
    raise AssertionError("inatteignable")


def run_judge(
    run_dir: Path, *, backend: str, processed_root: Path, workers: int | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    lock = json.loads((run_dir / "manifest.lock.json").read_text(encoding="utf-8"))
    run = lock.get("run") or {}
    dataset, split = str(run["dataset"]), str(run["split"])
    context = f"Juge {run_dir}"
    outputs = verify_run_outputs(run_dir, lock.get("outputs"), ("predictions.jsonl",), context=context)
    verify_pivot_files(processed_root / dataset, split, ("documents.jsonl",),
                       locked_files(lock.get("data_version"), context=context), context=context,
                       required=("documents.jsonl",))
    texts = {d.doc_id: d.text for d in read_jsonl(processed_root / dataset / split / "documents.jsonl", Document)}
    predictions = [
        json.loads(line) for line in (run_dir / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    targets = [p for p in predictions if str(p.get("status")) in ("ok", "partial")]
    ids = [p["doc_id"] for p in targets]
    if len(set(ids)) != len(ids) or any(i not in texts for i in ids):
        raise JudgeError("doc_id dupliqué ou absent du pivot gold")
    if any(not isinstance(p.get("anonymized_text"), str) for p in targets):
        raise JudgeError("texte anonymisé absent : relancer predict")
    client = LlmClient.for_backend(backend)

    def task(record: Mapping[str, Any]) -> dict[str, Any]:
        doc_id = str(record["doc_id"])
        return judge_one(doc_id, texts[doc_id], str(record["anonymized_text"]),
                         lambda prompt: _complete(client, prompt),
                         resample=lambda prompt: _complete(client, prompt, use_cache=False))

    with ThreadPoolExecutor(max_workers=max(1, workers or client.backend.max_concurrency)) as pool:
        rows = sorted(pool.map(task, targets), key=lambda row: row["doc_id"])
    with atomic_write(run_dir / JUDGMENTS_NAME) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    errors = sum(1 for row in rows if row["status"] != "ok")
    error_rate = errors / len(rows) if rows else 1.0
    judge_lock = {
        "protocol": PROTOCOL,
        "protocol_version": PROTOCOL_VERSION,
        "source": SOURCE,
        "judge": {
            "backend": client.backend.name,
            "model": client.backend.model,
            "temperature": JUDGE_TEMPERATURE,
            "parse_resamples_max": PARSE_RESAMPLES,
            "deviation": "JSON invalide : rééchantillonnage tracé au lieu des notes par défaut SPIA",
            "prompt_module_sha256": sha256_file(Path(__file__)),
        },
        "inputs": {
            "predictions.jsonl": outputs["predictions.jsonl"],
            "documents.jsonl": sha256_file(processed_root / dataset / split / "documents.jsonl"),
        },
        "outputs": {JUDGMENTS_NAME: sha256_file(run_dir / JUDGMENTS_NAME)},
        "documents": len(rows),
        "documents_error": errors,
        "error_rate": error_rate,
        "publishable": error_rate <= MAX_ERROR_RATE,
    }
    write_json(run_dir / JUDGE_LOCK_NAME, judge_lock)
    return judge_lock


__all__ = ["JUDGE_LOCK_NAME", "JUDGMENTS_NAME", "JudgeError", "judge_one", "parse_judgment", "run_judge"]

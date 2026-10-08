"""Utilite textuelle et Mean Utility (SPEC-07 v2.0 §6.A, ticket G-4)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from anonymisation.metrics.contracts import MetricDirection, MetricStatus, MetricValue

_TOKEN_RE = re.compile(r"(?u)\b\w+\b")


class UtilityJudge(Protocol):
    """Interface minimale d'un juge Readability/Meaning.

    Le juge peut etre local ou distant ; le coeur ne l'importe jamais et ne
    l'invoque que lorsqu'il est explicitement fourni.
    """

    name: str

    def __call__(self, original: str, anonymized: str) -> Mapping[str, float] | Sequence[float]: ...


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(text.casefold()))


def _lcs_length(left: Sequence[str], right: Sequence[str]) -> int:
    previous = [0] * (len(right) + 1)
    for left_token in left:
        current = [0]
        for index, right_token in enumerate(right, start=1):
            if left_token == right_token:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]


def rouge_l(reference: str, candidate: str) -> float:
    """Retourne le ROUGE-L F1 token-level, sans dependance externe."""
    reference_tokens = _tokens(reference)
    candidate_tokens = _tokens(candidate)
    if not reference_tokens and not candidate_tokens:
        return 1.0
    if not reference_tokens or not candidate_tokens:
        return 0.0
    lcs = _lcs_length(reference_tokens, candidate_tokens)
    recall = lcs / len(reference_tokens)
    precision = lcs / len(candidate_tokens)
    return 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0


def _score_components(result: Mapping[str, float] | Sequence[float]) -> tuple[float, float]:
    if isinstance(result, Mapping):
        try:
            readability = float(result["readability"])
            meaning = float(result["meaning"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "le juge doit retourner readability et meaning dans [0, 1]"
            ) from exc
    else:
        if len(result) != 2:
            raise ValueError("le juge doit retourner (readability, meaning)")
        try:
            readability, meaning = (float(result[0]), float(result[1]))
        except (TypeError, ValueError) as exc:
            raise ValueError("les scores du juge doivent être numériques") from exc
    for name, value in (("readability", readability), ("meaning", meaning)):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} doit être dans [0, 1]")
    return readability, meaning


def mean_utility(
    original: str,
    anonymized: str,
    *,
    judge: UtilityJudge | Callable[[str, str], Mapping[str, float] | Sequence[float]] | None = None,
    judge_name: str | None = None,
) -> MetricValue:
    """Calcule Mean Utility ou retourne explicitement ``UNAVAILABLE``.

    Sans juge, ROUGE-L est calculé pour diagnostic mais aucune moyenne partielle
    n'est publiée : Readability et Meaning sont indispensables à la définition
    de la métrique.
    """
    rouge = rouge_l(original, anonymized)
    if judge is None:
        return MetricValue(
            name="mean_utility",
            value=None,
            protocol="mean-utility",
            protocol_version="1",
            status=MetricStatus.UNAVAILABLE,
            direction=MetricDirection.MAXIMIZE,
            details={
                "components": {"readability": None, "meaning": None, "rouge_l": rouge},
                "judge": None,
                "reason": "aucun juge Readability/Meaning configuré",
            },
        )

    readability, meaning = _score_components(judge(original, anonymized))
    name = judge_name or str(getattr(judge, "name", "unnamed-judge"))
    return MetricValue(
        name="mean_utility",
        value=(readability + meaning + rouge) / 3.0,
        protocol="mean-utility",
        protocol_version="1",
        status=MetricStatus.DIAGNOSTIC,
        direction=MetricDirection.MAXIMIZE,
        details={
            "components": {
                "readability": readability,
                "meaning": meaning,
                "rouge_l": rouge,
            },
            "judge": name,
        },
    )


__all__ = ["UtilityJudge", "mean_utility", "rouge_l"]


def mean_utility_over_documents(
    *,
    pairs: Sequence[tuple[str, str]],
    rouge_scores: Sequence[float],
    judge: Any,
    judge_name: str | None,
) -> MetricValue:
    """Moyenne document par document de Mean Utility (SPEC-07).

    Sans juge, la métrique reste ``UNAVAILABLE`` par définition (Readability et
    Meaning sont indispensables) : on réutilise alors les ROUGE-L déjà calculés
    plutôt que de relancer un LCS. Avec juge, chaque document est évalué
    séparément puis moyenné — jamais le corpus concaténé.
    """
    rouge_mean = sum(rouge_scores) / len(rouge_scores) if rouge_scores else None
    if judge is None:
        return MetricValue(
            name="mean_utility",
            value=None,
            protocol="mean-utility",
            protocol_version="1",
            status=MetricStatus.UNAVAILABLE,
            direction=MetricDirection.MAXIMIZE,
            details={
                "components": {"readability": None, "meaning": None, "rouge_l": rouge_mean},
                "judge": None,
                "documents": len(rouge_scores),
                "reason": "aucun juge Readability/Meaning configuré",
            },
        )

    per_doc = [
        mean_utility(original=original, anonymized=anonymized, judge=judge, judge_name=judge_name)
        for original, anonymized in pairs
    ]
    values = [result.value for result in per_doc if result.value is not None]
    if not values:
        return MetricValue(
            name="mean_utility",
            value=None,
            protocol="mean-utility",
            protocol_version="1",
            status=MetricStatus.UNAVAILABLE,
            direction=MetricDirection.MAXIMIZE,
            details={
                "components": {"readability": None, "meaning": None, "rouge_l": rouge_mean},
                "judge": judge_name,
                "documents": 0,
                "reason": "aucun document évaluable par le juge",
            },
        )

    def _component(key: str) -> float | None:
        scores = [
            (result.details or {}).get("components", {}).get(key)
            for result in per_doc
            if result.value is not None
        ]
        usable = [float(s) for s in scores if s is not None]
        return sum(usable) / len(usable) if usable else None

    return MetricValue(
        name="mean_utility",
        value=sum(values) / len(values),
        protocol="mean-utility",
        protocol_version="1",
        status=MetricStatus.DIAGNOSTIC,
        direction=MetricDirection.MAXIMIZE,
        details={
            "components": {
                "readability": _component("readability"),
                "meaning": _component("meaning"),
                "rouge_l": _component("rouge_l"),
            },
            "judge": judge_name or str(getattr(judge, "name", "unnamed-judge")),
            "documents": len(values),
            "aggregation": "moyenne par document",
        },
    )


def mean_utility_from_judgments(
    rows: Sequence[Mapping[str, Any]], lock: Mapping[str, Any]
) -> MetricValue:
    """Mean Utility (SPIA) depuis des jugements FIGÉS par ``anonv2 judge`` (C5).

    Moyenne par document de ``utility_comb``, intervalle bootstrap par
    document. Au-delà de 5 % de documents non jugés, ``UNAVAILABLE`` (C4).
    """
    from anonymisation.metrics.uncertainty import bootstrap_interval
    from anonymisation.metrics.uncertainty import mean as _mean

    ok = [r for r in rows if r.get("status") == "ok"]
    errors = len(rows) - len(ok)
    error_rate = errors / len(rows) if rows else 1.0
    details: dict[str, Any] = {
        "protocol": lock.get("protocol"),
        "source": lock.get("source"),
        "judge": lock.get("judge"),
        "documents_judged": len(rows),
        "documents_error": errors,
        "error_rate": error_rate,
    }
    if not ok or error_rate > 0.05:
        return MetricValue(
            name="mean_utility", value=None, protocol=str(lock.get("protocol")),
            protocol_version=str(lock.get("protocol_version")), status=MetricStatus.UNAVAILABLE,
            direction=MetricDirection.MAXIMIZE,
            details={**details, "reason": f"{errors}/{len(rows)} document(s) non jugé(s) (> 5 %, C4)"},
        )
    values = [float(r["utility_comb"]) for r in ok]
    for row, value in zip(ok, values, strict=True):
        readability, meaning = float(row["readability"]), float(row["meaning"])
        rouge, rouge1 = float(row["rougeL"]), float(row["rouge1"])
        if (not 1 <= readability <= 10 or not 1 <= meaning <= 10
                or not 0 <= rouge <= 1 or not 0 <= rouge1 <= 1
                or row["hallucinations"] not in (0, 1)):
            raise ValueError(f"jugement {row.get('doc_id')} : composants hors échelle")
        expected = (readability / 10 + meaning / 10 + rouge) / 3
        if not 0 <= value <= 1 or abs(value - expected) > 1e-12:
            raise ValueError(f"jugement {row.get('doc_id')} : utility_comb incohérent")
    details.update(
        components={
            "readability": _mean([float(r["readability"]) / 10 for r in ok]),
            "meaning": _mean([float(r["meaning"]) / 10 for r in ok]),
            "rouge_l": _mean([float(r["rougeL"]) for r in ok]),
            "rouge_1": _mean([float(r["rouge1"]) for r in ok]),
            "hallucination_free": _mean([float(r["hallucinations"]) for r in ok]),
        },
        ci95=bootstrap_interval(values, _mean, unit="document"),
        aggregation="moyenne par document de (lisibilité/10 + sens/10 + ROUGE-L)/3",
    )
    return MetricValue(
        name="mean_utility", value=_mean(values), protocol=str(lock.get("protocol")),
        protocol_version=str(lock.get("protocol_version")), status=MetricStatus.DIAGNOSTIC,
        direction=MetricDirection.MAXIMIZE, details=details,
    )

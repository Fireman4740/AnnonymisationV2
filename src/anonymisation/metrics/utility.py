"""Utilite textuelle et Mean Utility (SPEC-07 v2.0 §6.A, ticket G-4)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

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

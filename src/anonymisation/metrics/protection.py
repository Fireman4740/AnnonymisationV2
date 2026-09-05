"""Metriques de protection multi-sujets (SPEC-07 v2.0 §5, ticket G-2).

CPR pondère les PII ; IPR pondère les sujets. Les deux valeurs sont
volontairement séparées : publier seulement l'une d'elles masque les sujets
avec peu ou beaucoup de PII.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite
from typing import Any, TypeAlias

from anonymisation.metrics.contracts import MetricContractError

CategoryCounts: TypeAlias = Mapping[str, tuple[int, int]]


@dataclass(frozen=True)
class SubjectOutcome:
    """Résultat de l'inférence adversariale pour un sujet.

    ``pii_total`` est ``O_i`` et ``pii_still_inferable`` est ``A_i``. La
    ventilation facultative ``pii_by_category`` porte ``{categorie:
    (O_i_categorie, A_i_categorie)}`` et permet l'analyse pondérée sans
    modifier les résultats uniformes publiés par SPIA.
    """

    subject_id: str
    pii_total: int
    pii_still_inferable: int
    pii_by_category: CategoryCounts = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.subject_id.strip():
            raise ValueError("subject_id ne peut pas être vide")
        for name, value in (
            ("pii_total", self.pii_total),
            ("pii_still_inferable", self.pii_still_inferable),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} doit être un entier positif ou nul")
        if self.pii_still_inferable > self.pii_total:
            raise ValueError("pii_still_inferable ne peut pas dépasser pii_total")
        category_total = 0
        category_inferable = 0
        for category, counts in self.pii_by_category.items():
            if not str(category).strip():
                raise ValueError("une catégorie de PII ne peut pas être vide")
            if (
                not isinstance(counts, tuple)
                or len(counts) != 2
                or any(isinstance(value, bool) or not isinstance(value, int) for value in counts)
            ):
                raise ValueError(
                    "pii_by_category doit associer chaque catégorie à (total, inferable)"
                )
            total, inferable = counts
            if total < 0 or inferable < 0 or inferable > total:
                raise ValueError(f"comptes invalides pour la catégorie {category!r}")
            category_total += total
            category_inferable += inferable
        if self.pii_by_category and (
            category_total != self.pii_total or category_inferable != self.pii_still_inferable
        ):
            raise ValueError(
                "pii_by_category doit totaliser pii_total et pii_still_inferable"
            )


def _validate_weights(weights: Mapping[str, float] | None) -> dict[str, float]:
    result = {str(category): float(weight) for category, weight in (weights or {}).items()}
    if any(not isfinite(weight) or weight < 0.0 for weight in result.values()):
        raise ValueError("les poids de catégorie doivent être finis et positifs ou nuls")
    if result and not any(weight > 0.0 for weight in result.values()):
        raise ValueError("au moins un poids de catégorie doit être strictement positif")
    return result


def _weighted_counts(
    outcome: SubjectOutcome, weights: Mapping[str, float] | None
) -> tuple[float, float]:
    validated = _validate_weights(weights)
    if not validated or not outcome.pii_by_category:
        return float(outcome.pii_total), float(outcome.pii_still_inferable)
    total = sum(
        counts[0] * validated.get(category, 1.0)
        for category, counts in outcome.pii_by_category.items()
    )
    inferable = sum(
        counts[1] * validated.get(category, 1.0)
        for category, counts in outcome.pii_by_category.items()
    )
    return total, inferable


def collective_protection_rate(
    subjects: Iterable[SubjectOutcome], *, weights: Mapping[str, float] | None = None
) -> float | None:
    """Calcule CPR = ``1 - ΣA_i / ΣO_i``.

    ``None`` signale l'absence de PII dans tout l'échantillon ; ce n'est pas
    une protection nulle. Les poids sont uniformes par défaut pour rester
    comparable à SPIA.
    """
    totals = [
        _weighted_counts(subject, weights)
        for subject in subjects
    ]
    denominator = sum(total for total, _ in totals)
    if denominator == 0.0:
        return None
    return 1.0 - sum(inferable for _, inferable in totals) / denominator


def individual_protection_rate(
    subjects: Iterable[SubjectOutcome], *, weights: Mapping[str, float] | None = None
) -> float | None:
    """Calcule IPR = moyenne des ``1 - A_i/O_i`` pour ``O_i > 0``.

    Les sujets sans PII gold sont explicitement exclus du dénominateur, comme
    le demande le protocole SPIA ; ils ne doivent jamais provoquer une division
    par zéro ni tirer artificiellement la moyenne vers zéro.
    """
    rates: list[float] = []
    for subject in subjects:
        total, inferable = _weighted_counts(subject, weights)
        if total == 0.0:
            continue
        rates.append(1.0 - inferable / total)
    return sum(rates) / len(rates) if rates else None


def _normalise_guess(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.strip().casefold())
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _normalise_guess(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(sorted(_normalise_guess(item) for item in value))
    return value


def _guess_quality(guess: Any, truth: Any) -> float:
    guessed = _normalise_guess(guess)
    expected = _normalise_guess(truth)
    if guessed == expected:
        return 1.0
    if guessed is None or expected is None:
        return 0.0
    if isinstance(guessed, str) and isinstance(expected, str):
        guessed_tokens = set(guessed.split())
        expected_tokens = set(expected.split())
        if guessed in expected or expected in guessed or guessed_tokens & expected_tokens:
            return 0.5
    if isinstance(guessed, tuple) and isinstance(expected, tuple) and set(guessed) & set(expected):
        return 0.5
    return 0.0


def adversarial_accuracy(guesses: Any, truth: Any) -> float:
    """Score une inférence adversariale : exact=1, partiel=0.5, faux=0.

    Si ``truth`` est scalaire et ``guesses`` est une séquence, le meilleur
    candidat (top-k) est retenu. Pour deux séquences de même longueur, le
    score est la moyenne des comparaisons positionnelles.
    """
    scalar_guess = isinstance(guesses, (str, bytes)) or not isinstance(guesses, Sequence)
    scalar_truth = isinstance(truth, (str, bytes)) or not isinstance(truth, Sequence)
    if scalar_truth and not scalar_guess:
        candidates = list(guesses)
        return max((_guess_quality(candidate, truth) for candidate in candidates), default=0.0)
    if not scalar_truth and not scalar_guess:
        guess_values = list(guesses)
        truth_values = list(truth)
        if len(guess_values) != len(truth_values):
            raise ValueError("guesses et truth doivent avoir la même longueur")
        return (
            sum(
                _guess_quality(guess, expected)
                for guess, expected in zip(guess_values, truth_values, strict=True)
            )
            / len(truth_values)
            if truth_values
            else 0.0
        )
    return _guess_quality(guesses, truth)


def _metric_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, Mapping) and "value" in value:
        return value["value"] is not None
    return True


def assert_published_together(metrics: Mapping[str, Any]) -> None:
    """Refuse une scorecard qui publie CPR sans IPR, ou l'inverse."""
    values = {str(key).casefold(): value for key, value in metrics.items()}
    cpr = values.get("cpr")
    ipr = values.get("ipr")
    if _metric_present(cpr) != _metric_present(ipr):
        raise MetricContractError(
            "CPR et IPR doivent être publiés ensemble, ou être tous deux absents"
        )


__all__ = [
    "SubjectOutcome",
    "adversarial_accuracy",
    "assert_published_together",
    "collective_protection_rate",
    "individual_protection_rate",
]

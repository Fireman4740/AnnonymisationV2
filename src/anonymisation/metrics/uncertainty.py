"""Intervalles de confiance par bootstrap en grappes (EPIC-H H-7).

Pourquoi : une scorecard sans incertitude ne permet de trancher **aucune**
comparaison. Sur un corpus de quelques centaines de documents, deux systèmes
séparés de 2 points de rappel peuvent être statistiquement indiscernables ;
les classer sur la valeur ponctuelle reviendrait à publier du bruit.

Choix de méthode
----------------
* **Grappes** : l'unité rééchantillonnée est celle qui rend les observations
  indépendantes — le document pour les métriques de spans et d'entités, le
  sujet pour CPR/IPR et TRIR. Rééchantillonner des spans ou des PII isolés
  ignorerait leur corrélation au sein d'un document et produirait des
  intervalles trop étroits.
* **Percentile**, niveau 95 %, 1 000 réplicats par défaut : simple, sans
  hypothèse de normalité, suffisant pour des proportions bornées.
* **Déterminisme** : chaque métrique tire avec un générateur neuf initialisé
  par la même graine. Ajouter une métrique ne décale pas les tirages des
  autres, et deux exécutions de ``score`` restent identiques bit à bit.

Le module ne dépend que de la bibliothèque standard : ``score`` reste hors
ligne et sans numpy (C5).
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from operator import itemgetter
from typing import Any, Final, TypeVar

T = TypeVar("T")

BOOTSTRAP_REPLICATES: Final[int] = 1000
BOOTSTRAP_SEED: Final[int] = 20261001
CONFIDENCE_LEVEL: Final[float] = 0.95
METHOD: Final[str] = "cluster-bootstrap-percentile"


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Quantile par interpolation linéaire (type 7, comme numpy par défaut)."""
    position = q * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    fraction = position - low
    return sorted_values[low] * (1.0 - fraction) + sorted_values[high] * fraction


def bootstrap_interval(
    units: Sequence[T],
    statistic: Callable[[Sequence[T]], float | None],
    *,
    unit: str,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
    level: float = CONFIDENCE_LEVEL,
) -> dict[str, Any] | None:
    """Intervalle percentile de ``statistic`` en rééchantillonnant ``units``.

    Retourne ``None`` si l'intervalle n'est pas défini : moins de deux unités,
    ou statistique indéfinie sur l'échantillon complet. Les réplicats où la
    statistique est indéfinie (ex. aucun gold tiré) sont exclus et **comptés**
    dans ``undefined_replicates`` — jamais remplacés par 0.
    """
    if replicates < 1:
        raise ValueError("replicates doit être ≥ 1")
    if not 0.0 < level < 1.0:
        raise ValueError("level doit être dans ]0, 1[")
    n = len(units)
    if n < 2 or statistic(units) is None:
        return None
    rng = random.Random(seed)
    values: list[float] = []
    undefined = 0
    for _ in range(replicates):
        # `choices` tire en C : ~5× plus rapide qu'une boucle de randrange,
        # ce qui garde le bootstrap praticable sur des corpus de 10⁵ documents.
        sample = rng.choices(units, k=n)
        value = statistic(sample)
        if value is None:
            undefined += 1
        else:
            values.append(float(value))
    if not values:
        return None
    values.sort()
    alpha = (1.0 - level) / 2.0
    return {
        "low": _quantile(values, alpha),
        "high": _quantile(values, 1.0 - alpha),
        "level": level,
        "method": METHOD,
        "unit": unit,
        "units": n,
        "replicates": replicates,
        "undefined_replicates": undefined,
        "seed": seed,
    }


# --------------------------------------------------------------------------- #
# Statistiques usuelles sur unités pré-agrégées
# --------------------------------------------------------------------------- #
def ratio_of_sums(numerator: int, denominator: int) -> Callable[[Sequence[Sequence[float]]], float | None]:
    """Σ num / Σ den sur des tuples d'unités — micro-moyenne (rappel, précision…)."""

    num_of = itemgetter(numerator)
    den_of = itemgetter(denominator)

    def statistic(sample: Sequence[Sequence[float]]) -> float | None:
        den = sum(map(den_of, sample))
        return sum(map(num_of, sample)) / den if den else None

    return statistic


def complement_ratio_of_sums(
    numerator: int, denominator: int
) -> Callable[[Sequence[Sequence[float]]], float | None]:
    """1 − Σ num / Σ den — CPR à partir de tuples ``(A_i, O_i)``."""
    ratio = ratio_of_sums(numerator, denominator)

    def statistic(sample: Sequence[Sequence[float]]) -> float | None:
        value = ratio(sample)
        return None if value is None else 1.0 - value

    return statistic


def mean(sample: Sequence[float]) -> float | None:
    """Moyenne simple — macro-moyenne par unité (IPR, ROUGE-L par document)."""
    return sum(sample) / len(sample) if sample else None


def f1_of_counts(sample: Sequence[Sequence[float]]) -> float | None:
    """F1 micro à partir de tuples ``(tp, fp, fn)``."""
    tp = sum(row[0] for row in sample)
    fp = sum(row[1] for row in sample)
    fn = sum(row[2] for row in sample)
    if tp + fp == 0 or tp + fn == 0:
        return None
    return 2.0 * tp / (2.0 * tp + fp + fn)


def with_interval(metric: dict[str, Any], interval: dict[str, Any] | None) -> dict[str, Any]:
    """Copie de ``metric`` avec l'intervalle rangé dans ``details.ci95``.

    Une métrique sans valeur (``UNAVAILABLE``) est rendue inchangée ; une
    métrique avec valeur mais sans intervalle défini le dit explicitement.
    """
    if metric.get("value") is None:
        return metric
    ci = interval if interval is not None else {
        "reason": "intervalle non défini (moins de deux unités indépendantes)"
    }
    return {**metric, "details": {**(metric.get("details") or {}), "ci95": ci}}


__all__ = [
    "BOOTSTRAP_REPLICATES",
    "BOOTSTRAP_SEED",
    "CONFIDENCE_LEVEL",
    "with_interval",
    "bootstrap_interval",
    "complement_ratio_of_sums",
    "f1_of_counts",
    "mean",
    "ratio_of_sums",
]

"""Formules canoniques de qualité du score de risque (SPEC-07 §4).

Pourquoi ce module : trois définitions de MALE-k coexistaient (SPEC-07
``|ln(k̂+1) − ln(k+1)|``, ``|ln(k̂/k)|`` dans le contrôle hybride, ``|log2|``
sur le k non calibré dans l'étalonnage). Trois chiffres différents sous un
même nom rendent toute comparaison impossible. La spec étant normative, une
seule implémentation existe désormais, et tout producteur l'importe.

Conventions (SPEC-07 §4, précisées par EPIC-H H-1) :

* ``MALE_k = moyenne |ln(k̂ + 1) − ln(k + 1)|`` — le ``+1`` borne le terme
  quand ``k̂`` ou ``k`` vaut 0 et compresse les grands ``k``.
* Brier et ECE comparent le risque prédit au **risque gold** ``R = 1/k``
  (modèle prosecutor), et non à un événement binaire : les k gold de
  RAT-Bench/PUMS sont des tailles de classe, pas des ré-identifications
  observées. ECE porte donc ici sur une cible continue ; le préciser à côté
  du chiffre est obligatoire.
* ECE : ``B`` bacs d'**équi-effectif** sur le risque prédit (défaut 10). La
  valeur dépend de ``B`` ; :func:`ece_sensitivity` publie la courbe
  ``B ∈ {5, 10, 15, 20}`` pour que ce choix ne soit pas un paramètre caché.

Le module ne dépend que de la bibliothèque standard.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Final

DEFAULT_BINS: Final[int] = 10
SENSITIVITY_BINS: Final[tuple[int, ...]] = (5, 10, 15, 20)


def male_k(pairs: Sequence[tuple[float, float]]) -> float | None:
    """MALE-k de SPEC-07 sur des couples ``(k_prédit, k_vrai)``."""
    if not pairs:
        return None
    for k_pred, k_true in pairs:
        if k_pred < 0 or k_true < 0 or not (math.isfinite(k_pred) and math.isfinite(k_true)):
            raise ValueError(f"k invalide pour MALE-k : prédit={k_pred}, vrai={k_true}")
    return sum(abs(math.log(k_pred + 1.0) - math.log(k_true + 1.0)) for k_pred, k_true in pairs) / len(pairs)


def brier(pairs: Sequence[tuple[float, float]]) -> float | None:
    """Erreur quadratique moyenne entre risque prédit et risque gold."""
    if not pairs:
        return None
    return sum((pred - true) ** 2 for pred, true in pairs) / len(pairs)


def ece_equal_mass(pairs: Sequence[tuple[float, float]], *, n_bins: int = DEFAULT_BINS) -> float | None:
    """ECE sur bacs d'équi-effectif du risque prédit.

    Égalités de risque prédit départagées par le risque gold puis par l'ordre
    d'entrée : le résultat est déterministe. ``None`` si aucun couple — jamais
    0.0, qui passerait pour une calibration parfaite.
    """
    n = len(pairs)
    if n == 0:
        return None
    if n_bins < 1:
        raise ValueError("n_bins doit être ≥ 1")
    bins = min(n_bins, n)
    ordered = sorted(range(n), key=lambda i: (pairs[i][0], pairs[i][1], i))
    size, remainder = divmod(n, bins)
    ece = 0.0
    position = 0
    for b in range(bins):
        count = size + (1 if b < remainder else 0)
        chunk = ordered[position : position + count]
        position += count
        mean_pred = sum(pairs[i][0] for i in chunk) / count
        mean_true = sum(pairs[i][1] for i in chunk) / count
        ece += (count / n) * abs(mean_pred - mean_true)
    return ece


def ece_sensitivity(
    pairs: Sequence[tuple[float, float]], bins: Sequence[int] = SENSITIVITY_BINS
) -> dict[str, float | None]:
    """ECE pour plusieurs nombres de bacs — le choix de ``B`` n'est pas neutre."""
    return {str(b): ece_equal_mass(pairs, n_bins=b) for b in bins}


__all__ = [
    "DEFAULT_BINS",
    "SENSITIVITY_BINS",
    "brier",
    "ece_equal_mass",
    "ece_sensitivity",
    "male_k",
]

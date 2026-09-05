"""Application des décisions d'anonymisation sur le texte original.

Points de correction critiques (voir tests) :

* Les décisions sont appliquées **de droite à gauche** (offsets décroissants)
  pour que le remplacement d'un span ne décale pas les offsets des spans
  suivants — tous les offsets de :class:`AnonymizationDecision` réfèrent
  toujours au texte ORIGINAL, jamais à un texte partiellement transformé.
* Deux décisions dont les intervalles ``[start, end)`` se chevauchent sont un
  bug amont (chevauchement silencieux = texte corrompu) : on lève une
  exception explicite listant les offsets fautifs plutôt que de choisir un
  ordre arbitraire.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from anonymisation.transform.decisions import Action, AnonymizationDecision


class OverlappingDecisionsError(ValueError):
    """Deux décisions ou plus se chevauchent sur le texte original."""


@dataclass(frozen=True)
class TransformResult:
    """Résultat immuable de l'application d'un ensemble de décisions."""

    original_text: str
    anonymized_text: str
    decisions: tuple[AnonymizationDecision, ...]
    mapping: dict[str, str] = field(default_factory=dict)


def _check_bounds(text: str, decisions: Sequence[AnonymizationDecision]) -> None:
    offenders = [
        (d.start, d.end)
        for d in decisions
        if d.start < 0 or d.end > len(text)
    ]
    if offenders:
        raise ValueError(
            f"Décisions hors bornes du texte (longueur={len(text)}) : {offenders}"
        )


def _check_no_overlap(decisions: Sequence[AnonymizationDecision]) -> None:
    ordered = sorted(decisions, key=lambda d: d.start)
    overlaps: list[tuple[int, int, int, int]] = []
    for previous, current in pairwise(ordered):
        if current.start < previous.end:
            overlaps.append((previous.start, previous.end, current.start, current.end))
    if overlaps:
        raise OverlappingDecisionsError(
            f"Décisions chevauchantes (offsets sur le texte original) : {overlaps}"
        )


def apply_decisions(text: str, decisions: Sequence[AnonymizationDecision]) -> TransformResult:
    """Applique ``decisions`` sur ``text`` et retourne un :class:`TransformResult`.

    ``decisions`` peut être fournie dans n'importe quel ordre : la fonction
    trie et applique de droite à gauche en interne. Les décisions ``KEEP``
    sont acceptées (aucun effet sur le texte) mais restent dans la trace pour
    l'explicabilité.
    """
    decisions = tuple(decisions)
    _check_bounds(text, decisions)
    _check_no_overlap(decisions)

    # Application de droite à gauche : trier par start décroissant garantit
    # que remplacer un span ne modifie jamais les offsets des spans restant à
    # traiter, tous relatifs au texte original.
    ordered_desc = sorted(decisions, key=lambda d: d.start, reverse=True)

    result_text = text
    for decision in ordered_desc:
        if decision.action is Action.KEEP:
            continue
        actual = text[decision.start : decision.end]
        if actual != decision.original:
            raise ValueError(
                f"Décision incohérente avec le texte original à [{decision.start}:{decision.end}] : "
                f"attendu {decision.original!r}, trouvé {actual!r}"
            )
        result_text = result_text[: decision.start] + decision.replacement + result_text[decision.end :]

    mapping: dict[str, str] = {}
    for decision in decisions:
        if decision.action is not Action.KEEP:
            mapping[decision.original] = decision.replacement

    return TransformResult(
        original_text=text,
        anonymized_text=result_text,
        decisions=decisions,
        mapping=mapping,
    )

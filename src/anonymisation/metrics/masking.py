"""Couverture des masques **appliqués** (EPIC-H H-8).

Une annotation détectée ne prouve pas que son texte a été transformé : un
système peut détecter puis décider ``KEEP``, ou masquer un autre intervalle.
Cette mesure lit les **décisions** du run (``decisions`` de chaque
prédiction), ignore ``KEEP``, fusionne les intervalles transformés et mesure
quelle part du gold ancré ils recouvrent :

* ``chars`` — caractères gold recouverts / caractères gold ;
* ``mentions`` — mentions gold intégralement recouvertes / mentions gold.

Seules les annotations gold à offsets comptent (les attributs inférés au
niveau document n'ont aucun caractère à masquer). La mesure n'a de sens que
pour un système qui déclare la capacité ``decisions`` ; le portillon la rend
``UNAVAILABLE`` sinon.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from anonymisation.metrics.entities import SpanLike, bounds, field_value

_KEEP = "KEEP"


class MaskingError(ValueError):
    """Décision malformée : offsets absents, inversés ou hors du texte."""


@dataclass(frozen=True)
class MaskCoverage:
    covered_chars: int = 0
    gold_chars: int = 0
    covered_mentions: int = 0
    gold_mentions: int = 0

    def __add__(self, other: MaskCoverage) -> MaskCoverage:
        return MaskCoverage(
            self.covered_chars + other.covered_chars, self.gold_chars + other.gold_chars,
            self.covered_mentions + other.covered_mentions,
            self.gold_mentions + other.gold_mentions,
        )

    @property
    def char_rate(self) -> float | None:
        return self.covered_chars / self.gold_chars if self.gold_chars else None

    @property
    def mention_rate(self) -> float | None:
        return self.covered_mentions / self.gold_mentions if self.gold_mentions else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "covered_chars": self.covered_chars, "gold_chars": self.gold_chars,
            "covered_mentions": self.covered_mentions, "gold_mentions": self.gold_mentions,
            "char_rate": self.char_rate, "mention_rate": self.mention_rate,
        }


def masked_offsets(decisions: Iterable[Mapping[str, Any]], text_length: int) -> frozenset[int]:
    """Caractères transformés par les décisions appliquées (``KEEP`` exclu)."""
    masked: set[int] = set()
    for decision in decisions:
        action = str(getattr(decision.get("action"), "value", decision.get("action")))
        if action.upper() == _KEEP:
            continue
        start, end = decision.get("start"), decision.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= text_length:
            raise MaskingError(
                f"décision {action} aux offsets ({start}, {end}) invalides pour un texte de "
                f"{text_length} caractères — prédiction corrompue, relancer predict"
            )
        masked.update(range(start, end))
    return frozenset(masked)


def document_coverage(
    gold: Sequence[SpanLike], decisions: Sequence[Mapping[str, Any]], text: str
) -> MaskCoverage:
    masked = masked_offsets(decisions, len(text))
    coverage = MaskCoverage()
    seen: set[tuple[int, int]] = set()
    for span in gold:
        span_bounds = bounds(span)
        # Une même mention annotée sous plusieurs catégories ou par plusieurs
        # annotateurs ne compte qu'une fois : ce sont les caractères qui fuient.
        if span_bounds is None or span_bounds in seen:
            continue
        seen.add(span_bounds)
        chars = range(*span_bounds)
        covered = sum(1 for i in chars if i in masked)
        coverage = coverage + MaskCoverage(
            covered, len(chars), int(covered == len(chars)), 1
        )
    return coverage


def decisions_of(record: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    decisions = field_value(record, "decisions", None)
    return tuple(decisions or ())


__all__ = ["MaskCoverage", "MaskingError", "decisions_of", "document_coverage", "masked_offsets"]

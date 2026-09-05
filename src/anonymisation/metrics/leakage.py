"""Fuite de valeurs gold — mesure **indépendante du détecteur**.

Le seul contrôle de l'étape VALIDATE qui ne suppose rien de l'implémentation :
une recherche exacte des surfaces gold dans le texte anonymisé. Il fonctionne
donc pour **tout** système, boîte noire comprise, et c'est ce qui en fait le
socle des mesures de protection (CPR / IPR).

Cette duplication avec ``pipeline/validate_stage.py`` est délibérée et
souhaitable : le contrôle côté système est un garde-fou de production, celui-ci
est une mesure **indépendante de l'implémentation**. Les faire coïncider par un
import couplerait le scoring au pipeline et lui interdirait de rester hors
ligne.

Ce module n'importe que ``schema.taxonomy`` : aucune dépendance à ``detect``,
``pipeline`` ou ``systems``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from anonymisation.schema.taxonomy import IdentifierType


def _field(item: Any, name: str) -> Any:
    """Lit un champ, que l'item soit un modèle Pydantic ou un dict JSON."""
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def _identifier_type(item: Any) -> str | None:
    raw = _field(item, "identifier_type")
    if raw is None:
        return None
    return getattr(raw, "value", raw)


def _surface(item: Any) -> str | None:
    """Surface textuelle testable d'une annotation gold.

    Une annotation sans surface (inférence au niveau document, offsets nuls —
    invariant I-ANN-2) n'est pas testable par recherche exacte : elle est
    exclue du dénominateur plutôt que comptée comme protégée, ce qui
    surestimerait la protection.
    """
    span = _field(item, "span_text")
    if isinstance(span, str) and span.strip():
        return span
    return None


@dataclass(frozen=True)
class LeakCounts:
    """Surfaces gold encore présentes, sur les surfaces testables."""

    leaked: int
    testable: int
    leaked_direct: int
    testable_direct: int

    @property
    def rate(self) -> float | None:
        """Taux de fuite, ou ``None`` si rien n'est testable."""
        if self.testable == 0:
            return None
        return self.leaked / self.testable

    @property
    def direct_rate(self) -> float | None:
        if self.testable_direct == 0:
            return None
        return self.leaked_direct / self.testable_direct

    def to_dict(self) -> dict[str, Any]:
        return {
            "leaked": self.leaked,
            "testable": self.testable,
            "leaked_direct": self.leaked_direct,
            "testable_direct": self.testable_direct,
            "rate": self.rate,
            "direct_rate": self.direct_rate,
        }


def gold_leak_counts(anonymized_text: str, gold: Sequence[Any]) -> LeakCounts:
    """Compte les surfaces gold encore littéralement présentes dans le texte."""
    leaked = testable = leaked_direct = testable_direct = 0
    for annotation in gold:
        surface = _surface(annotation)
        if surface is None:
            continue
        is_direct = _identifier_type(annotation) == IdentifierType.DIRECT.value
        present = surface in anonymized_text
        testable += 1
        leaked += int(present)
        if is_direct:
            testable_direct += 1
            leaked_direct += int(present)
    return LeakCounts(
        leaked=leaked,
        testable=testable,
        leaked_direct=leaked_direct,
        testable_direct=testable_direct,
    )


def aggregate_leak_counts(items: Sequence[LeakCounts]) -> LeakCounts:
    """Somme des comptes, pour un corpus entier."""
    return LeakCounts(
        leaked=sum(item.leaked for item in items),
        testable=sum(item.testable for item in items),
        leaked_direct=sum(item.leaked_direct for item in items),
        testable_direct=sum(item.testable_direct for item in items),
    )

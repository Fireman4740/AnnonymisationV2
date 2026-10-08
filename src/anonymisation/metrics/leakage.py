"""Fuite de valeurs gold — mesure **indépendante du détecteur**.

Le seul contrôle de l'étape VALIDATE qui ne suppose rien de l'implémentation :
une recherche littérale (normalisée, bornée aux mots) des surfaces gold dans
le texte anonymisé. Il fonctionne
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

import re
import unicodedata
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
    return str(getattr(raw, "value", raw))


_WHITESPACE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """NFC + casse repliée + espaces fusionnés : forme de comparaison."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text).casefold())


def surface_present(surface: str, text: str) -> bool:
    """La surface apparaît-elle dans le texte comme **mot(s) entier(s)** ?

    La recherche en sous-chaîne brute (v1) se trompait dans les deux sens :

    * faux positifs : une surface courte (« 28 », « Li ») trouvée à
      l'intérieur d'un autre mot (« 1928 », « Lille ») comptait comme fuite ;
    * faux négatifs : une simple variation de casse ou d'espacement
      (« DUPONT », « Jean  Dupont ») comptait comme protection.

    On compare donc des formes normalisées et on exige qu'une surface
    commençant (resp. finissant) par un caractère de mot ne soit pas collée à
    un autre caractère de mot. Cela reste une recherche **littérale** : une
    paraphrase ou une inférence n'est jamais détectée.
    """
    needle = _normalise(surface).strip()
    haystack = _normalise(text)
    if not needle:
        return False
    check_left = needle[0].isalnum()
    check_right = needle[-1].isalnum()
    start = haystack.find(needle)
    while start != -1:
        end = start + len(needle)
        left_ok = not check_left or start == 0 or not haystack[start - 1].isalnum()
        right_ok = not check_right or end == len(haystack) or not haystack[end].isalnum()
        if left_ok and right_ok:
            return True
        start = haystack.find(needle, start + 1)
    return False


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
    """Compte les surfaces gold encore présentes (voir :func:`surface_present`)."""
    leaked = testable = leaked_direct = testable_direct = 0
    for annotation in gold:
        surface = _surface(annotation)
        if surface is None:
            continue
        is_direct = _identifier_type(annotation) == IdentifierType.DIRECT.value
        present = surface_present(surface, anonymized_text)
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

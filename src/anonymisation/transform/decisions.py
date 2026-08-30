"""Décisions d'anonymisation — le pivot explicable entre risque et texte.

Une :class:`AnonymizationDecision` est le seul objet que ``transform/apply.py``
sait consommer : elle porte l'action choisie, le texte de remplacement, et une
justification en français lisible par un humain (exigence d'explicabilité,
SPEC-06 §6 « contributing_qi », SPEC-07 §4).

Ce module ne dépend PAS de ``detect/base.py`` (qui peut ne pas encore exister
au moment où ce lot est développé) : il définit son propre protocole minimal,
satisfait aussi bien par un ``Annotation`` de ``schema/models.py`` que par un
futur ``Candidate`` de détection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from anonymisation.schema.taxonomy import ALLOWED_ACTIONS


class Action(str, Enum):
    """Les cinq actions d'anonymisation possibles (SPEC-01 §8)."""

    KEEP = "KEEP"
    GENERALIZE = "GENERALIZE"
    PSEUDONYMIZE = "PSEUDONYMIZE"
    MASK = "MASK"
    SUPPRESS = "SUPPRESS"


@runtime_checkable
class AnnotationLike(Protocol):
    """Abstraction commune entre ``schema.models.Annotation`` et un futur
    ``detect.base.Candidate`` : seuls les attributs utilisés par la couche de
    transformation sont exigés.
    """

    start: int | None
    end: int | None
    identifier_type: Any
    qi_categories: Any
    granularity: Any
    value_normalized: dict[str, Any] | None


class ActionNotAllowedError(ValueError):
    """L'action choisie viole le tableau ``ALLOWED_ACTIONS`` de SPEC-01 §8."""


class InvalidDecisionError(ValueError):
    """Une décision est structurellement incohérente (offsets, texte, ...)."""


def _granularity_key(granularity: Any) -> str | None:
    """Normalise une granularité (enum ou str) vers la clé utilisée par
    ``ALLOWED_ACTIONS``. ``None`` désigne les types qui n'ont pas de notion de
    granularité (DIRECT, SENSITIVE_ONLY, IGNORED).
    """
    if granularity is None:
        return None
    value = getattr(granularity, "value", granularity)
    return str(value)


def check_action_allowed(identifier_type: Any, granularity: Any, action: Action | str) -> None:
    """Vérifie qu'``action`` est autorisée pour ce ``identifier_type``/``granularity``.

    Lève :class:`ActionNotAllowedError` sinon. C'est le seul point de contrôle
    d'autorisation de la couche de transformation — aucune valeur par défaut
    silencieuse (règle d'or du projet).

    Point important de SPEC-01 §8 : un QI de granularité ``COARSE`` ne peut
    plus être généralisé, seulement supprimé (ou gardé s'il redevient
    acceptable, ce que la politique ne décide jamais pour un QUASI COARSE).
    """
    id_type_key = getattr(identifier_type, "value", identifier_type)
    id_type_key = str(id_type_key)
    action_key = getattr(action, "value", action)
    action_key = str(action_key)

    key = (id_type_key, _granularity_key(granularity))
    if key not in ALLOWED_ACTIONS:
        raise ActionNotAllowedError(
            f"Combinaison (identifier_type={id_type_key!r}, "
            f"granularity={_granularity_key(granularity)!r}) absente de "
            f"ALLOWED_ACTIONS (SPEC-01 §8). Vérifier la taxonomie."
        )

    allowed = ALLOWED_ACTIONS[key]
    if action_key not in allowed:
        raise ActionNotAllowedError(
            f"Action {action_key!r} interdite pour "
            f"(identifier_type={id_type_key!r}, granularity={_granularity_key(granularity)!r}). "
            f"Actions autorisées : {allowed} (SPEC-01 §8)."
        )


@dataclass(frozen=True)
class AnonymizationDecision:
    """Une décision d'anonymisation sur un span, prête à être appliquée.

    Les offsets ``start``/``end`` réfèrent TOUJOURS au texte original du
    document, jamais à un texte partiellement transformé (voir
    ``transform/apply.py``).

    ``reason`` doit être une phrase en français, compréhensible par un humain
    sans connaissance du code : c'est l'exigence d'explicabilité du projet.
    """

    start: int
    end: int
    original: str
    action: Action
    replacement: str
    qi_category: str
    reason: str
    risk_before: float | None = None
    risk_after: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise InvalidDecisionError(
                f"end ({self.end}) doit être strictement supérieur à start ({self.start})"
            )
        if not self.reason.strip():
            raise InvalidDecisionError(
                "reason ne peut pas être vide : toute décision doit être explicable"
            )

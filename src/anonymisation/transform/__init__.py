"""Couche de transformation : texte + décisions -> texte anonymisé.

Implémentation normative des sections « actions d'anonymisation » de SPEC-01
§8 et des hiérarchies de généralisation de SPEC-06 §5. Ce paquet ne calcule
aucun risque (voir ``anonymisation.policy`` pour le choix des actions) : il se
contente de savoir exécuter une action déjà décidée, de manière traçable et
explicable.
"""

from __future__ import annotations

from anonymisation.transform.apply import (
    OverlappingDecisionsError,
    TransformResult,
    apply_decisions,
)
from anonymisation.transform.decisions import (
    Action,
    ActionNotAllowedError,
    AnnotationLike,
    AnonymizationDecision,
    InvalidDecisionError,
    check_action_allowed,
)
from anonymisation.transform.generalize import (
    MalformedValueNormalizedError,
    UnknownGeneralizationCategoryError,
    generalize,
    levels_available,
)
from anonymisation.transform.mask import UnknownMaskModeError, mask
from anonymisation.transform.pseudonymize import PseudoMapper, normalise_surface

__all__ = [
    "Action",
    "ActionNotAllowedError",
    "AnonymizationDecision",
    "AnnotationLike",
    "InvalidDecisionError",
    "check_action_allowed",
    "TransformResult",
    "OverlappingDecisionsError",
    "apply_decisions",
    "generalize",
    "levels_available",
    "UnknownGeneralizationCategoryError",
    "MalformedValueNormalizedError",
    "mask",
    "UnknownMaskModeError",
    "PseudoMapper",
    "normalise_surface",
]

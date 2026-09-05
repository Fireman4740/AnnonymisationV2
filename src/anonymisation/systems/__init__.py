"""Systèmes d'anonymisation évaluables (SPEC-10).

La découverte se fait par **import explicite** ci-dessous, jamais par scan de
répertoire : le comportement ne doit pas dépendre de l'ordre d'import.

⚠️ Ce paquet importe ``detect/`` (via le système déterministe). Il ne doit
donc **jamais** être importé par ``metrics/`` ni par ``cli/score.py`` — le
scoring doit rester hors ligne et sans modèle. Le vocabulaire partagé avec les
métriques vit dans ``anonymisation.capabilities``, qui n'importe rien.
"""

from anonymisation.systems.base import (
    ModelRef,
    SystemBase,
    SystemConfig,
    SystemContractError,
    SystemDescriptor,
    SystemIdentity,
    TextRewriteSystem,
    params_digest,
)
from anonymisation.systems.registry import (
    ALIASES,
    SYSTEM_REGISTRY,
    UnknownSystemError,
    list_systems,
    register_system,
    resolve_system,
)

# --- Systèmes enregistrés (import explicite = enregistrement) --------------- #
from anonymisation.systems import bounds as _bounds  # noqa: F401,E402
from anonymisation.systems import deterministic as _deterministic  # noqa: F401,E402

__all__ = [
    "ALIASES",
    "SYSTEM_REGISTRY",
    "ModelRef",
    "SystemBase",
    "SystemConfig",
    "SystemContractError",
    "SystemDescriptor",
    "SystemIdentity",
    "TextRewriteSystem",
    "UnknownSystemError",
    "list_systems",
    "params_digest",
    "register_system",
    "resolve_system",
]

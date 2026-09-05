"""Registre des systèmes d'anonymisation évaluables.

Calqué sur ``anonymisation.datasets.registry`` — le seul mécanisme d'extension
déjà éprouvé du dépôt. Même logique, mêmes garanties : enregistrement par
décorateur, découverte par **import explicite** (jamais par scan de
répertoire, qui rendrait le comportement dépendant de l'ordre d'import), refus
des collisions de clés et d'alias.

Ajouter un système consiste à écrire une classe, la décorer avec
:func:`register_system`, et l'importer dans ``systems/__init__.py``. Rien
d'autre : ni le harnais d'évaluation, ni les métriques, ni le CLI n'ont à
connaître son existence.
"""

from __future__ import annotations

from typing import Final

from anonymisation.capabilities import assert_known
from anonymisation.systems.base import SystemBase

SYSTEM_REGISTRY: Final[dict[str, type[SystemBase]]] = {}
ALIASES: Final[dict[str, str]] = {}


class UnknownSystemError(KeyError):
    """Clé de système non enregistrée."""


def register_system(cls: type[SystemBase]) -> type[SystemBase]:
    """Enregistre un système. Refuse toute collision, bruyamment."""
    key = getattr(cls, "system_id", None)
    if not key:
        raise ValueError(f"{cls.__name__} : attribut de classe `system_id` manquant.")
    if key in SYSTEM_REGISTRY:
        held = SYSTEM_REGISTRY[key].__module__
        raise ValueError(
            f"Clé de système déjà enregistrée : {key!r} (déjà tenue par {held})."
        )
    assert_known(cls.capabilities, owner=key)
    for alias in getattr(cls, "aliases", ()):
        if alias in ALIASES or alias in SYSTEM_REGISTRY:
            raise ValueError(f"Alias déjà utilisé : {alias!r}.")
        ALIASES[alias] = key
    SYSTEM_REGISTRY[key] = cls
    return cls


def resolve_system(key: str) -> type[SystemBase]:
    """Résout une clé ou un alias. Le message d'erreur liste les clés connues."""
    if key in SYSTEM_REGISTRY:
        return SYSTEM_REGISTRY[key]
    if key in ALIASES:
        return SYSTEM_REGISTRY[ALIASES[key]]
    known = ", ".join(sorted(SYSTEM_REGISTRY)) or "(aucun)"
    raise UnknownSystemError(f"Système inconnu : {key!r}. Clés connues : {known}.")


def list_systems() -> tuple[str, ...]:
    return tuple(sorted(SYSTEM_REGISTRY))

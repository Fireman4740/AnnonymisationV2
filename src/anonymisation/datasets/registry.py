"""Registre de datasets.

Implémentation de SPEC-03 §5 et §8.

L'enregistrement se fait par décorateur et la découverte par import explicite
dans ``datasets/__init__.py`` — jamais par scan dynamique du système de
fichiers, qui rendrait le comportement dépendant de l'ordre d'import.
"""

from __future__ import annotations

from typing import Final

from anonymisation.datasets.base import DatasetAdapter

REGISTRY: Final[dict[str, type[DatasetAdapter]]] = {}
ALIASES: Final[dict[str, str]] = {}


class UnknownDatasetError(KeyError):
    """Clé de dataset non enregistrée — garantie G1."""


class ManifestError(ValueError):
    """Manifeste invalide ou incomplet — garantie G2."""


class UnmappedLabelError(ValueError):
    """Étiquette source absente du label_map — garantie G4, erreur E-MAP-001.

    Bloquant par conception : dégrader silencieusement en ``OTHER_QI``
    fausserait les métriques sans que personne ne s'en aperçoive.
    """


def register(cls: type[DatasetAdapter]) -> type[DatasetAdapter]:
    key = cls.key
    if key in REGISTRY:
        raise ValueError(f"Clé de dataset déjà enregistrée : {key!r}")
    REGISTRY[key] = cls
    for alias in getattr(cls, "aliases", ()):
        if alias in ALIASES:
            raise ValueError(f"Alias déjà utilisé : {alias!r}")
        ALIASES[alias] = key
    return cls


def resolve(key: str) -> type[DatasetAdapter]:
    """Résout une clé ou un alias vers une classe d'adaptateur."""
    if key in REGISTRY:
        return REGISTRY[key]
    if key in ALIASES:
        return REGISTRY[ALIASES[key]]
    known = ", ".join(sorted(REGISTRY))
    raise UnknownDatasetError(f"Dataset inconnu : {key!r}. Clés connues : {known}")


def list_keys() -> tuple[str, ...]:
    return tuple(sorted(REGISTRY))

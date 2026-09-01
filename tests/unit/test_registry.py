"""Tests du registre d'adaptateurs (EPIC-A, A-5).

Critères d'acceptation du ticket :
- ``from anonymisation.datasets import REGISTRY`` expose les adaptateurs
  livrés (aucun dans l'épic A — le mécanisme doit exister) ;
- une clé enregistrée deux fois lève une erreur ;
- un alias déjà utilisé lève une erreur.

Le registre est un dict global : chaque test part d'un état vide et le
restaure après (fixture ``clean_registry``).
"""

from __future__ import annotations

import pytest

import anonymisation.datasets as datasets_pkg
from anonymisation.datasets import (
    ALIASES,
    REGISTRY,
    AcquisitionReport,
    DatasetAdapter,
    ManifestError,
    UnknownDatasetError,
    UnmappedLabelError,
    list_keys,
    register,
    resolve,
)


@pytest.fixture
def clean_registry():
    """Vide le registre pour la durée du test, restaure l'état d'origine."""
    saved = (dict(REGISTRY), dict(ALIASES))
    REGISTRY.clear()
    ALIASES.clear()
    yield
    REGISTRY.clear()
    ALIASES.clear()
    REGISTRY.update(saved[0])
    ALIASES.update(saved[1])


# --- Classes d'essai (jamais enregistrées à l'import) ------------------------ #


class _A(DatasetAdapter):
    key = "aaa"
    aliases = ("a1", "a2")


class _B(DatasetAdapter):
    key = "bbb"


class _B2(DatasetAdapter):
    key = "bbb"  # même clé que ``_B`` — pour le doublon


class _C(DatasetAdapter):
    key = "ccc"


class _D(DatasetAdapter):
    key = "ddd"
    aliases = ("a1",)  # même alias que ``_A``


# --- Enregistrement et résolution ---------------------------------------------- #


def test_register_and_resolve_key(clean_registry) -> None:
    assert register(_A) is _A  # sémantique décorateur : renvoie la classe
    assert resolve("aaa") is _A
    assert list_keys() == ("aaa",)


def test_resolve_alias(clean_registry) -> None:
    register(_A)
    assert resolve("a1") is _A
    assert resolve("a2") is _A
    assert ALIASES == {"a1": "aaa", "a2": "aaa"}


def test_list_keys_sorted(clean_registry) -> None:
    register(_C)
    register(_A)
    register(_B)
    assert list_keys() == ("aaa", "bbb", "ccc")


def test_unknown_key_raises_explicit_error(clean_registry) -> None:
    register(_B)
    with pytest.raises(UnknownDatasetError, match="Dataset inconnu : 'nope'"):
        resolve("nope")
    # Le message liste les clés connues (actionnabilité, garantie G1).
    with pytest.raises(UnknownDatasetError) as excinfo:
        resolve("nope")
    assert "Clés connues : bbb" in str(excinfo.value)


def test_unknown_dataset_error_is_keyerror() -> None:
    """``UnknownDatasetError`` est une ``KeyError`` — contractuelle (SPEC-03 G1)."""
    assert issubclass(UnknownDatasetError, KeyError)


# --- Erreurs de doublon (critères d'acceptation) ------------------------------ #


def test_duplicate_key_raises(clean_registry) -> None:
    register(_B)
    with pytest.raises(ValueError, match="Clé de dataset déjà enregistrée : 'bbb'"):
        register(_B2)


def test_duplicate_alias_raises(clean_registry) -> None:
    register(_A)
    with pytest.raises(ValueError, match="Alias déjà utilisé : 'a1'"):
        register(_D)


# --- Exposition publique (critère d'acceptation) ------------------------------ #


def test_package_exports_public_api() -> None:
    """``from anonymisation.datasets import REGISTRY`` + API complète."""
    assert datasets_pkg.REGISTRY is REGISTRY
    assert datasets_pkg.ALIASES is ALIASES
    assert datasets_pkg.register is register
    assert datasets_pkg.resolve is resolve
    assert datasets_pkg.list_keys is list_keys
    assert datasets_pkg.DatasetAdapter is DatasetAdapter
    assert datasets_pkg.AcquisitionReport is AcquisitionReport
    assert datasets_pkg.UnknownDatasetError is UnknownDatasetError
    assert datasets_pkg.ManifestError is ManifestError
    assert datasets_pkg.UnmappedLabelError is UnmappedLabelError
    # L'import du paquet importe les modules d'ingestion (sans effet de bord).
    assert hasattr(datasets_pkg, "manifest")
    assert hasattr(datasets_pkg, "ingest")
    assert hasattr(datasets_pkg, "_bio")
    assert hasattr(datasets_pkg, "_local")

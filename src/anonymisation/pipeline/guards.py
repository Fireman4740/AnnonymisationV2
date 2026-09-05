"""Gardes de sécurité du pipeline (SPEC-10 §10, SPEC-08 §8).

Le texte original d'un corpus réel ne doit jamais être envoyé à un fournisseur
externe. La garde est volontairement indépendante de l'orchestrateur afin que
les commandes ``predict`` et les futurs attaquants partagent le même contrat.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from anonymisation.datasets.manifest import DatasetManifest
from anonymisation.pipeline.profiles import RuntimeProfile


class LocalOnlyViolationError(ValueError):
    """Accès distant demandé pour un corpus qui peut contenir des personnes réelles."""


def _read_field(value: object, name: str, default: object = None) -> object:
    """Lit un champ d'un modèle Pydantic ou d'un mapping sans défaut permissif."""
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _allow_remote(profile: RuntimeProfile | Mapping[str, Any]) -> bool:
    llm = _read_field(profile, "llm")
    return bool(_read_field(llm, "allow_remote", False))


def _corpus_info(manifest: DatasetManifest | Mapping[str, Any]) -> tuple[str, bool]:
    key = str(_read_field(manifest, "key", "<corpus inconnu>"))
    structure = _read_field(manifest, "structure", {})
    # L'absence de ``synthetic`` est traitée comme False : la garde échoue
    # fermée, conformément au défaut de StructureSpec.
    synthetic = bool(_read_field(structure, "synthetic", False))
    return key, synthetic


def assert_local_only(
    profile: RuntimeProfile | Mapping[str, Any],
    manifest: DatasetManifest | Mapping[str, Any],
) -> None:
    """Refuse l'envoi distant du texte d'un corpus non synthétique.

    ``llm.allow_remote`` peut être activé uniquement pour un manifeste portant
    explicitement ``structure.synthetic: true``. Les corpus absents ou
    incomplets sont refusés par défaut, et le message cite le corpus ainsi que
    la cause afin de rendre l'erreur actionnable.
    """
    if not _allow_remote(profile):
        return

    corpus, synthetic = _corpus_info(manifest)
    if synthetic:
        return

    raise LocalOnlyViolationError(
        f"Accès distant interdit pour le corpus {corpus!r} : "
        "llm.allow_remote=true alors que structure.synthetic=false ou absent. "
        "Le profil doit utiliser un backend local pour protéger le texte original "
        "(SPEC-10 §10 / SPEC-08 E2)."
    )


__all__ = ["LocalOnlyViolationError", "assert_local_only"]

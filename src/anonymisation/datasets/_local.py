"""Résolution des sources locales et empreinte de corpus (EPIC A, ticket A-1).

Une source ``kind: local`` pointe vers un corpus déjà sur disque (inventaire
local, ``documentation/datasets/inventaire-local.md``). La racine est
surchargeable par une variable d'environnement (``path_env``) : c'est ce qui
rend le dépôt portable — sans elle, un chemin absolu ne fonctionne que sur la
machine qui l'a écrit, et aucun résultat n'est reproductible par un tiers
(piège connu du ticket A-1).

Règle d'or : une source absente n'est jamais tolérée silencieusement.
:class:`LocalSourceError` est actionnable : elle dit **quoi** définir
(variable d'environnement) et **où** (chemin résolu).
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from anonymisation.schema.io import sha256_file

__all__ = [
    "LocalSourceError",
    "SourceResolution",
    "check_files",
    "fingerprint",
    "resolve_local_source",
    "resolve_source_dir",
    "resolve_v1_cache",
]

#: Variable canonique de surcharge de la racine des corpus v1.
V1_DATASETS_ENV = "ANONV2_V1_DATASETS"


class LocalSourceError(FileNotFoundError):
    """Source locale absente — message actionnable.

    Indique toujours la variable à définir (le cas échéant) et le chemin
    résolu, pour qu'un tiers puisse répliquer l'acquisition sans deviner.
    """


@dataclass(frozen=True)
class SourceResolution:
    """Résultat de la résolution d'une source locale : figé dans le lock."""

    kind: str
    directory: Path
    files: tuple[Path, ...]
    fingerprint: str


class _Source(Protocol):
    """Part de ``SourceSpec`` (manifest.py) consommée par ce module.

    Protocole structurel : évite une importation circulaire manifest <->
    _local tout en gardant une signature typée.
    """

    kind: str
    path: str | None
    path_env: str | None
    files: list[str]


def resolve_source_dir(source: _Source) -> Path:
    """Résout le répertoire d'une source ``kind: local``.

    Règles de résolution (déterministes, aucun repli silencieux) :

    - ``path_env`` déclarée **et définie** : le répertoire est
      ``$<path_env> / path`` si ``path`` est déclaré, sinon ``$<path_env>``
      lui-même. Un ``path`` *absolu* garde la main (sémantique pathlib :
      le joint d'un chemin absolu retourne ce chemin) — c'est le cas de la
      machine de développement, qui a écrit un chemin absolu dans le
      manifeste.
    - ``path_env`` déclarée **mais non définie** : si ``path`` est absolu,
      on l'utilise tel quel (défaut local explicite) ; sinon
      :class:`LocalSourceError` qui nomme la variable à définir.
    - ``path_env`` absente : ``path`` est utilisé tel quel (absolu ou
      relatif au répertoire courant) ; ``path`` absent → erreur.
    """
    if source.kind != "local":
        raise LocalSourceError(
            f"resolve_source_dir : kind {source.kind!r} n'est pas une source locale"
        )

    if source.path_env:
        var = source.path_env
        root = os.environ.get(var)
        if root is None:
            if source.path is not None and Path(source.path).is_absolute():
                return Path(source.path)
            raise LocalSourceError(
                f"source locale : la variable d'environnement {var} n'est pas définie. "
                f"Définissez-la à la racine de vos corpus v1 (ex. "
                f"export {var}=/chemin/vers/Anonymisation/eval/datasets), "
                "ou déclarez un `path` absolu valide sur cette machine."
            )
        if source.path is not None:
            return Path(root) / source.path
        return Path(root)

    if source.path is not None:
        return Path(source.path)

    raise LocalSourceError(
        "source locale : ni `path` ni `path_env` déclarés — "
        "déclarez l'un des deux dans le manifeste"
    )


def check_files(directory: Path, files: Sequence[str] | None = None) -> list[Path]:
    """Vérifie la présence de la source : répertoire, puis fichiers déclarés.

    ``files`` est une liste de noms de fichiers *relatifs* à ``directory`` ;
    ``None`` ou liste vide signifie « le répertoire lui-même est la source ».

    Retourne la liste des chemins résolus (le répertoire s'il n'y a pas de
    fichier déclaré). Lève :class:`LocalSourceError` en nommant chaque
    élément manquant.
    """
    directory = Path(directory)
    if not directory.exists():
        raise LocalSourceError(f"répertoire source absent : {directory}")
    if not directory.is_dir():
        raise LocalSourceError(f"la source n'est pas un répertoire : {directory}")

    if not files:
        return [directory]

    resolved: list[Path] = []
    missing: list[Path] = []
    for name in files:
        path = directory / name
        resolved.append(path)
        if not path.is_file():
            missing.append(path)
    if missing:
        raise LocalSourceError(
            "fichier(s) manquant(s) dans "
            + str(directory)
            + " : "
            + ", ".join(str(p) for p in missing)
        )
    return resolved


def fingerprint(paths: Sequence[Path]) -> str:
    """Empreinte SHA-256 combinée d'un jeu de fichiers.

    Déterministe quel que soit l'ordre des chemins fournis : les chemins sont
    d'abord triés, et pour chaque fichier on hache son *nom* puis l'empreinte
    de son *contenu* (le nom distingue deux fichiers identiques de noms
    différents). Le contenu est haché par
    :func:`~anonymisation.schema.io.sha256_file`, qui lit par blocs — donc
    utilisable sur les gros corpus.

    L'empreinte figure dans ``.manifest.lock.json`` : c'est elle qui
    invalide le cache des données normalisées (SPEC-04 §7) quand la source
    change.
    """
    h = hashlib.sha256()
    for path in sorted(Path(p) for p in paths):
        h.update(path.name.encode("utf-8"))
        h.update(b"\0")
        h.update(sha256_file(path).encode("ascii"))
    return h.hexdigest()


def resolve_local_source(source: _Source) -> SourceResolution | None:
    """Résout et vérifie une source ``kind: local`` — ``None`` sinon.

    Point d'entrée unique de l'étape ACQUIRE pour les sources locales :
    répertoire résolu, fichiers déclarés vérifiés, empreinte calculée. Le
    chargement du manifeste (SPEC-03 §5, contrôle 4) et le pipeline
    d'ingestion (SPEC-04, étape 1) passent tous deux par ici — la règle de
    résolution n'existe qu'à un seul endroit.

    Les sources non locales (``huggingface``, ``manual``, ``generated``)
    retournent ``None`` : leur acquisition est l'affaire de l'adaptateur.
    """
    if source.kind != "local":
        return None
    directory = resolve_source_dir(source)
    files = check_files(directory, source.files)
    return SourceResolution(
        kind="local",
        directory=directory,
        files=tuple(files),
        fingerprint=fingerprint(files),
    )


def resolve_v1_cache(
    v1_cache: str | None, env: Mapping[str, str] | None = None
) -> Path | None:
    """Résout un chemin ``v1_cache`` d'un manifeste (corpus v1 réutilisé, SPEC-03 §7).

    Le chemin est relatif à la racine des corpus v1, surchargeable par la
    variable ``ANONV2_V1_DATASETS`` : sans elle, il est interprété depuis le
    répertoire courant (la disposition du dépôt suppose v1 comme voisin du
    dépôt, d'où les chemins ``../Anonymisation/...`` des manifestes).
    """
    if not v1_cache:
        return None
    lookup = os.environ if env is None else env
    root = lookup.get(V1_DATASETS_ENV)
    if root:
        return Path(root) / v1_cache
    return Path(v1_cache)

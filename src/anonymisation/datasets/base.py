"""Contrat d'adaptateur de dataset.

Implémentation de SPEC-03 §6
(``documentation/specifications/SPEC-03-registre-et-adaptateurs.md``).

Un adaptateur ne connaît que son format source et le schéma SPEC-02. Il ne
connaît ni les métriques, ni le moteur de risque, ni la politique.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from anonymisation.schema.models import (
    Annotation,
    Combination,
    Document,
    Organization,
    Profile,
    TaskLabel,
)


@dataclass(frozen=True)
class AcquisitionReport:
    """Résultat d'un ``download()``."""

    dataset: str
    path: Path
    sha256: str
    bytes_downloaded: int
    from_cache: bool
    revision: str | None = None


class DatasetAdapter(ABC):
    """Contrat que tout dataset doit implémenter.

    Règles d'implémentation (SPEC-03 §6) :

    1. Les ``iter_*`` DOIVENT être des générateurs paresseux — OpenPII et
       MultiCoNER ne tiennent pas confortablement en mémoire ; le pipeline
       peut activer sa voie d'ingestion en flux via ``streaming = True``.
    2. ``download()`` DOIT être idempotent : relancé, il ne retélécharge pas si
       le checksum correspond.

    3. Un adaptateur NE DOIT PAS écrire dans ``data/processed/`` — c'est le rôle
       du pipeline d'ingestion (SPEC-04). Il produit des objets, pas des fichiers.
    4. Un adaptateur NE DOIT PAS filtrer ni corriger silencieusement. Une donnée
       source aberrante remonte telle quelle et est rejetée par la validation,
       avec son ``doc_id``.
    """

    key: ClassVar[str]
    streaming: ClassVar[bool] = False

    def __init__(self, manifest: Any, raw_dir: Path) -> None:
        self.manifest = manifest
        self.raw_dir = raw_dir

    # --- Acquisition ------------------------------------------------------ #
    @abstractmethod
    def download(self, *, force: bool = False) -> AcquisitionReport:
        """Télécharge la source dans ``raw_dir``. Idempotent."""

    # --- Normalisation ---------------------------------------------------- #
    @abstractmethod
    def iter_documents(self, split: str) -> Iterator[Document]: ...

    @abstractmethod
    def iter_annotations(self, split: str) -> Iterator[Annotation]: ...

    def iter_profiles(self, split: str) -> Iterator[Profile]:
        return iter(())

    def iter_organizations(self, split: str) -> Iterator[Organization]:
        return iter(())

    def iter_combinations(self, split: str) -> Iterator[Combination]:
        return iter(())

    def iter_tasks(self, split: str) -> Iterator[TaskLabel]:
        return iter(())

    # --- Découpage -------------------------------------------------------- #
    def splits(self) -> tuple[str, ...]:
        return tuple(self.manifest.structure.splits)

    def make_splits(self, seed: int = 42) -> dict[str, tuple[str, ...]]:
        """Split déterministe quand la source n'en fournit pas.

        DOIT respecter ``manifest.structure.split_by``. Un split par document
        sur un corpus à profils latents produit une fuite massive : le registre
        doit la refuser (SPEC-03 §4).
        """
        raise NotImplementedError

    # --- Introspection ---------------------------------------------------- #
    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "raw_dir": str(self.raw_dir),
            "splits": list(self.splits()),
        }

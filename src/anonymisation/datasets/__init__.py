"""Registre et adaptateurs de datasets (SPEC-03, SPEC-04).

Les adaptateurs sont importés explicitement ici : c'est cet import qui les
enregistre. Ordre d'implémentation recommandé (SPEC-04 §10) : openpii ->
synthpai -> tab -> ratbench -> corpus internes -> jobstack/multiconer/meddocan.

ÉPIC-A ne livre aucun adaptateur (lot L2 = épic B) : seuls les modules de
l'infrastructure d'ingestion sont importés — sans effet de bord.
"""

from anonymisation.datasets import _bio, _local, ingest, manifest  # noqa: F401
from anonymisation.datasets.base import AcquisitionReport, DatasetAdapter
from anonymisation.datasets.registry import (
    ALIASES,
    REGISTRY,
    ManifestError,
    UnknownDatasetError,
    UnmappedLabelError,
    list_keys,
    register,
    resolve,
)

# --- Adaptateurs — épic B (décommenter au fil de la livraison) ---------------
# from anonymisation.datasets import openpii    # noqa: F401
# from anonymisation.datasets import synthpai   # noqa: F401
# from anonymisation.datasets import tab        # noqa: F401
# from anonymisation.datasets import ratbench   # noqa: F401

__all__ = [
    "ALIASES",
    "REGISTRY",
    "AcquisitionReport",
    "DatasetAdapter",
    "ManifestError",
    "UnknownDatasetError",
    "UnmappedLabelError",
    "list_keys",
    "register",
    "resolve",
]

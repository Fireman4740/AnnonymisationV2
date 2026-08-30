"""Registre et adaptateurs de datasets (SPEC-03, SPEC-04).

Les adaptateurs sont importés explicitement ici : c'est cet import qui les
enregistre. Ordre d'implémentation recommandé (SPEC-04 §10) : openpii ->
synthpai -> tab -> ratbench -> corpus internes -> jobstack/multiconer/meddocan.
"""

from anonymisation.datasets.base import AcquisitionReport, DatasetAdapter
from anonymisation.datasets.registry import (
    REGISTRY,
    ManifestError,
    UnknownDatasetError,
    UnmappedLabelError,
    list_keys,
    register,
    resolve,
)

# --- Adaptateurs (à décommenter au fur et à mesure du lot L2) ---------------
# from anonymisation.datasets import openpii    # noqa: F401
# from anonymisation.datasets import synthpai   # noqa: F401
# from anonymisation.datasets import tab        # noqa: F401
# from anonymisation.datasets import ratbench   # noqa: F401

__all__ = [
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

"""Registre et adaptateurs de datasets (SPEC-03, SPEC-04).

Les adaptateurs sont importés explicitement ici : c'est cet import qui les
enregistre. Ordre d'implémentation recommandé (SPEC-04 §10) : openpii ->
synthpai -> tab -> ratbench -> corpus internes -> jobstack/multiconer/meddocan.

L'infrastructure d'ingestion (épic A) est importée sans effet de bord ; les
adaptateurs de l'épic B sont importés ici un à un, au fil de la livraison.
"""

from anonymisation.datasets import (  # noqa: F401
    _bio,
    _local,
    bitextsupport,
    conll2003,
    dbbio,
    ingest,
    manifest,
    openpii,
    panorama,
    personalreddit,
    quasifr,
    ratbench,
    spia,
    supporttickets,
    tab,
)
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

# --- Adaptateurs restants — épic B/G ---------------------------------------
# Les imports explicites garantissent un registre indépendant de l'ordre du
# système de fichiers (SPIA/PANORAMA sont livrés par l'épic G).

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

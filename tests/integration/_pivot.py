"""Découverte des splits réellement publiés par un corpus ingéré.

Pourquoi ce module existe : une liste de splits **codée en dur** fait skipper
les tests en silence dès qu'un corpus n'utilise pas les noms usuels. C'est
exactement ce qui s'est produit avec ``quasifr``, dont les splits sont
``anonymization`` / ``hard_quasi_id`` / ``max_anonymization`` alors que les
tests cherchaient ``train`` / ``dev`` / ``test`` / ``validation`` : la condition
était structurellement toujours fausse, et les contrôles de sanité S1-S3 comme
la non-régression déterministe sur corpus réel **ne se sont jamais exécutés**.

Un test qui passe en étant skippé ne vaut rien. Les fonctions de ce module
lisent donc les splits **sur le disque** et, lorsqu'elles skippent, disent
précisément ce qu'elles ont trouvé.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_ROOT = REPO_ROOT / "data" / "processed"


def pivot_root(dataset: str) -> Path:
    """Répertoire pivot d'un corpus ingéré."""
    return PROCESSED_ROOT / dataset


def pivot_splits(dataset: str) -> tuple[str, ...]:
    """Splits réellement publiés, triés — vide si le corpus n'est pas ingéré.

    Un split ne compte que s'il porte un ``documents.jsonl`` : un répertoire nu
    laissé par une ingestion interrompue ne doit pas faire croire à un corpus
    disponible.
    """
    root = pivot_root(dataset)
    if not root.is_dir():
        return ()
    return tuple(
        sorted(
            entry.name
            for entry in root.iterdir()
            if entry.is_dir() and (entry / "documents.jsonl").is_file()
        )
    )


def require_split(dataset: str, *, prefer: Sequence[str] = ()) -> str:
    """Renvoie un split exploitable, ou skippe en nommant ce qui a été trouvé.

    ``prefer`` liste les splits souhaités par ordre de préférence ; s'il n'y a
    aucune correspondance, on retient le premier split disponible plutôt que de
    skipper — la vocation de ces tests est de tourner sur du réel.
    """
    splits = pivot_splits(dataset)
    if not splits:
        root = pivot_root(dataset)
        raison = "répertoire absent" if not root.is_dir() else "aucun documents.jsonl"
        pytest.skip(
            f"{dataset} non ingéré ({raison} sous {root}) : "
            f"lancez « anonv2 datasets ingest {dataset} » "
            f"avec ANONV2_V1_DATASETS défini."
        )
    for candidate in prefer:
        if candidate in splits:
            return candidate
    return splits[0]


def require_source(dataset: str) -> None:
    """Skippe si la **source brute** du corpus n'est pas résoluble.

    Distinct de :func:`require_split` : un corpus peut être déjà ingéré (pivot
    présent) sans que sa source d'origine soit disponible sur la machine. Une
    ré-ingestion — que teste la non-régression déterministe — exige la source.
    Sur un clone frais, cela doit **skipper**, jamais échouer.
    """
    from anonymisation.datasets._local import LocalSourceError
    from anonymisation.datasets.manifest import load_manifest

    config = REPO_ROOT / "configs" / "datasets" / f"{dataset}.yaml"
    if not config.is_file():
        pytest.skip(f"{dataset} : manifeste absent ({config})")
    try:
        # `load_manifest` résout la source locale et lève si elle est absente.
        load_manifest(config)
    except LocalSourceError as exc:
        pytest.skip(f"{dataset} : source brute indisponible — {exc}")

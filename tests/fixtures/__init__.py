"""Chargeur du micro-dataset de tests (voir ``tests/fixtures/README.md``).

Permet de tester la validation, le calcul de k, les métriques, la politique et
l'attaquant simulé sans aucun téléchargement (SPEC-09 §4.3).
"""

from __future__ import annotations

from pathlib import Path

from anonymisation.schema.io import read_jsonl
from anonymisation.schema.models import (
    Annotation,
    Combination,
    Document,
    Profile,
    TaskLabel,
)

MICRO_DIR = Path(__file__).parent / "micro"


def load_micro() -> dict[str, list]:
    """Charge le micro-dataset complet depuis ``tests/fixtures/micro/``.

    Retourne un dict avec les clés ``documents``, ``annotations``,
    ``profiles``, ``combinations``, ``tasks`` — chacune une liste de modèles
    pydantic déjà validés à la construction (SPEC-02).
    """
    return {
        "documents": list(read_jsonl(MICRO_DIR / "documents.jsonl", Document)),
        "annotations": list(read_jsonl(MICRO_DIR / "annotations.jsonl", Annotation)),
        "profiles": list(read_jsonl(MICRO_DIR / "profiles.jsonl", Profile)),
        "combinations": list(read_jsonl(MICRO_DIR / "combinations.jsonl", Combination)),
        "tasks": list(read_jsonl(MICRO_DIR / "tasks.jsonl", TaskLabel)),
    }

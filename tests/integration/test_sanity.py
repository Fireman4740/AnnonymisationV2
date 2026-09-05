"""Tests de sanité S1 à S3 (SPEC-07 §11, SPEC-10 §10)."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import pytest

from anonymisation.pipeline.orchestrator import Pipeline
from anonymisation.pipeline.profiles import load_runtime_profile
from anonymisation.schema.io import read_jsonl
from anonymisation.schema.models import Annotation, Document
from integration._micro import write_micro_pivot

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CorpusCase:
    """Documents et gold d'un corpus utilisé par les contrôles S1-S3."""

    name: str
    documents: tuple[Document, ...]
    gold_by_doc: dict[str, tuple[Annotation, ...]]


def _load_case(name: str, tmp_path: Path) -> CorpusCase:
    if name == "micro":
        root = write_micro_pivot(tmp_path / "processed")
        base = root / "micro" / "train"
    else:
        base = REPO_ROOT / "data" / "processed" / name / "train"
        if not (base / "documents.jsonl").is_file():
            pytest.skip(f"{name} absent : ingérez le corpus avant les tests de sanité")

    documents = tuple(read_jsonl(base / "documents.jsonl", Document))
    annotations = tuple(read_jsonl(base / "annotations.jsonl", Annotation))
    gold: dict[str, list[Annotation]] = {}
    for annotation in annotations:
        gold.setdefault(annotation.doc_id, []).append(annotation)
    return CorpusCase(
        name=name,
        documents=documents,
        gold_by_doc={doc_id: tuple(values) for doc_id, values in gold.items()},
    )


@pytest.fixture(params=["micro", pytest.param("quasifr", marks=pytest.mark.requires_data)])
def corpus_case(request: pytest.FixtureRequest, tmp_path: Path) -> CorpusCase:
    """Fait tourner les mêmes assertions sur le micro et le corpus réel disponible."""
    return _load_case(str(request.param), tmp_path)


def _gold_leakage(text: str, annotations: tuple[Annotation, ...]) -> int:
    """Compte les surfaces gold encore présentes dans le texte."""
    return sum(
        1
        for annotation in annotations
        if annotation.span_text is not None and annotation.span_text in text
    )


def _utility_retention(original: str, anonymized: str) -> float:
    """Proxy de sanité : similarité de caractères, bornée entre 0 et 1."""
    return SequenceMatcher(None, original, anonymized).ratio()


def _all_gold(case: CorpusCase) -> tuple[Annotation, ...]:
    return tuple(annotation for values in case.gold_by_doc.values() for annotation in values)


def test_s1_original_text_has_high_gold_leakage_and_full_utility(corpus_case: CorpusCase) -> None:
    """S1 : le texte inchangé fuit le gold et conserve toute son utilité."""
    original = "\n".join(document.text for document in corpus_case.documents)
    gold = _all_gold(corpus_case)
    explicit = tuple(annotation for annotation in gold if annotation.span_text is not None)
    leaked = _gold_leakage(original, explicit)

    assert explicit, f"{corpus_case.name}: le corpus de sanité doit avoir du gold positionnel"
    assert leaked >= max(1, int(0.8 * len(explicit))), (
        f"{corpus_case.name}: S1 fuite gold trop faible ({leaked}/{len(explicit)})"
    )
    assert _utility_retention(original, original) == pytest.approx(1.0)


def test_s2_empty_text_has_no_gold_leakage_and_collapsed_utility(corpus_case: CorpusCase) -> None:
    """S2 : supprimer tout le texte supprime la fuite au prix de l'utilité."""
    original = "\n".join(document.text for document in corpus_case.documents)
    gold = _all_gold(corpus_case)
    assert _gold_leakage("", gold) == 0, f"{corpus_case.name}: S2 laisse fuiter du gold"
    assert _utility_retention(original, "") == pytest.approx(0.0)


def test_s3_privacy_utility_curve_is_monotone(corpus_case: CorpusCase) -> None:
    """S3 : les cinq politiques forment une courbe privacy-utilité monotone."""
    profile = load_runtime_profile("deterministic").profile
    policies = ("P0", "P1", "P2", "P3", "P4")
    previous_leakage: int | None = None
    previous_utility: float | None = None

    for policy in policies:
        pipeline = Pipeline(profile, policy_id=policy)
        results = [
            pipeline.run(document, corpus_case.gold_by_doc.get(document.doc_id, ()))
            for document in corpus_case.documents
        ]
        leakage = sum(
            _gold_leakage(
                result.anonymized_text,
                corpus_case.gold_by_doc.get(result.doc_id, ()),
            )
            for result in results
        )
        total_chars = sum(len(document.text) for document in corpus_case.documents)
        utility = (
            sum(
                _utility_retention(document.text, result.anonymized_text) * len(document.text)
                for document, result in zip(corpus_case.documents, results, strict=True)
            )
            / total_chars
            if total_chars
            else 0.0
        )

        if previous_leakage is not None:
            assert leakage <= previous_leakage, (
                f"{corpus_case.name}: S3 fuite augmente avec {policy} "
                f"({previous_leakage} -> {leakage})"
            )
        if previous_utility is not None:
            assert utility <= previous_utility + 1e-12, (
                f"{corpus_case.name}: S3 utilité augmente avec {policy} "
                f"({previous_utility:.6f} -> {utility:.6f})"
            )
        previous_leakage = leakage
        previous_utility = utility

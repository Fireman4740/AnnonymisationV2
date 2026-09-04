"""Scorecard et invariants d'agrégation (ticket D-4, SPEC-07 §10).

Ces tests portent sur ``build_scorecard`` seul : aucun fichier, aucun run, et
donc aucune dépendance au pivot ingéré. Les cas couverts sont ceux où une
agrégation naïve donnerait un chiffre flatteur mais faux.
"""

from __future__ import annotations

import json

import pytest

from anonymisation.metrics.contracts import MetricStatus
from anonymisation.metrics.scorecard import ScorecardError, build_scorecard, validate_scorecard
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Stability,
)

LOCK = {
    "run": {
        "dataset": "mini",
        "split": "train",
        "profile": "deterministic",
        "policy": "P2",
        "status": "complete",
    },
    "data_version": {"source": "fixture"},
    "taxonomy_version": "1.0",
    "code": {"git_commit": "fixture-commit"},
    "models": [],
    "seeds": {"determinism": 42},
    "prompts": [],
    "policy": {"id": "P2", "source": "policies.yaml", "sha256": "a" * 64},
}


def _document(doc_id: str, text: str) -> Document:
    return Document(
        doc_id=doc_id,
        dataset="mini",
        split="train",
        domain="hr",
        language="fr",
        text=text,
    )


def _annotation(
    doc_id: str,
    start: int,
    end: int,
    *,
    span_text: str,
    expression_mode: ExpressionMode = ExpressionMode.EXPLICIT,
    identifier_type: IdentifierType = IdentifierType.DIRECT,
    category: str = "DIR_NAME",
) -> Annotation:
    return Annotation(
        annotation_id=f"{doc_id}-{start}-{end}",
        doc_id=doc_id,
        start=start,
        end=end,
        span_text=span_text,
        identifier_type=identifier_type,
        qi_categories=(category,),
        expression_mode=expression_mode,
        granularity=Granularity.EXACT,
        stability=Stability.STABLE,
    )


def _prediction(doc_id: str, annotations: list[Annotation]) -> dict:
    return {
        "doc_id": doc_id,
        "status": "ok",
        "error": [],
        "annotations": [a.model_dump(mode="json") for a in annotations],
        "decisions": [],
        "anonymized_text": "",
        "risk": None,
        "runtime_ms": 0.0,
    }


def _build(documents, gold_by_doc, predictions, **kwargs) -> dict:
    return build_scorecard(
        run_id="run-1",
        dataset="mini",
        split="train",
        protocol="mini-diagnostic",
        protocol_version="1",
        predictions=predictions,
        gold_by_doc=gold_by_doc,
        documents_by_doc=documents,
        reproducibility=LOCK,
        requested_status=MetricStatus.DIAGNOSTIC,
        **kwargs,
    )


def test_entity_recall_never_matches_across_documents() -> None:
    """Une prédiction du document B ne protège pas une mention du document A.

    Les deux documents portent « Alice » aux mêmes offsets ; seul le second est
    prédit. Une agrégation qui met en commun les spans de tout le corpus avant
    de comparer les offsets afficherait 100 % de protection.
    """
    documents = {
        "d1": _document("d1", "Alice travaille."),
        "d2": _document("d2", "Alice travaille."),
    }
    gold = {
        "d1": (_annotation("d1", 0, 5, span_text="Alice"),),
        "d2": (_annotation("d2", 0, 5, span_text="Alice"),),
    }
    predictions = [
        _prediction("d1", []),
        _prediction("d2", [_annotation("d2", 0, 5, span_text="Alice")]),
    ]
    card = _build(documents, gold, predictions)
    recall = card["diagnostic"]["entity_recall_direct"]
    assert recall["details"]["entities"] == 2
    assert recall["value"] == pytest.approx(0.5)


def test_by_expression_splits_gold_and_predictions_per_mode() -> None:
    """Chaque mode ne porte que ses propres spans.

    Le document mélange une mention explicite et une mention implicite ; verser le
    document entier dans les deux seaux ferait apparaître 2 golds par mode,
    soit le double de l'effectif réel du corpus.
    """
    documents = {"d1": _document("d1", "Alice, la voisine du dessus, travaille.")}
    explicit = _annotation("d1", 0, 5, span_text="Alice")
    implicit = _annotation(
        "d1", 7, 29, span_text="la voisine du dessus",
        expression_mode=ExpressionMode.IMPLICIT,
    )
    gold = {"d1": (explicit, implicit)}
    predictions = [_prediction("d1", [explicit])]
    card = _build(documents, gold, predictions)
    by_expression = card["by_expression"]
    assert by_expression["EXPLICIT"]["gold"] == 1
    assert by_expression["EXPLICIT"]["tp"] == 1
    assert by_expression["IMPLICIT"]["gold"] == 1
    assert by_expression["IMPLICIT"]["tp"] == 0
    assert sum(values["gold"] for values in by_expression.values()) == 2


def test_document_without_prediction_does_not_zero_token_precision() -> None:
    """Un document sans identifiant ni prédiction sort de la moyenne token.

    Compter sa précision comme ``0.0`` ferait chuter de moitié le score d'un
    système pourtant parfait sur les deux documents.
    """
    documents = {
        "d1": _document("d1", "Alice travaille."),
        "d2": _document("d2", "Rien a signaler ici."),
    }
    annotation = _annotation("d1", 0, 5, span_text="Alice")
    gold = {"d1": (annotation,)}
    predictions = [_prediction("d1", [annotation]), _prediction("d2", [])]
    card = _build(documents, gold, predictions)
    assert card["diagnostic"]["weighted_token_precision"]["value"] == pytest.approx(1.0)


def test_macro_f1_ignores_categories_without_gold() -> None:
    """Le macro-F1 des catégories est publié et n'intègre pas les ``None``."""
    documents = {"d1": _document("d1", "Alice travaille a Lyon.")}
    annotation = _annotation("d1", 0, 5, span_text="Alice")
    gold = {"d1": (annotation,)}
    predictions = [_prediction("d1", [annotation])]
    card = _build(documents, gold, predictions)
    assert card["macro_f1"]["value"] == pytest.approx(1.0)
    assert card["macro_f1"]["details"]["categories"] == 1


def test_scorecard_survives_a_json_round_trip() -> None:
    """Aller-retour JSON sans perte : la scorecard relue reste valide (D-4)."""
    documents = {"d1": _document("d1", "Alice travaille.")}
    annotation = _annotation("d1", 0, 5, span_text="Alice")
    predictions = [_prediction("d1", [annotation])]
    card = _build(documents, {"d1": (annotation,)}, predictions)
    reloaded = json.loads(json.dumps(card, ensure_ascii=False, sort_keys=True))
    validate_scorecard(reloaded)
    assert reloaded == json.loads(json.dumps(card, ensure_ascii=False, sort_keys=True))
    assert reloaded["publishable"] is True
    assert reloaded["error_rate"] == 0.0

def test_primary_proxy_risk_is_rejected_even_if_metric_is_forced() -> None:
    documents = {"d1": _document("d1", "Alice travaille.")}
    annotation = _annotation("d1", 0, 5, span_text="Alice")
    card = _build(documents, {"d1": (annotation,)}, [_prediction("d1", [annotation])])
    card["primary"]["naive_risk"] = {"status": MetricStatus.PROXY}

    with pytest.raises(ScorecardError, match="PROXY"):
        validate_scorecard(card)


def test_naive_risk_cannot_produce_official_scorecard() -> None:
    documents = {"d1": _document("d1", "Alice travaille.")}
    annotation = _annotation("d1", 0, 5, span_text="Alice")
    prediction = _prediction("d1", [annotation])
    prediction["risk"] = {"risk": 0.5, "status": "PROXY"}

    with pytest.raises(ScorecardError, match="OFFICIAL"):
        build_scorecard(
            run_id="run-naive",
            dataset="mini",
            split="train",
            protocol="mini-diagnostic",
            protocol_version="1",
            predictions=[prediction],
            gold_by_doc={"d1": (annotation,)},
            documents_by_doc=documents,
            reproducibility=LOCK,
            requested_status=MetricStatus.OFFICIAL,
        )

"""Métriques spans, entités et ventilations D-1 (SPEC-07 §2)."""

from __future__ import annotations

import pytest

from anonymisation.metrics.entities import entity_recall
from anonymisation.metrics.spans import category_metrics, span_metrics, weighted_token_precision
from anonymisation.schema.models import Annotation
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Stability,
)


def _annotation(
    start: int,
    end: int,
    *,
    entity_id: str | None = None,
    category: str = "DIR_NAME",
    identifier_type: IdentifierType = IdentifierType.DIRECT,
    text: str | None = None,
) -> Annotation:
    return Annotation(
        annotation_id=f"a-{start}-{end}-{entity_id or 'x'}",
        doc_id="d1",
        start=start,
        end=end,
        span_text=text,
        identifier_type=identifier_type,
        qi_categories=(category,),
        expression_mode=ExpressionMode.EXPLICIT,
        granularity=Granularity.EXACT,
        stability=Stability.STABLE,
        entity_id=entity_id,
    )


def test_exact_overlap_entity_modes_are_declared_and_distinct() -> None:
    gold = [_annotation(0, 4, entity_id="person"), _annotation(10, 14, entity_id="person")]
    pred = [
        _annotation(0, 4, entity_id="person"),
        _annotation(9, 15, entity_id="person"),
        _annotation(30, 34, entity_id="person"),
    ]
    exact = span_metrics(gold, pred, match="exact")
    overlap = span_metrics(gold, pred, match="overlap")
    entity = span_metrics(gold, pred, match="entity")
    assert exact["mode"] == "exact"
    assert overlap["mode"] == "overlap"
    assert entity["mode"] == "entity"
    assert len({exact["f1"], overlap["f1"], entity["f1"]}) == 3


def test_entity_recall_requires_all_mentions_of_repeated_entity() -> None:
    gold = [_annotation(0, 4, entity_id="person"), _annotation(10, 14, entity_id="person")]
    pred = [_annotation(0, 4, entity_id="person")]
    span_recall = span_metrics(gold, pred)["recall"]
    assert span_recall == pytest.approx(0.5)
    assert entity_recall(gold, pred, identifier_type=IdentifierType.DIRECT) == 0.0


def test_category_without_gold_is_null_not_zero() -> None:
    pred = [_annotation(0, 4, category="DIR_NAME")]
    result = category_metrics([], pred, "DIR_EMAIL")
    assert result["gold"] == 0
    assert result["recall"] is None
    assert result["f1"] is None


def test_f2_exceeds_f1_when_recall_exceeds_precision() -> None:
    gold = [_annotation(0, 4)]
    pred = [_annotation(0, 4), _annotation(10, 14)]
    result = span_metrics(gold, pred)
    assert result["recall"] > result["precision"]
    assert result["f2"] > result["f1"]


def test_weighted_token_precision_uses_text_and_predicted_tokens() -> None:
    text = "Alice travaille ici"
    gold = [_annotation(0, 5, text="Alice")]
    pred = [
        _annotation(0, 5, text="Alice"),
        _annotation(15, 18, text="ici"),
    ]
    assert weighted_token_precision(gold, pred, text) == pytest.approx(5 / 8)


def test_unknown_match_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="Mode de correspondance"):
        span_metrics([], [], match="invalid")


def test_matching_is_maximal_and_order_independent() -> None:
    """Un gold large ne doit pas confisquer la seule prédiction d'un gold étroit.

    Un appariement glouton apparierait ``(0, 10)`` avec ``(0, 2)`` et laisserait
    le gold ``(0, 2)`` sans partenaire : TP=1 au lieu de 2.
    """
    gold = [_annotation(0, 10), _annotation(0, 2)]
    pred = [_annotation(0, 2), _annotation(4, 6)]
    result = span_metrics(gold, pred, match="overlap")
    assert (result["tp"], result["fp"], result["fn"]) == (2, 0, 0)
    reversed_result = span_metrics(list(reversed(gold)), list(reversed(pred)), match="overlap")
    assert reversed_result["tp"] == result["tp"]


def test_weighted_token_precision_is_none_without_prediction() -> None:
    """Sans token prédit le dénominateur est vide : la précision est indéfinie.

    Renvoyer ``0.0`` pénaliserait un système qui, à raison, ne prédit rien sur
    un document sans identifiant.
    """
    assert weighted_token_precision([], [], "un texte sans identifiant") is None

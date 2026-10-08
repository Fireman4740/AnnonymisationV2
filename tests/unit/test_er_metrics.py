"""ER_di/ER_qi et partial-match SemEval (ticket G-5)."""

from __future__ import annotations

import pytest

from anonymisation.metrics.entities import entity_recall, entity_recall_metrics
from anonymisation.metrics.spans import span_metrics
from anonymisation.schema.models import Annotation
from anonymisation.schema.taxonomy import ExpressionMode, Granularity, IdentifierType, Stability


def _annotation(
    start: int,
    end: int,
    *,
    entity_id: str | None = None,
    identifier_type: IdentifierType = IdentifierType.DIRECT,
    annotator_id: str | None = None,
) -> Annotation:
    return Annotation(
        annotation_id=f"a-{start}-{end}-{entity_id or 'x'}-{annotator_id or 'none'}",
        doc_id="d1",
        start=start,
        end=end,
        span_text="x" * (end - start),
        identifier_type=identifier_type,
        qi_categories=("DIR_NAME",) if identifier_type is IdentifierType.DIRECT else ("GEN_AGE",),
        expression_mode=ExpressionMode.EXPLICIT,
        granularity=Granularity.EXACT,
        stability=Stability.STABLE,
        entity_id=entity_id,
        annotator_id=annotator_id,
    )


def test_three_matching_modes_are_distinct() -> None:
    gold = [_annotation(0, 4, entity_id="person"), _annotation(10, 14, entity_id="person")]
    pred = [_annotation(0, 4, entity_id="person"), _annotation(9, 15, entity_id="person")]

    exact = span_metrics(gold, pred, match="exact")
    partial = span_metrics(gold, pred, match="partial")
    entity = span_metrics(gold, pred, match="entity")

    assert exact["f1"] < partial["f1"] < entity["f1"]
    assert partial["partial"] == 1
    assert partial["tp"] == pytest.approx(1.5)


def test_four_mentions_three_masked_have_span_recall_but_zero_entity_recall() -> None:
    gold = [_annotation(index * 10, index * 10 + 4, entity_id="person") for index in range(4)]
    pred = gold[:3]

    assert span_metrics(gold, pred, match="partial")["recall"] == pytest.approx(0.75)
    assert entity_recall(gold, pred, identifier_type=IdentifierType.DIRECT) == 0.0
    assert entity_recall_metrics(gold, pred)["ER_di"] == 0.0


def test_entity_recall_is_micro_averaged_over_divergent_annotators() -> None:
    gold = [
        _annotation(0, 4, entity_id="a", annotator_id="ann-1"),
        _annotation(10, 14, entity_id="b", annotator_id="ann-2"),
    ]
    pred = [_annotation(0, 4, entity_id="a")]

    assert entity_recall(gold, pred, identifier_type=IdentifierType.DIRECT) == pytest.approx(0.5)


def test_unlocalized_gold_is_excluded_from_entity_recall():
    """Un attribut sans offsets n'a pas de mention à masquer : hors dénominateur ER."""
    from anonymisation.metrics.entities import entity_protection_counts

    localized = {"start": 0, "end": 5, "span_text": "Alice", "identifier_type": "direct",
                 "qi_categories": ["DIR_NAME"]}
    unlocalized = {"start": None, "end": None, "span_text": None, "identifier_type": "direct",
                   "qi_categories": ["DIR_EMAIL"]}
    assert entity_protection_counts([localized, unlocalized], [localized],
                                    identifier_type="direct") == (1, 1)
    assert entity_protection_counts([unlocalized], [], identifier_type="direct") == (0, 0)

"""Schémas de spans délégués à nervaluate, et masques appliqués (EPIC-H H-8)."""

from __future__ import annotations

import pytest
from nervaluate import Evaluator

from anonymisation.metrics.masking import MaskingError, document_coverage
from anonymisation.metrics.ner_schemas import SCHEMAS, corpus_counts, document_counts, to_entities


def _span(start: int, end: int, *categories: str) -> dict:
    return {"start": start, "end": end, "qi_categories": list(categories or ("DIR_NAME",)),
            "identifier_type": "DIRECT"}


def test_adapter_turns_exclusive_end_into_nervaluate_inclusive_end():
    entities, unanchored = to_entities([_span(0, 3), {"start": None, "end": None,
                                                       "qi_categories": ["GEN_AGE"]}])
    assert entities == [{"label": "DIR_NAME", "start": 0, "end": 2}]
    assert unanchored == 1


def test_touching_spans_do_not_overlap_once_ends_are_adapted():
    counts, _ = document_counts([_span(0, 3)], [_span(3, 5)])
    assert counts["partial"].partial == 0
    assert counts["partial"].spurious == 1 and counts["partial"].missed == 1


def test_wrong_category_counts_for_localisation_but_not_classification():
    """Le `partial` original ignore le type ; seuls `ent_type` et `strict` l'exigent."""
    counts, _ = document_counts([_span(0, 5, "DIR_NAME")], [_span(0, 5, "GEN_GEO")])
    assert counts["exact"].correct == 1
    assert counts["partial"].correct == 1
    assert counts["strict"].correct == 0 and counts["strict"].incorrect == 1
    assert counts["ent_type"].correct == 0


def test_overlap_earns_half_credit_in_partial():
    counts, _ = document_counts([_span(0, 10)], [_span(2, 6)])
    assert counts["partial"].scores("partial")["recall"] == 0.5
    assert counts["exact"].scores("exact")["recall"] == 0.0


def test_duplicate_prediction_is_spurious_and_repeated_mentions_count_separately():
    counts, _ = document_counts([_span(0, 4), _span(10, 14)], [_span(0, 4), _span(0, 4)])
    assert counts["strict"].correct == 1
    assert counts["strict"].spurious == 1
    assert counts["strict"].missed == 1


def test_document_counts_add_up_to_nervaluate_on_the_whole_corpus():
    docs = [
        ([_span(0, 4), _span(8, 12, "GEN_AGE")], [_span(0, 4, "GEN_GEO"), _span(9, 12, "GEN_AGE")]),
        ([_span(1, 3)], []),
        ([], [_span(5, 9)]),
    ]
    total, per_doc, _ = corpus_counts(docs)
    gold = [to_entities(g)[0] for g, _ in docs]
    pred = [to_entities(p)[0] for _, p in docs]
    tags = sorted({e["label"] for doc in gold + pred for e in doc})
    reference = Evaluator(gold, pred, tags=tags, loader="dict").evaluate()["overall"]
    for schema in SCHEMAS:
        assert total[schema].correct == reference[schema].correct
        assert total[schema].partial == reference[schema].partial
        assert total[schema].actual == reference[schema].actual
        assert total[schema].possible == reference[schema].possible
        assert total[schema].scores(schema)["f1"] == pytest.approx(reference[schema].f1)
    assert len(per_doc) == 3


def test_detected_but_kept_span_is_not_masked():
    text = "Alice vit à Lyon."
    gold = [_span(0, 5), _span(12, 16, "GEN_GEO")]
    decisions = [{"start": 0, "end": 5, "action": "KEEP"},
                 {"start": 12, "end": 14, "action": "SUPPRESS"}]
    coverage = document_coverage(gold, decisions, text)
    assert coverage.covered_chars == 2 and coverage.gold_chars == 9
    assert coverage.covered_mentions == 0 and coverage.gold_mentions == 2


def test_mention_annotated_twice_counts_once_for_masking():
    coverage = document_coverage([_span(0, 5), _span(0, 5, "GEN_GEO")],
                                 [{"start": 0, "end": 5, "action": "SUPPRESS"}], "Alice")
    assert coverage.gold_mentions == 1 and coverage.mention_rate == 1.0


def test_decision_outside_the_text_is_an_error():
    with pytest.raises(MaskingError, match="invalides"):
        document_coverage([_span(0, 5)], [{"start": 3, "end": 99, "action": "SUPPRESS"}], "Alice")

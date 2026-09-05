"""Tests du risque de ré-identification TRIA/TRIR (ticket G-3)."""

from __future__ import annotations

import pytest

from anonymisation.metrics.tria import TRIARecord, evaluate_trir


@pytest.fixture
def records() -> list[TRIARecord]:
    return [
        TRIARecord("d1", "alice", "alice quantum researcher in paris"),
        TRIARecord("d2", "bob", "bob marine engineer in madrid"),
        TRIARecord("d3", "carol", "carol historian in berlin"),
        TRIARecord("d4", "dave", "dave physician in lisbon"),
    ]


def test_trir_is_high_on_original_text_and_declares_candidates(
    records: list[TRIARecord],
) -> None:
    result = evaluate_trir(records)

    assert result.accuracy == pytest.approx(1.0)
    assert result.candidate_count == 4
    assert result.candidate_subjects == ("alice", "bob", "carol", "dave")
    assert result.to_dict()["chance_level"] == pytest.approx(0.25)


def test_trir_on_fully_suppressed_text_is_at_chance(
    records: list[TRIARecord],
) -> None:
    result = evaluate_trir(records, ["", "", "", ""])

    assert result.candidate_count == 4
    assert result.accuracy == pytest.approx(0.25)


def test_trir_accepts_document_id_mapping_for_anonymized_text(
    records: list[TRIARecord],
) -> None:
    result = evaluate_trir(records, {record.doc_id: "" for record in records})

    assert result.total == len(records)
    assert result.correct == 1

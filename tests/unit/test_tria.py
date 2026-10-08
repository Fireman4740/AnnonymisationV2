"""Tests du risque de ré-identification TRIA/TRIR (ticket G-3, EPIC-H H-2).

Le cœur de ces tests est l'hypothèse de TRIA : l'attaquant s'entraîne sur des
connaissances auxiliaires **disjointes** des documents qu'il attaque. La
version 1 entraînait sur les originaux des cibles ; les tests ci-dessous
échoueraient sur cette implémentation.
"""

from __future__ import annotations

import pytest

from anonymisation.metrics import tria
from anonymisation.metrics.tria import (
    TfidfReidentifier,
    TRIARecord,
    TRIRUnavailable,
    assign_folds,
    evaluate_trir,
    expected_hit,
)

# Chaque sujet a 2 documents qui partagent un vocabulaire propre (connaissance
# auxiliaire utile) sans être identiques (la cible n'est pas recopiée).
_PROFILES = {
    "alice": ("quantum physics laboratory paris", "quantum optics seminar paris"),
    "bob": ("marine engineering shipyard madrid", "marine turbines shipyard madrid"),
    "carol": ("medieval history archives berlin", "medieval manuscripts archives berlin"),
    "dave": ("cardiology hospital ward lisbon", "cardiology clinic ward lisbon"),
}


@pytest.fixture
def records() -> list[TRIARecord]:
    return [
        TRIARecord(f"{subject}-{index}", subject, text)
        for subject, texts in _PROFILES.items()
        for index, text in enumerate(texts)
    ]


def test_attacker_never_trains_on_its_target(
    records: list[TRIARecord], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chaque apprentissage exclut les cibles du bloc — la fuite v1 est impossible."""
    seen_training: list[set[str]] = []
    original_fit = TfidfReidentifier.fit

    def spy_fit(self: TfidfReidentifier, rows):  # type: ignore[no-untyped-def]
        rows = list(rows)
        seen_training.append({row.doc_id for row in rows})
        return original_fit(self, rows)

    monkeypatch.setattr(TfidfReidentifier, "fit", spy_fit)
    result = evaluate_trir(records)

    folds = assign_folds(records, result.folds)
    for training in seen_training:
        fold_of_training = {folds[doc_id] for doc_id in training}
        targets = {doc_id for doc_id, fold in folds.items() if fold not in fold_of_training}
        assert training.isdisjoint(targets)
    assert {o.doc_id for o in result.outcomes} == {r.doc_id for r in records}


def test_unanonymized_text_is_reidentified_without_being_copied(
    records: list[TRIARecord],
) -> None:
    """S1 : texte original → TRIR élevé grâce aux AUTRES documents du sujet."""
    result = evaluate_trir(records)
    assert result.accuracy == pytest.approx(1.0)
    assert result.candidate_count == 4
    assert result.excluded_no_background == 0


def test_fully_suppressed_text_is_exactly_at_chance(records: list[TRIARecord]) -> None:
    """S2 : texte vide → égalité totale → espérance = hasard, sans biais d'ordre."""
    result = evaluate_trir(records, {record.doc_id: "" for record in records})
    assert result.accuracy == pytest.approx(result.chance_level)
    assert result.top5 == pytest.approx(1.0)  # 4 candidats ≤ 5


def test_subject_specific_vocabulary_removed_lowers_trir(records: list[TRIARecord]) -> None:
    """Retirer les termes discriminants fait chuter TRIR (monotonie, S3)."""
    generic = {record.doc_id: "a person works somewhere" for record in records}
    assert evaluate_trir(records, generic).accuracy < evaluate_trir(records).accuracy


def test_singleton_subjects_are_excluded_but_serve_as_distractors() -> None:
    rows = [
        TRIARecord("a1", "alice", "quantum physics paris"),
        TRIARecord("a2", "alice", "quantum optics paris"),
        TRIARecord("z1", "zoe", "quantum physics paris"),  # seule, distractrice
    ]
    result = evaluate_trir(rows)
    assert result.excluded_no_background == 1
    assert result.total == 2
    assert result.candidate_count == 2


def test_corpus_without_cross_document_identity_is_unavailable() -> None:
    """Un sujet par document (repli `doc_id`) → TRIR non défini, jamais 1.0."""
    rows = [TRIARecord(f"d{i}", f"d{i}", f"text {i}") for i in range(4)]
    with pytest.raises(TRIRUnavailable, match="plus d'un document"):
        evaluate_trir(rows)


def test_missing_anonymized_text_is_an_error(records: list[TRIARecord]) -> None:
    """Un texte absent n'est pas une suppression totale."""
    with pytest.raises(ValueError, match="texte anonymisé absent"):
        evaluate_trir(records, {records[0].doc_id: ""})


def test_single_fold_is_refused(records: list[TRIARecord]) -> None:
    with pytest.raises(ValueError, match="au moins 2 blocs"):
        evaluate_trir(records, folds=1)


def test_expected_hit_resolves_ties_in_expectation() -> None:
    scores = {"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.1}
    assert expected_hit(scores, "a", 1) == pytest.approx(1 / 3)
    assert expected_hit(scores, "d", 1) == 0.0
    assert expected_hit(scores, "d", 5) == 1.0
    assert expected_hit({"a": 0.9, "b": 0.5}, "b", 1) == 0.0


def test_majority_baseline_exceeds_uniform_chance_on_imbalanced_corpus() -> None:
    rows = [TRIARecord(f"big{i}", "big", f"common words {i}") for i in range(6)]
    rows += [
        TRIARecord("s1", "small", "common words x"),
        TRIARecord("s2", "small", "common words y"),
    ]
    result = evaluate_trir(rows)
    assert result.majority_level is not None and result.chance_level is not None
    assert result.majority_level > result.chance_level


def test_fold_assignment_is_deterministic_and_spreads_subject_documents(
    records: list[TRIARecord],
) -> None:
    first = assign_folds(records, 5)
    assert first == assign_folds(list(reversed(records)), 5)
    for subject in _PROFILES:
        assert first[f"{subject}-0"] != first[f"{subject}-1"]


def test_result_serialisation_declares_protocol_and_baselines(
    records: list[TRIARecord],
) -> None:
    payload = evaluate_trir(records).to_dict()
    assert payload["protocol_version"] == tria.PROTOCOL_VERSION == "2"
    for key in ("chance_level", "majority_level", "top5_accuracy", "excluded_no_background"):
        assert key in payload
    assert "candidate_subjects" not in payload


def test_single_candidate_subject_is_unavailable_not_one() -> None:
    """Un seul auteur dans l'échantillon : TRIR = 1 serait le hasard, pas un risque."""
    rows = [TRIARecord("a1", "alice", "x y"), TRIARecord("a2", "alice", "z w")]
    with pytest.raises(TRIRUnavailable, match="un seul sujet candidat"):
        evaluate_trir(rows)

"""Tests de ``datasets/_bio.py`` — conversion BIO → offsets (EPIC-A, A-4).

Critères d'acceptation du ticket :
- ``text[start:end] == span_text`` sur 100 % des spans produits, sur au
  moins 5 cas dont un ``I-`` orphelin et une entité en fin de séquence ;
- longueurs ``tokens``/``tags`` différentes → erreur explicite ;
- étiquette au préfixe invalide → erreur explicite (la v1 les ignorait).
"""

from __future__ import annotations

import pytest

from anonymisation.datasets._bio import bio_to_spans


def _check_invariant(text: str, spans: list[tuple[int, int, str]], surfaces: list[str]) -> None:
    """100 % des spans : la surface extraite du texte est la surface attendue."""
    assert len(spans) == len(surfaces)
    for (start, end, _type), surface in zip(spans, surfaces, strict=True):
        assert 0 <= start < end <= len(text), (start, end, text)
        assert text[start:end] == surface


# --- Cas fonctionnels (5+ requis) ---------------------------------------------- #


def test_simple_entity() -> None:
    """Entité B-/I- classique, fermée par O."""
    text, spans = bio_to_spans(
        ["John", "Smith", "lives", "in", "Paris"],
        ["B-PER", "I-PER", "O", "O", "B-LOC"],
    )
    assert text == "John Smith lives in Paris"
    _check_invariant(
        text,
        spans,
        ["John Smith", "Paris"],
    )
    assert [t for _, _, t in spans] == ["PER", "LOC"]


def test_orphan_i_opens_new_entity() -> None:
    """``I-`` orphelin (sans ``B-`` précédent) ouvre une nouvelle entité."""
    text, spans = bio_to_spans(["The", "Paris", "hotel"], ["O", "I-LOC", "O"])
    assert text == "The Paris hotel"
    _check_invariant(text, spans, ["Paris"])
    assert [t for _, _, t in spans] == ["LOC"]


def test_entity_at_end_of_sequence() -> None:
    """Entité ouverte jusqu'à la fin de la séquence : fermée proprement."""
    text, spans = bio_to_spans(["Marie", "Curie"], ["B-PER", "I-PER"])
    assert text == "Marie Curie"
    _check_invariant(text, spans, ["Marie Curie"])
    assert spans[0][1] == len(text)


def test_i_switching_type_closes_previous() -> None:
    """``I-X`` d'un autre type que l'entité ouverte : fermeture + ouverture."""
    text, spans = bio_to_spans(
        ["John", "Smith"],
        ["B-PER", "I-LOC"],
    )
    _check_invariant(text, spans, ["John", "Smith"])
    assert [(s, e, t) for s, e, t in spans] == [(0, 4, "PER"), (5, 10, "LOC")]


def test_adjacent_entities_without_o() -> None:
    """Deux entités adjacentes : le ``B-`` ferme l'entité précédente."""
    text, spans = bio_to_spans(
        ["John", "Smith", "Paris", "France"],
        ["B-PER", "I-PER", "B-LOC", "I-LOC"],
    )
    _check_invariant(text, spans, ["John Smith", "Paris France"])


def test_glued_punctuation_inside_span() -> None:
    """Ponctuation collée au token : incluse dans la surface extraite."""
    text, spans = bio_to_spans(
        ["monsieur", "Dupont,", "dit"],
        ["B-PER", "I-PER", "O"],
    )
    assert text == "monsieur Dupont, dit"
    _check_invariant(text, spans, ["monsieur Dupont,"])
    assert spans[0] == (0, 16, "PER")


def test_all_o_no_spans() -> None:
    text, spans = bio_to_spans(["a", "b", "c"], ["O", "O", "O"])
    assert text == "a b c"
    assert spans == []


def test_empty_sequence() -> None:
    assert bio_to_spans([], []) == ("", [])


def test_custom_joiner() -> None:
    """``joiner`` vide : offsets continus, pas de séparateur dans la surface."""
    text, spans = bio_to_spans(["Jean", "Pierre"], ["B-PER", "I-PER"], joiner="")
    assert text == "JeanPierre"
    _check_invariant(text, spans, ["JeanPierre"])
    assert spans[0] == (0, 10, "PER")


def test_single_token_entity() -> None:
    text, spans = bio_to_spans(["Paris", "est"], ["B-LOC", "O"])
    _check_invariant(text, spans, ["Paris"])
    assert spans[0] == (0, 5, "LOC")


# --- Erreurs explicites -------------------------------------------------------- #


def test_length_mismatch_is_explicit() -> None:
    """Longueurs différentes → ``ValueError`` nommant les deux compteurs."""
    with pytest.raises(ValueError, match="3 tokens pour 2 étiquettes"):
        bio_to_spans(["a", "b", "c"], ["B-X", "O"])


def test_invalid_prefix_is_explicit() -> None:
    """Préfixe autre que ``B-``/``I-``/``O`` → ``ValueError`` nommant l'index."""
    with pytest.raises(ValueError, match="index 2"):
        bio_to_spans(["a", "b", "c"], ["O", "O", "U-NAME"])


@pytest.mark.parametrize(
    ("tags", "index"),
    [
        (["N"], 0),  # préfixe manquant
        (["b-PER"], 0),  # casse du préfixe
        (["B-"], 0),  # type vide
        (["-PER"], 0),  # préfixe vide
    ],
)
def test_malformed_tags_are_explicit(tags: list[str], index: int) -> None:
    with pytest.raises(ValueError, match=f"index {index}"):
        bio_to_spans(["a"], tags)

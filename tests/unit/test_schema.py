"""Tests des invariants de SPEC-02.

Ces tests ne nécessitent aucune donnée téléchargée : ils doivent passer sur un
clone frais (SPEC-09 §4.1).

Ils incluent des tests NÉGATIFS : un invariant volontairement violé doit faire
échouer la validation. Sans eux, on ne saurait pas si la validation fonctionne.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from anonymisation.schema.models import (
    Annotation,
    Combination,
    CombinationSource,
    Document,
    Domain,
    QiValue,
    RiskModel,
    Scope,
    TargetType,
)
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Stability,
    UnknownQiCodeError,
)

TEXT = "J'ai moins de 30 ans et je suis doctorant, je cherche à poser un arrêt maladie."


def _annotation(**overrides: object) -> Annotation:
    base: dict[str, object] = {
        "annotation_id": "fx:a1",
        "doc_id": "fx:d1",
        "start": 5,
        "end": 20,
        "span_text": "moins de 30 ans",
        "identifier_type": IdentifierType.QUASI,
        "qi_categories": ("GEN_AGE",),
        "expression_mode": ExpressionMode.EXPLICIT,
        "granularity": Granularity.RANGE,
        "stability": Stability.STABLE,
    }
    base.update(overrides)
    return Annotation(**base)  # type: ignore[arg-type]


class TestAnnotation:
    def test_valid(self) -> None:
        ann = _annotation()
        assert ann.qi_categories == ("GEN_AGE",)

    def test_unknown_code_is_rejected(self) -> None:
        """E-MAP-002 : un code hors taxonomie ne dégrade pas en OTHER_QI."""
        with pytest.raises((UnknownQiCodeError, ValidationError)):
            _annotation(qi_categories=("GEN_NOPE",))

    def test_direct_exclusivity(self) -> None:
        """I-ANN-3 : un span DIRECT ne porte que des codes DIR_*."""
        with pytest.raises(ValidationError):
            _annotation(
                identifier_type=IdentifierType.DIRECT,
                qi_categories=("DIR_NAME", "GEN_AGE"),
            )

    def test_no_offsets_requires_implicit(self) -> None:
        """I-ANN-2 : annotation sans offset admise seulement en IMPLICIT."""
        with pytest.raises(ValidationError):
            _annotation(start=None, end=None, span_text=None)

        # Cas légitime : inférence au niveau document (exigence SynthPAI).
        ann = _annotation(
            start=None,
            end=None,
            span_text=None,
            expression_mode=ExpressionMode.IMPLICIT,
        )
        assert ann.start is None

    def test_offsets_must_match_text(self) -> None:
        """I-ANN-1 : violation = échec, jamais un avertissement."""
        _annotation().check_against_text(TEXT)

        with pytest.raises(ValueError, match="I-ANN-1"):
            _annotation(start=0, end=4, span_text="XXXX").check_against_text(TEXT)

    def test_extra_field_is_rejected(self) -> None:
        """extra='forbid' rattrape les fautes de frappe des adaptateurs."""
        with pytest.raises(ValidationError):
            _annotation(qi_categorie=("GEN_AGE",))

    def test_immutable(self) -> None:
        ann = _annotation()
        with pytest.raises(ValidationError):
            ann.start = 12  # type: ignore[misc]


class TestCombination:
    def _combination(self, **overrides: object) -> Combination:
        base: dict[str, object] = {
            "combination_id": "fx:c1",
            "dataset": "fx",
            "target_type": TargetType.PERSON,
            "target_id": "fx:P1",
            "scope": Scope.DOCUMENT,
            "doc_ids": ("fx:d1",),
            "qi_set": (
                QiValue(qi_category="GEN_AGE", normalized={"range": [18, 29]}),
                QiValue(qi_category="GEN_EDUCATION", normalized={"isced": "8"}),
                QiValue(qi_category="HR_ADMIN_PROCEDURE", normalized={"code": "sick_leave"}),
            ),
            "k_true": 3,
            "risk_true": 1 / 3,
            "risk_model": RiskModel.PROSECUTOR,
            "population_id": "fr-hr-2026",
            "at_risk": True,
            "source": CombinationSource.GENERATED,
        }
        base.update(overrides)
        return Combination(**base)  # type: ignore[arg-type]

    def test_valid(self) -> None:
        assert self._combination().k_true == 3

    def test_risk_k_coherence(self) -> None:
        """I-CMB-2 : risk_true == 1/k_true en modèle prosecutor."""
        with pytest.raises(ValidationError):
            self._combination(k_true=3, risk_true=0.9)

    def test_empty_qi_set_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._combination(qi_set=())


class TestDocument:
    def test_valid(self) -> None:
        doc = Document(
            doc_id="fx:d1",
            dataset="fx",
            split="test",
            domain=Domain.HR,
            language="fr",
            text=TEXT,
            author_id="fx:P1",
        )
        assert doc.domain is Domain.HR

    def test_unknown_domain_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Document(
                doc_id="fx:d1",
                dataset="fx",
                split="test",
                domain="marketing",  # type: ignore[arg-type]
                language="fr",
                text=TEXT,
            )

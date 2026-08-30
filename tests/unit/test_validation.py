"""Tests de ``schema/validation.py`` — invariants SPEC-02 via SPEC-04 §5.

Chaque contrôle a un test positif (l'invariant respecté ne produit pas
l'issue) et un test négatif (l'invariant volontairement violé produit le bon
code d'erreur). Sans les négatifs, on ne saurait pas si la validation
fonctionne réellement.

``E-VAL-108`` (fuite de split) est traité en premier dans les commentaires
métier de ce module car c'est, en pratique, le contrôle le plus important :
SPEC-04 §5 le désigne explicitement comme celui qui attrape la fuite par
profil latent.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pour `import fixtures`

from anonymisation.schema.models import (
    Annotation,
    AttributeValue,
    Combination,
    CombinationSource,
    Document,
    Domain,
    Profile,
    QiValue,
    RiskModel,
    Scope,
    TargetType,
)
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Sensitivity,
    Stability,
    Subject,
)
from anonymisation.schema.validation import validate_dataset
from fixtures import load_micro

TEXT = "J'ai moins de 30 ans et je suis doctorant, je cherche à poser un arrêt maladie."


def _doc(**overrides: object) -> Document:
    base: dict[str, object] = {
        "doc_id": "fx:d1",
        "dataset": "fx",
        "split": "train",
        "domain": Domain.HR,
        "language": "fr",
        "text": TEXT,
        "author_id": None,
        "org_id": None,
    }
    base.update(overrides)
    return Document(**base)  # type: ignore[arg-type]


def _ann(**overrides: object) -> Annotation:
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


def _profile(**overrides: object) -> Profile:
    base: dict[str, object] = {
        "person_id": "fx:P1",
        "dataset": "fx",
        "population_id": "fr-hr-2026",
        "attributes": {
            "GEN_AGE": AttributeValue(value=28, normalized={"range": [18, 29]}),
        },
    }
    base.update(overrides)
    return Profile(**base)  # type: ignore[arg-type]


def _combination(**overrides: object) -> Combination:
    base: dict[str, object] = {
        "combination_id": "fx:c1",
        "dataset": "fx",
        "target_type": TargetType.PERSON,
        "target_id": "fx:P1",
        "scope": Scope.DOCUMENT,
        "doc_ids": ("fx:d1",),
        "qi_set": (QiValue(qi_category="GEN_AGE", normalized={"range": [18, 29]}),),
        "k_true": 3,
        "risk_true": 1 / 3,
        "risk_model": RiskModel.PROSECUTOR,
        "population_id": "fr-hr-2026",
        "at_risk": True,
        "source": CombinationSource.GENERATED,
    }
    base.update(overrides)
    return Combination(**base)  # type: ignore[arg-type]


def _codes(report, code: str) -> list:
    return [i for i in report.issues if i.code == code]


# --------------------------------------------------------------------------- #
# Micro-dataset — sanité globale
# --------------------------------------------------------------------------- #
class TestMicroDataset:
    def test_micro_dataset_is_valid(self) -> None:
        data = load_micro()
        report = validate_dataset(
            "micro",
            data["documents"],
            data["annotations"],
            data["profiles"],
            (),
            data["combinations"],
            data["tasks"],
        )
        assert report.status in ("PASS", "WARN")
        assert report.errors() == ()

    def test_micro_dataset_counts(self) -> None:
        data = load_micro()
        report = validate_dataset(
            "micro",
            data["documents"],
            data["annotations"],
            data["profiles"],
            (),
            data["combinations"],
            data["tasks"],
        )
        assert report.counts["documents"] == 5
        assert report.counts["annotations"] == 13
        assert report.counts["profiles"] == 3
        assert report.counts["by_language"] == {"fr": 5}
        assert report.counts["by_domain"] == {"hr": 5}
        assert set(report.counts["by_expression_mode"]) <= {"EXPLICIT", "NON_STANDARD", "IMPLICIT"}
        assert report.counts["by_expression_mode"]["IMPLICIT"] == 1
        assert report.counts["by_identifier_type"]["DIRECT"] == 1


# --------------------------------------------------------------------------- #
# E-VAL-101 — I-ANN-1 : offsets valides
# --------------------------------------------------------------------------- #
class TestEVal101OffsetsValid:
    def test_valid_offsets_produce_no_issue(self) -> None:
        report = validate_dataset("fx", [_doc()], [_ann()])
        assert _codes(report, "E-VAL-101") == []
        assert report.status == "PASS"

    def test_mismatched_span_text_is_blocking(self) -> None:
        """L'annotation elle-même ne connaît pas le texte du document à la
        construction : c'est la validation croisée doc/annotation qui doit
        attraper l'incohérence."""
        bad = _ann(start=0, end=4, span_text="XXXX")
        report = validate_dataset("fx", [_doc()], [bad])
        issues = _codes(report, "E-VAL-101")
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].ref_id == "fx:a1"
        assert report.status == "FAIL"


# --------------------------------------------------------------------------- #
# E-VAL-102 — I-ANN-2 : annotation sans offset hors IMPLICIT
# --------------------------------------------------------------------------- #
class TestEVal102NoOffsetImplicitOnly:
    def test_implicit_without_offsets_is_valid(self) -> None:
        ann = _ann(
            start=None,
            end=None,
            span_text=None,
            expression_mode=ExpressionMode.IMPLICIT,
            granularity=Granularity.COARSE,
        )
        report = validate_dataset("fx", [_doc()], [ann])
        assert _codes(report, "E-VAL-102") == []

    def test_non_implicit_without_offsets_is_blocking(self) -> None:
        """Construit une annotation en contournant le validateur pydantic
        (``model_construct``) pour simuler une donnée chargée sans passer par
        le constructeur validant — c'est le scénario que E-VAL-102 doit
        attraper indépendamment du garde-fou du modèle."""
        bad = Annotation.model_construct(
            annotation_id="fx:a_bad",
            doc_id="fx:d1",
            start=None,
            end=None,
            span_text=None,
            identifier_type=IdentifierType.QUASI,
            qi_categories=("GEN_AGE",),
            expression_mode=ExpressionMode.EXPLICIT,  # pas IMPLICIT -> violation
            sensitivity=Sensitivity.NONE,
            granularity=Granularity.RANGE,
            stability=Stability.STABLE,
            subject=Subject.SELF,
            value_normalized=None,
            entity_id=None,
            annotator_id=None,
            confidence=1.0,
            meta={},
        )
        report = validate_dataset("fx", [_doc()], [bad])
        issues = _codes(report, "E-VAL-102")
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert report.status == "FAIL"


# --------------------------------------------------------------------------- #
# E-VAL-103 — I-ANN-3 : exclusivité DIRECT
# --------------------------------------------------------------------------- #
class TestEVal103DirectExclusivity:
    def test_direct_with_dir_code_is_valid(self) -> None:
        ann = _ann(
            identifier_type=IdentifierType.DIRECT,
            qi_categories=("DIR_EMAIL",),
            granularity=Granularity.EXACT,
        )
        report = validate_dataset("fx", [_doc()], [ann])
        assert _codes(report, "E-VAL-103") == []

    def test_direct_with_non_dir_code_is_blocking(self) -> None:
        bad = Annotation.model_construct(
            annotation_id="fx:a_bad",
            doc_id="fx:d1",
            start=5,
            end=20,
            span_text="moins de 30 ans",
            identifier_type=IdentifierType.DIRECT,
            qi_categories=("GEN_AGE",),  # non-DIR_* avec DIRECT -> violation
            expression_mode=ExpressionMode.EXPLICIT,
            sensitivity=Sensitivity.NONE,
            granularity=Granularity.EXACT,
            stability=Stability.STABLE,
            subject=Subject.SELF,
            value_normalized=None,
            entity_id=None,
            annotator_id=None,
            confidence=1.0,
            meta={},
        )
        report = validate_dataset("fx", [_doc()], [bad])
        issues = _codes(report, "E-VAL-103")
        assert len(issues) == 1
        assert report.status == "FAIL"


# --------------------------------------------------------------------------- #
# E-VAL-104 — I-DOC-3 : références orphelines
# --------------------------------------------------------------------------- #
class TestEVal104Orphans:
    def test_known_author_and_doc_reference_are_valid(self) -> None:
        report = validate_dataset(
            "fx", [_doc(author_id="fx:P1")], [_ann()], [_profile(person_id="fx:P1")]
        )
        assert _codes(report, "E-VAL-104") == []

    def test_orphan_author_id_is_blocking(self) -> None:
        report = validate_dataset("fx", [_doc(author_id="fx:P_absent")], [_ann()], [])
        issues = _codes(report, "E-VAL-104")
        assert any(i.ref_id == "fx:P_absent" for i in issues)
        assert report.status == "FAIL"

    def test_orphan_org_id_is_blocking(self) -> None:
        report = validate_dataset("fx", [_doc(org_id="fx:O_absent")], [_ann()], [])
        issues = _codes(report, "E-VAL-104")
        assert any(i.ref_id == "fx:O_absent" for i in issues)
        assert report.status == "FAIL"

    def test_orphan_annotation_doc_id_is_blocking(self) -> None:
        ann = _ann(doc_id="fx:d_absent")
        report = validate_dataset("fx", [_doc()], [ann])
        issues = _codes(report, "E-VAL-104")
        assert any(i.ref_id == "fx:a1" for i in issues)
        assert report.status == "FAIL"


# --------------------------------------------------------------------------- #
# E-VAL-105 — I-CMB-1 : monotonie du scope
# --------------------------------------------------------------------------- #
class TestEVal105ScopeMonotonicity:
    QI_SET = (QiValue(qi_category="GEN_AGE", normalized={"range": [18, 29]}),)

    def test_monotonic_scopes_produce_no_issue(self) -> None:
        combos = [
            _combination(
                combination_id="fx:c_author",
                scope=Scope.AUTHOR,
                qi_set=self.QI_SET,
                k_true=2,
                risk_true=0.5,
            ),
            _combination(
                combination_id="fx:c_thread",
                scope=Scope.THREAD,
                qi_set=self.QI_SET,
                k_true=3,
                risk_true=1 / 3,
            ),
            _combination(
                combination_id="fx:c_doc",
                scope=Scope.DOCUMENT,
                qi_set=self.QI_SET,
                k_true=5,
                risk_true=1 / 5,
            ),
        ]
        report = validate_dataset("fx", [_doc()], [], [], (), combos)
        assert _codes(report, "E-VAL-105") == []

    def test_violated_monotonicity_is_blocking(self) -> None:
        """k_author > k_document pour le même target_id/qi_set : incohérence
        de génération, doit être détectée."""
        combos = [
            _combination(
                combination_id="fx:c_author",
                scope=Scope.AUTHOR,
                qi_set=self.QI_SET,
                k_true=8,  # devrait être <= k_document
                risk_true=1 / 8,
            ),
            _combination(
                combination_id="fx:c_doc",
                scope=Scope.DOCUMENT,
                qi_set=self.QI_SET,
                k_true=5,
                risk_true=1 / 5,
            ),
        ]
        report = validate_dataset("fx", [_doc()], [], [], (), combos)
        issues = _codes(report, "E-VAL-105")
        assert len(issues) == 1
        assert report.status == "FAIL"

    def test_different_qi_set_is_not_compared(self) -> None:
        """Deux combinaisons de qi_set différents ne sont pas soumises à la
        contrainte de monotonie l'une envers l'autre."""
        combos = [
            _combination(
                combination_id="fx:c_author",
                scope=Scope.AUTHOR,
                qi_set=(QiValue(qi_category="GEN_GEO", normalized={"geo": "FR-59"}),),
                k_true=100,
                risk_true=1 / 100,
            ),
            _combination(
                combination_id="fx:c_doc",
                scope=Scope.DOCUMENT,
                qi_set=self.QI_SET,
                k_true=5,
                risk_true=1 / 5,
            ),
        ]
        report = validate_dataset("fx", [_doc()], [], [], (), combos)
        assert _codes(report, "E-VAL-105") == []


# --------------------------------------------------------------------------- #
# E-VAL-106 — I-CMB-2 : cohérence risque / k en modèle prosecutor
# --------------------------------------------------------------------------- #
class TestEVal106RiskKCoherence:
    def test_consistent_risk_is_valid(self) -> None:
        report = validate_dataset(
            "fx", [_doc()], [], [], (), [_combination(k_true=4, risk_true=0.25)]
        )
        assert _codes(report, "E-VAL-106") == []

    def test_inconsistent_risk_is_blocking(self) -> None:
        bad = Combination.model_construct(
            combination_id="fx:c_bad",
            dataset="fx",
            target_type=TargetType.PERSON,
            target_id="fx:P1",
            scope=Scope.DOCUMENT,
            doc_ids=("fx:d1",),
            qi_set=(QiValue(qi_category="GEN_AGE", normalized={"range": [18, 29]}),),
            k_true=3,
            risk_true=0.9,  # != 1/3
            risk_model=RiskModel.PROSECUTOR,
            population_id="fr-hr-2026",
            at_risk=True,
            source=CombinationSource.GENERATED,
            meta={},
        )
        report = validate_dataset("fx", [_doc()], [], [], (), [bad])
        issues = _codes(report, "E-VAL-106")
        assert len(issues) == 1
        assert report.status == "FAIL"


# --------------------------------------------------------------------------- #
# E-VAL-107 — I-PRO-2 : attribut de profil sans normalized (avertissement)
# --------------------------------------------------------------------------- #
class TestEVal107ProfileNormalized:
    def test_all_attributes_normalized_no_warning(self) -> None:
        profile = _profile()
        report = validate_dataset("fx", [_doc()], [], [profile])
        assert _codes(report, "E-VAL-107") == []
        assert report.status == "PASS"

    def test_attribute_without_normalized_warns_but_does_not_fail(self) -> None:
        profile = _profile(
            attributes={
                "GEN_AGE": AttributeValue(value=28, normalized=None),
            }
        )
        report = validate_dataset("fx", [_doc()], [], [profile])
        issues = _codes(report, "E-VAL-107")
        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert report.status == "WARN"
        assert report.errors() == ()


# --------------------------------------------------------------------------- #
# E-VAL-108 — fuite de split (LE contrôle le plus important, SPEC-04 §5)
# --------------------------------------------------------------------------- #
class TestEVal108SplitLeakage:
    def test_author_confined_to_one_split_is_valid(self) -> None:
        docs = [
            _doc(doc_id="fx:d1", split="train", author_id="fx:P1"),
            _doc(doc_id="fx:d2", split="train", author_id="fx:P1"),
        ]
        report = validate_dataset("fx", docs, [])
        assert _codes(report, "E-VAL-108") == []

    def test_author_split_across_two_splits_is_blocking(self) -> None:
        """Le scénario exact qui produirait des résultats de détection
        excellents et faux : le même auteur observé en train et en test."""
        docs = [
            _doc(doc_id="fx:d1", split="train", author_id="fx:P1"),
            _doc(doc_id="fx:d2", split="test", author_id="fx:P1"),
        ]
        report = validate_dataset("fx", docs, [])
        issues = _codes(report, "E-VAL-108")
        assert len(issues) == 1
        assert issues[0].ref_id == "fx:P1"
        assert report.status == "FAIL"

    def test_org_split_across_two_splits_is_blocking(self) -> None:
        docs = [
            _doc(doc_id="fx:d1", split="train", org_id="fx:O1"),
            _doc(doc_id="fx:d2", split="dev", org_id="fx:O1"),
        ]
        report = validate_dataset("fx", docs, [])
        issues = _codes(report, "E-VAL-108")
        assert len(issues) == 1
        assert issues[0].ref_id == "fx:O1"


# --------------------------------------------------------------------------- #
# E-VAL-109 — volumétrie observée != expected_documents (avertissement)
# --------------------------------------------------------------------------- #
class TestEVal109Volumetry:
    def test_matching_expected_documents_no_warning(self) -> None:
        report = validate_dataset("fx", [_doc()], [], expected_documents=1)
        assert _codes(report, "E-VAL-109") == []
        assert report.status == "PASS"

    def test_mismatched_expected_documents_warns(self) -> None:
        report = validate_dataset("fx", [_doc()], [], expected_documents=5)
        issues = _codes(report, "E-VAL-109")
        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert report.status == "WARN"

    def test_no_expected_documents_is_not_checked(self) -> None:
        report = validate_dataset("fx", [_doc()], [], expected_documents=None)
        assert _codes(report, "E-VAL-109") == []


# --------------------------------------------------------------------------- #
# E-VAL-110 — taux d'OTHER_QI > 1 % (avertissement)
# --------------------------------------------------------------------------- #
class TestEVal110OtherQiRate:
    def test_low_other_qi_rate_no_warning(self) -> None:
        anns = [_ann(annotation_id=f"fx:a{i}") for i in range(100)]
        anns.append(
            _ann(annotation_id="fx:a_other", qi_categories=("OTHER_QI",))
        )
        report = validate_dataset("fx", [_doc()], anns)
        assert _codes(report, "E-VAL-110") == []

    def test_high_other_qi_rate_warns(self) -> None:
        anns = [_ann(annotation_id=f"fx:a{i}") for i in range(10)]
        anns.append(
            _ann(annotation_id="fx:a_other", qi_categories=("OTHER_QI",))
        )
        # 1 sur 11 > 1 %
        report = validate_dataset("fx", [_doc()], anns)
        issues = _codes(report, "E-VAL-110")
        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert report.status == "WARN"


# --------------------------------------------------------------------------- #
# E-VAL-111 — doublons d'identifiants (bloquant)
# --------------------------------------------------------------------------- #
class TestEVal111Duplicates:
    def test_unique_ids_no_issue(self) -> None:
        docs = [_doc(doc_id="fx:d1"), _doc(doc_id="fx:d2")]
        report = validate_dataset("fx", docs, [])
        assert _codes(report, "E-VAL-111") == []

    def test_duplicate_doc_id_is_blocking(self) -> None:
        docs = [_doc(doc_id="fx:d1"), _doc(doc_id="fx:d1")]
        report = validate_dataset("fx", docs, [])
        issues = _codes(report, "E-VAL-111")
        assert any(i.ref_id == "fx:d1" for i in issues)
        assert report.status == "FAIL"

    def test_duplicate_annotation_id_is_blocking(self) -> None:
        anns = [_ann(annotation_id="fx:a1"), _ann(annotation_id="fx:a1")]
        report = validate_dataset("fx", [_doc()], anns)
        issues = _codes(report, "E-VAL-111")
        assert any(i.ref_id == "fx:a1" for i in issues)
        assert report.status == "FAIL"

    def test_duplicate_person_id_is_blocking(self) -> None:
        profiles = [_profile(person_id="fx:P1"), _profile(person_id="fx:P1")]
        report = validate_dataset("fx", [_doc()], [], profiles)
        issues = _codes(report, "E-VAL-111")
        assert any(i.ref_id == "fx:P1" for i in issues)
        assert report.status == "FAIL"

    def test_duplicate_combination_id_is_blocking(self) -> None:
        combos = [
            _combination(combination_id="fx:c1"),
            _combination(combination_id="fx:c1"),
        ]
        report = validate_dataset("fx", [_doc()], [], [], (), combos)
        issues = _codes(report, "E-VAL-111")
        assert any(i.ref_id == "fx:c1" for i in issues)
        assert report.status == "FAIL"


# --------------------------------------------------------------------------- #
# ValidationReport / ValidationIssue — API
# --------------------------------------------------------------------------- #
class TestReportApi:
    def test_pass_status_with_no_issues(self) -> None:
        report = validate_dataset("fx", [_doc()], [_ann()], [_profile()])
        assert report.status == "PASS"
        assert report.issues == ()
        assert report.errors() == ()
        assert report.warnings() == ()

    def test_to_dict_shape(self) -> None:
        report = validate_dataset(
            "fx", [_doc(author_id="fx:P_absent")], [], []
        )
        payload = report.to_dict()
        assert payload["dataset"] == "fx"
        assert payload["status"] == "FAIL"
        assert isinstance(payload["errors"], list)
        assert isinstance(payload["warnings"], list)
        assert payload["errors"][0]["code"] == "E-VAL-104"

    def test_errors_and_warnings_partition_issues(self) -> None:
        docs = [_doc(author_id="fx:P_absent")]
        profile = _profile(
            attributes={"GEN_AGE": AttributeValue(value=28, normalized=None)}
        )
        report = validate_dataset("fx", docs, [], [profile])
        assert len(report.errors()) >= 1
        assert len(report.warnings()) >= 1
        assert set(report.errors()) | set(report.warnings()) == set(report.issues)
        assert report.status == "FAIL"  # une erreur prime sur un avertissement

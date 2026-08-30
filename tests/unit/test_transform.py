"""Tests de la couche de transformation (lot L5).

Couvre : décisions explicables, pseudonymisation HMAC stable, masquage
conservateur, hiérarchies de généralisation, et application des décisions sur
le texte (ordre, chevauchement).
"""

from __future__ import annotations

import pytest

from anonymisation.transform.apply import OverlappingDecisionsError, apply_decisions
from anonymisation.transform.decisions import (
    Action,
    ActionNotAllowedError,
    AnonymizationDecision,
    InvalidDecisionError,
    check_action_allowed,
)
from anonymisation.transform.generalize import (
    MalformedValueNormalizedError,
    UnknownGeneralizationCategoryError,
    generalize,
    levels_available,
)
from anonymisation.transform.mask import UnknownMaskModeError, mask
from anonymisation.transform.pseudonymize import PseudoMapper, normalise_surface


# --------------------------------------------------------------------------- #
# decisions.py
# --------------------------------------------------------------------------- #
def test_check_action_allowed_accepts_valid_combination():
    check_action_allowed("QUASI", "EXACT", Action.GENERALIZE)
    check_action_allowed("DIRECT", None, Action.SUPPRESS)
    check_action_allowed("SENSITIVE_ONLY", None, Action.KEEP)


def test_check_action_allowed_rejects_invalid_combination():
    with pytest.raises(ActionNotAllowedError):
        check_action_allowed("DIRECT", None, Action.GENERALIZE)


def test_coarse_quasi_cannot_be_generalized():
    """Point important de SPEC-01 §8 : un QI COARSE ne peut plus être généralisé."""
    with pytest.raises(ActionNotAllowedError):
        check_action_allowed("QUASI", "COARSE", Action.GENERALIZE)
    # Seule SUPPRESS reste disponible.
    check_action_allowed("QUASI", "COARSE", Action.SUPPRESS)


def test_decision_requires_non_empty_reason():
    with pytest.raises(InvalidDecisionError):
        AnonymizationDecision(
            start=0, end=3, original="abc", action=Action.SUPPRESS, replacement="[X]",
            qi_category="GEN_AGE", reason="   ",
        )


def test_decision_requires_end_after_start():
    with pytest.raises(InvalidDecisionError):
        AnonymizationDecision(
            start=3, end=3, original="", action=Action.KEEP, replacement="",
            qi_category="GEN_AGE", reason="ok",
        )


# --------------------------------------------------------------------------- #
# pseudonymize.py
# --------------------------------------------------------------------------- #
def test_pseudo_mapper_is_stable_within_scope():
    mapper = PseudoMapper(secret=b"secret-test", scope="doc-1")
    p1 = mapper.placeholder("PER", "Jean Dupont")
    p2 = mapper.placeholder("PER", "Jean Dupont")
    assert p1 == p2


def test_pseudo_mapper_normalises_surface_variants():
    mapper = PseudoMapper(secret=b"secret-test", scope="doc-1")
    p1 = mapper.placeholder("PER", "Jean DUPONT")
    p2 = mapper.placeholder("PER", "jean dupont")
    p3 = mapper.placeholder("PER", "Jean  Dupont")
    assert p1 == p2 == p3


def test_pseudo_mapper_isolates_scopes():
    surface = "Jean Dupont"
    mapper_a = PseudoMapper(secret=b"secret-test", scope="scope-a")
    mapper_b = PseudoMapper(secret=b"secret-test", scope="scope-b")
    assert mapper_a.placeholder("PER", surface) != mapper_b.placeholder("PER", surface)


def test_pseudo_mapper_different_secret_gives_different_placeholder():
    surface = "Jean Dupont"
    mapper_a = PseudoMapper(secret=b"secret-1", scope="doc-1")
    mapper_b = PseudoMapper(secret=b"secret-2", scope="doc-1")
    assert mapper_a.placeholder("PER", surface) != mapper_b.placeholder("PER", surface)


def test_pseudo_mapper_mapping_export():
    mapper = PseudoMapper(secret=b"secret-test", scope="doc-1")
    placeholder = mapper.placeholder("PER", "Jean Dupont")
    assert mapper.mapping() == {"Jean Dupont": placeholder}


def test_pseudo_mapper_rejects_empty_secret():
    with pytest.raises(ValueError):
        PseudoMapper(secret=b"", scope="doc-1")


def test_normalise_surface_collapses_whitespace_and_case():
    assert normalise_surface("Jean   DUPONT") == normalise_surface("jean dupont")


# --------------------------------------------------------------------------- #
# mask.py
# --------------------------------------------------------------------------- #
def test_mask_default_mode_is_full_and_generic():
    assert mask("jean.dupont@example.fr", "DIR_EMAIL") == "[DIR_EMAIL]"


def test_mask_partial_email():
    result = mask("jean.dupont@example.fr", "DIR_EMAIL", mode="partial")
    assert result.startswith("j")
    assert "@" in result
    assert "jean.dupont" not in result


def test_mask_partial_iban_keeps_country_code():
    result = mask("FR7630006000011234567890189", "DIR_ACCOUNT", mode="partial")
    assert result.startswith("FR76")


def test_mask_unknown_mode_raises():
    with pytest.raises(UnknownMaskModeError):
        mask("x", "DIR_EMAIL", mode="bogus")


# --------------------------------------------------------------------------- #
# generalize.py
# --------------------------------------------------------------------------- #
def test_generalize_age_step_by_step():
    value = {"range": [28, 28], "level": 0}
    surface, new_value = generalize(value, "GEN_AGE", steps=1)
    assert surface == "25-29 ans"
    assert new_value["level"] == 1

    surface2, new_value2 = generalize(new_value, "GEN_AGE", steps=1)
    assert surface2 == "20-29 ans"
    assert new_value2["level"] == 2

    surface3, new_value3 = generalize(new_value2, "GEN_AGE", steps=1)
    assert surface3 == "18-29 ans"
    assert new_value3["level"] == 3


def test_generalize_age_exhausted_returns_none():
    value = {"range": [28, 28], "level": 3}
    assert generalize(value, "GEN_AGE", steps=1) is None
    assert levels_available(value, "GEN_AGE") == 0


def test_generalize_geo_chain():
    value = {"geo": "FR-59350", "level": 0}
    surface1, value1 = generalize(value, "GEN_GEO", steps=1)
    assert surface1 == "Nord"

    surface2, value2 = generalize(value1, "GEN_GEO", steps=1)
    assert surface2 == "Hauts-de-France"

    surface3, value3 = generalize(value2, "GEN_GEO", steps=1)
    assert surface3 == "France"

    assert levels_available(value3, "GEN_GEO") == 0
    assert generalize(value3, "GEN_GEO", steps=1) is None


def test_generalize_version_chain():
    value = {"semver": "4.2.1", "level": 0}
    surface1, value1 = generalize(value, "SUP_VERSION", steps=1)
    assert surface1 == "4.2"
    surface2, value2 = generalize(value1, "SUP_VERSION", steps=1)
    assert surface2 == "4"
    assert generalize(value2, "SUP_VERSION", steps=1) is None


def test_generalize_multi_step_in_one_call():
    value = {"semver": "4.2.1", "level": 0}
    surface, new_value = generalize(value, "SUP_VERSION", steps=2)
    assert surface == "4"
    assert new_value["level"] == 2


def test_generalize_unknown_category_raises():
    with pytest.raises(UnknownGeneralizationCategoryError):
        generalize({"level": 0}, "NOT_A_CATEGORY", steps=1)


def test_generalize_malformed_value_raises():
    with pytest.raises(MalformedValueNormalizedError):
        generalize({"level": 0}, "GEN_AGE", steps=1)  # pas de clé 'range'


def test_generalize_incident_time_chain():
    value = {"time": "14:32", "date": "2026-08-30", "level": 0}
    surface1, value1 = generalize(value, "SUP_INCIDENT_TIME", steps=1)
    assert surface1 == "après-midi"
    surface2, _value2 = generalize(value1, "SUP_INCIDENT_TIME", steps=1)
    assert surface2 == "2026-08-30"


def test_generalize_employer_size():
    value = {"band": "50-99", "level": 0}
    surface, new_value = generalize(value, "HR_EMPLOYER_SIZE", steps=1)
    assert surface == "50-249 salariés"
    assert generalize(new_value, "HR_EMPLOYER_SIZE", steps=1) is None


# --------------------------------------------------------------------------- #
# apply.py
# --------------------------------------------------------------------------- #
def test_apply_decisions_out_of_order_produces_correct_text():
    """Le test qui attrape le bug d'offsets : les décisions sont fournies dans
    le désordre, l'application doit quand même produire un texte correct.
    """
    text = "Jean Dupont habite à Lille et travaille chez Acme."

    def _at(surface: str, action: Action, replacement: str, category: str):
        """Dérive les offsets du texte plutôt que de les coder en dur.

        Des offsets écrits à la main sont une source d'erreur classique : c'est
        exactement ce que l'invariant I-ANN-1 est censé attraper, et il ne doit
        pas être mis en échec par le harnais de test lui-même.
        """
        start = text.index(surface)
        return AnonymizationDecision(
            start=start, end=start + len(surface), original=surface,
            action=action, replacement=replacement, qi_category=category,
            reason="test",
        )

    d_name = _at("Jean Dupont", Action.SUPPRESS, "[DIR_NAME_SUPPRIME]", "DIR_NAME")
    d_org = _at("Acme", Action.SUPPRESS, "[GEN_AFFILIATION_SUPPRIME]", "GEN_AFFILIATION")
    d_city = _at("Lille", Action.GENERALIZE, "Nord", "GEN_GEO")
    # Ordre volontairement inversé par rapport aux offsets.
    result = apply_decisions(text, [d_org, d_name, d_city])
    assert result.anonymized_text == (
        "[DIR_NAME_SUPPRIME] habite à Nord et travaille chez [GEN_AFFILIATION_SUPPRIME]."
    )


def test_apply_decisions_rejects_overlap():
    text = "Jean Dupont"
    d1 = AnonymizationDecision(
        start=0, end=4, original="Jean", action=Action.SUPPRESS, replacement="[X]",
        qi_category="DIR_NAME", reason="test",
    )
    d2 = AnonymizationDecision(
        start=2, end=11, original="an Dupont", action=Action.SUPPRESS, replacement="[Y]",
        qi_category="DIR_NAME", reason="test",
    )
    with pytest.raises(OverlappingDecisionsError):
        apply_decisions(text, [d1, d2])


def test_apply_decisions_detects_text_mismatch():
    text = "Jean Dupont"
    d1 = AnonymizationDecision(
        start=0, end=4, original="JEAN", action=Action.SUPPRESS, replacement="[X]",
        qi_category="DIR_NAME", reason="test",
    )
    with pytest.raises(ValueError):
        apply_decisions(text, [d1])


def test_apply_decisions_keep_is_noop():
    text = "Jean Dupont"
    d1 = AnonymizationDecision(
        start=0, end=4, original="Jean", action=Action.KEEP, replacement="Jean",
        qi_category="DIR_NAME", reason="test",
    )
    result = apply_decisions(text, [d1])
    assert result.anonymized_text == text
    assert result.mapping == {}


def test_apply_decisions_builds_mapping():
    text = "Jean Dupont"
    d1 = AnonymizationDecision(
        start=0, end=11, original="Jean Dupont", action=Action.PSEUDONYMIZE,
        replacement="[PER_ABC123]", qi_category="DIR_NAME", reason="test",
    )
    result = apply_decisions(text, [d1])
    assert result.mapping == {"Jean Dupont": "[PER_ABC123]"}
    assert result.original_text == text

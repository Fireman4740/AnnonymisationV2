"""Tests des règles de détection contextuelles (detect/rules.py).

Couvre chaque catégorie de QI contextuel exigée par le cahier des charges,
en FR et en EN, avec vérification du ``value_normalized`` quand il existe
(condition nécessaire au calcul de k, SPEC-01 §6.2).
"""

from __future__ import annotations

import pytest

from anonymisation.detect.patterns import load_patterns
from anonymisation.detect.rules import apply_rules
from anonymisation.schema.taxonomy import IdentifierType


@pytest.fixture(scope="module")
def lexicons() -> dict[str, list[str]]:
    _patterns, lex = load_patterns()
    return lex


def _categories(candidates) -> set[str]:
    return {c.qi_category for c in candidates}


class TestAge:
    def test_age_range_fr(self, lexicons) -> None:
        out = apply_rules("moins de 30 ans", "fr", lexicons)
        assert any(c.qi_category == "GEN_AGE" for c in out)
        c = next(c for c in out if c.qi_category == "GEN_AGE")
        assert c.meta["value_normalized"] == {"range": [0, 29]}

    def test_age_exact_fr(self, lexicons) -> None:
        out = apply_rules("j'ai 28 ans et je travaille ici", "fr", lexicons)
        c = next(c for c in out if c.qi_category == "GEN_AGE")
        assert c.meta["value_normalized"] == {"range": [28, 28]}

    def test_age_decade_fr(self, lexicons) -> None:
        out = apply_rules("je suis dans la trentaine", "fr", lexicons)
        c = next(c for c in out if c.qi_category == "GEN_AGE")
        assert c.meta["value_normalized"] == {"range": [30, 39]}

    def test_age_exact_en(self, lexicons) -> None:
        out = apply_rules("I'm 28 years old", "en", lexicons)
        c = next(c for c in out if c.qi_category == "GEN_AGE")
        assert c.meta["value_normalized"] == {"range": [28, 28]}

    def test_age_under_en(self, lexicons) -> None:
        out = apply_rules("under 30", "en", lexicons)
        c = next(c for c in out if c.qi_category == "GEN_AGE")
        assert c.meta["value_normalized"] == {"range": [0, 29]}

    def test_seniority_not_mistaken_for_age(self, lexicons) -> None:
        out = apply_rules("6 ans d'expérience", "fr", lexicons)
        assert "GEN_AGE" not in _categories(out)
        assert "HR_SENIORITY" in _categories(out)


class TestEducation:
    def test_fr(self, lexicons) -> None:
        out = apply_rules("je suis doctorant en physique", "fr", lexicons)
        assert "GEN_EDUCATION" in _categories(out)

    def test_en(self, lexicons) -> None:
        out = apply_rules("I am a PhD student", "en", lexicons)
        assert "GEN_EDUCATION" in _categories(out)


class TestOccupation:
    def test_lexicon_fr(self, lexicons) -> None:
        out = apply_rules("elle est infirmière au CHU", "fr", lexicons)
        assert "GEN_OCCUPATION" in _categories(out)

    def test_intro_fr(self, lexicons) -> None:
        out = apply_rules("je suis développeur", "fr", lexicons)
        cats = _categories(out)
        assert "GEN_OCCUPATION" in cats

    def test_intro_en(self, lexicons) -> None:
        out = apply_rules("I work as a nurse", "en", lexicons)
        assert "GEN_OCCUPATION" in _categories(out)

    def test_all_quasi(self, lexicons) -> None:
        out = apply_rules("je suis développeur", "fr", lexicons)
        for c in out:
            if c.qi_category == "GEN_OCCUPATION":
                assert c.identifier_type is IdentifierType.QUASI


class TestSeniority:
    def test_years_fr(self, lexicons) -> None:
        out = apply_rules("6 ans d'expérience", "fr", lexicons)
        c = next(c for c in out if c.qi_category == "HR_SENIORITY")
        assert c.meta["value_normalized"] == {"range": [6, 6]}

    def test_since_year_fr(self, lexicons) -> None:
        out = apply_rules("je travaille ici depuis 2015", "fr", lexicons)
        c = next(c for c in out if c.qi_category == "HR_SENIORITY")
        assert c.meta["value_normalized"] == {"since_year": 2015}

    def test_years_en(self, lexicons) -> None:
        out = apply_rules("6 years of experience", "en", lexicons)
        c = next(c for c in out if c.qi_category == "HR_SENIORITY")
        assert c.meta["value_normalized"] == {"range": [6, 6]}


class TestHrAdminProcedure:
    def test_fr(self, lexicons) -> None:
        out = apply_rules("je voudrais poser un arrêt maladie", "fr", lexicons)
        assert "HR_ADMIN_PROCEDURE" in _categories(out)

    def test_congenital_fr(self, lexicons) -> None:
        out = apply_rules("je suis en congé parental", "fr", lexicons)
        assert "HR_ADMIN_PROCEDURE" in _categories(out)

    def test_en(self, lexicons) -> None:
        out = apply_rules("I'm currently on sick leave", "en", lexicons)
        assert "HR_ADMIN_PROCEDURE" in _categories(out)


class TestEmployerSize:
    def test_fr(self, lexicons) -> None:
        out = apply_rules("une PME de 400 salariés", "fr", lexicons)
        c = next(c for c in out if c.qi_category == "HR_EMPLOYER_SIZE")
        assert c.meta["value_normalized"] == {"range": [400, 400]}

    def test_en(self, lexicons) -> None:
        out = apply_rules("a company of 50 employees", "en", lexicons)
        c = next(c for c in out if c.qi_category == "HR_EMPLOYER_SIZE")
        assert c.meta["value_normalized"] == {"range": [50, 50]}


class TestVersion:
    def test_semver(self, lexicons) -> None:
        out = apply_rules("nous utilisons la version 4.2.1", "fr", lexicons)
        c = next(c for c in out if c.qi_category == "SUP_VERSION")
        assert c.meta["value_normalized"] == {"semver": "4.2.1"}

    def test_short(self, lexicons) -> None:
        out = apply_rules("sur v12 ça plante", "fr", lexicons)
        c = next(c for c in out if c.qi_category == "SUP_VERSION")
        assert c.meta["value_normalized"] == {"semver": "12"}


class TestOs:
    def test_windows(self, lexicons) -> None:
        out = apply_rules("Windows Server 2022 est installé", "fr", lexicons)
        assert any(c.qi_category == "SUP_OS" for c in out)

    def test_ubuntu(self, lexicons) -> None:
        out = apply_rules("sous Ubuntu 22.04", "fr", lexicons)
        assert any(c.qi_category == "SUP_OS" for c in out)

    def test_macos_coarse(self, lexicons) -> None:
        out = apply_rules("j'utilise macOS", "fr", lexicons)
        c = next(c for c in out if c.qi_category == "SUP_OS")
        assert c.granularity.value == "COARSE"


class TestIncidentTime:
    def test_fr(self, lexicons) -> None:
        out = apply_rules("ça plante tous les matins vers 7h", "fr", lexicons)
        c = next(c for c in out if c.qi_category == "SUP_INCIDENT_TIME")
        assert c.meta["value_normalized"] == {"hour": 7}

    def test_en(self, lexicons) -> None:
        out = apply_rules("it crashes every morning around 7am", "en", lexicons)
        assert any(c.qi_category == "SUP_INCIDENT_TIME" for c in out)


class TestFamily:
    def test_lexicon_fr(self, lexicons) -> None:
        out = apply_rules("il est célibataire", "fr", lexicons)
        assert "GEN_FAMILY" in _categories(out)

    def test_of_fr(self, lexicons) -> None:
        out = apply_rules("il est père de jumeaux", "fr", lexicons)
        assert "GEN_FAMILY" in _categories(out)

    def test_en(self, lexicons) -> None:
        out = apply_rules("she is married", "en", lexicons)
        assert "GEN_FAMILY" in _categories(out)


class TestHealth:
    def test_fr_sensitivity(self, lexicons) -> None:
        out = apply_rules("il est en dépression", "fr", lexicons)
        c = next(c for c in out if c.qi_category == "GEN_HEALTH_STATE")
        assert c.meta["sensitivity"] == "HEALTH"

    def test_en(self, lexicons) -> None:
        out = apply_rules("she has a disability", "en", lexicons)
        assert "GEN_HEALTH_STATE" in _categories(out)


class TestOffsetsIntegrity:
    """Vérifie que text[start:end] == candidate.text pour toutes les règles."""

    def test_offsets_match_text(self, lexicons) -> None:
        text = (
            "J'ai moins de 30 ans, je suis doctorant à Lille et je cherche "
            "comment poser un arrêt maladie."
        )
        for c in apply_rules(text, "fr", lexicons):
            assert text[c.start : c.end] == c.text

"""Règles de détection de quasi-identifiants contextuels (FR/EN).

C'est ici que ce projet se distingue d'un détecteur de PII générique : âge,
niveau d'étude, profession, ancienneté, démarches RH, taille d'employeur,
version logicielle, OS, horaire d'incident, situation familiale, état de
santé. Chaque règle est une fonction pure ``text, language -> list[Candidate]``.

Les lexiques (métiers, diplômes, démarches administratives...) viennent de
``configs/detection/patterns.yaml`` (clé ``lexicons``), jamais du code : voir
``anonymisation.detect.patterns.load_patterns``.

Chaque règle produit, quand c'est possible, un ``value_normalized`` exploité
plus tard par le moteur de risque (SPEC-01 §6.2) : un âge devient un
intervalle ``[min, max]``, une version un ``semver``, etc.
"""

import re
from collections.abc import Callable
from typing import Any

from anonymisation.detect.base import Candidate
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Sensitivity,
    Stability,
)

RuleFn = Callable[[str, str, dict[str, list[str]]], list[Candidate]]


def _candidate(
    match_start: int,
    match_end: int,
    text: str,
    qi_category: str,
    identifier_type: IdentifierType,
    source: str,
    confidence: float,
    granularity: Granularity,
    stability: Stability,
    expression_mode: ExpressionMode = ExpressionMode.EXPLICIT,
    value_normalized: dict[str, Any] | None = None,
    sensitivity: Sensitivity | None = None,
) -> Candidate:
    meta: dict[str, Any] = {}
    if value_normalized is not None:
        meta["value_normalized"] = value_normalized
    if sensitivity is not None:
        meta["sensitivity"] = sensitivity.value
    return Candidate(
        start=match_start,
        end=match_end,
        text=text[match_start:match_end],
        qi_category=qi_category,
        identifier_type=identifier_type,
        source=source,
        confidence=confidence,
        granularity=granularity,
        stability=stability,
        expression_mode=expression_mode,
        meta=meta,
    )


def _lexicon_pattern(terms: list[str]) -> re.Pattern[str] | None:
    """Compile une alternative regex triée par longueur décroissante.

    Le tri évite qu'un terme court («é») masque un terme plus long qui le
    contient («infirmière») lors du matching par alternance.
    """
    if not terms:
        return None
    escaped = sorted((re.escape(t) for t in terms), key=len, reverse=True)
    return re.compile(rf"\b(?:{'|'.join(escaped)})\b", re.IGNORECASE | re.UNICODE)


# --------------------------------------------------------------------------- #
# GEN_AGE — âge exact et tranche d'âge
# --------------------------------------------------------------------------- #

_AGE_EXACT_FR = re.compile(r"\b(?:j'ai|jai)\s+(\d{1,3})\s*ans\b", re.IGNORECASE)
#: Négation : « X ans d'expérience » relève de HR_SENIORITY, pas de GEN_AGE.
_AGE_EXACT_FR_BARE = re.compile(
    r"\b(\d{1,3})\s*ans\b(?!\s*d['’]expérience)", re.IGNORECASE
)
_AGE_EXACT_EN = re.compile(r"\bI(?:'|’)?m\s+(\d{1,3})(?:\s*(?:years?\s*old|yo))?\b", re.IGNORECASE)
_AGE_UNDER_FR = re.compile(r"\bmoins de\s+(\d{1,3})\s*ans\b", re.IGNORECASE)
_AGE_OVER_FR = re.compile(r"\bplus de\s+(\d{1,3})\s*ans\b", re.IGNORECASE)
_AGE_UNDER_EN = re.compile(r"\bunder\s+(\d{1,3})\b", re.IGNORECASE)
_AGE_OVER_EN = re.compile(r"\b(?:over|above)\s+(\d{1,3})\b", re.IGNORECASE)
_AGE_DECADE_FR = re.compile(
    r"\bla\s+(vingtaine|trentaine|quarantaine|cinquantaine|soixantaine)\b", re.IGNORECASE
)
_DECADE_FR_TO_RANGE = {
    "vingtaine": (20, 29),
    "trentaine": (30, 39),
    "quarantaine": (40, 49),
    "cinquantaine": (50, 59),
    "soixantaine": (60, 69),
}
_AGE_DECADE_EN = re.compile(
    r"\bin (?:my|his|her|their) (twenties|thirties|forties|fifties|sixties)\b", re.IGNORECASE
)
_DECADE_EN_TO_RANGE = {
    "twenties": (20, 29),
    "thirties": (30, 39),
    "forties": (40, 49),
    "fifties": (50, 59),
    "sixties": (60, 69),
}


def rule_age(text: str, language: str, lexicons: dict[str, list[str]]) -> list[Candidate]:
    """Âge exact ou tranche d'âge, FR et EN."""
    out: list[Candidate] = []

    for pattern in (_AGE_UNDER_FR, _AGE_UNDER_EN):
        for m in pattern.finditer(text):
            age = int(m.group(1))
            out.append(_candidate(
                m.start(), m.end(), text, "GEN_AGE", IdentifierType.QUASI,
                "rule:age_under", 0.9, Granularity.RANGE, Stability.VOLATILE,
                value_normalized={"range": [0, age - 1]},
            ))

    for pattern in (_AGE_OVER_FR, _AGE_OVER_EN):
        for m in pattern.finditer(text):
            age = int(m.group(1))
            out.append(_candidate(
                m.start(), m.end(), text, "GEN_AGE", IdentifierType.QUASI,
                "rule:age_over", 0.9, Granularity.RANGE, Stability.VOLATILE,
                value_normalized={"range": [age + 1, 130]},
            ))

    for m in _AGE_EXACT_FR.finditer(text):
        age = int(m.group(1))
        out.append(_candidate(
            m.start(), m.end(), text, "GEN_AGE", IdentifierType.QUASI,
            "rule:age_exact_fr", 0.95, Granularity.EXACT, Stability.VOLATILE,
            value_normalized={"range": [age, age]},
        ))

    for m in _AGE_EXACT_EN.finditer(text):
        age = int(m.group(1))
        out.append(_candidate(
            m.start(), m.end(), text, "GEN_AGE", IdentifierType.QUASI,
            "rule:age_exact_en", 0.9, Granularity.EXACT, Stability.VOLATILE,
            value_normalized={"range": [age, age]},
        ))

    # Repli bas-rappel : « 28 ans » sans « j'ai » explicite.
    exact_spans = {(c.start, c.end) for c in out}
    for m in _AGE_EXACT_FR_BARE.finditer(text):
        if any(m.start() >= s and m.end() <= e for s, e in exact_spans):
            continue
        age = int(m.group(1))
        if not 0 < age < 130:
            continue
        out.append(_candidate(
            m.start(), m.end(), text, "GEN_AGE", IdentifierType.QUASI,
            "rule:age_bare_fr", 0.6, Granularity.EXACT, Stability.VOLATILE,
            value_normalized={"range": [age, age]},
        ))

    decade_pattern, decade_map = (
        (_AGE_DECADE_FR, _DECADE_FR_TO_RANGE)
        if language == "fr"
        else (_AGE_DECADE_EN, _DECADE_EN_TO_RANGE)
    )
    for m in decade_pattern.finditer(text):
        low, high = decade_map[m.group(1).lower()]
        out.append(_candidate(
            m.start(), m.end(), text, "GEN_AGE", IdentifierType.QUASI,
            "rule:age_decade", 0.8, Granularity.RANGE, Stability.VOLATILE,
            value_normalized={"range": [low, high]},
        ))

    return out


# --------------------------------------------------------------------------- #
# GEN_EDUCATION — niveau d'étude / diplôme (lexique)
# --------------------------------------------------------------------------- #


def rule_education(text: str, language: str, lexicons: dict[str, list[str]]) -> list[Candidate]:
    terms = lexicons.get("education_fr", []) + lexicons.get("education_en", [])
    pattern = _lexicon_pattern(terms)
    if pattern is None:
        return []
    out: list[Candidate] = []
    for m in pattern.finditer(text):
        out.append(_candidate(
            m.start(), m.end(), text, "GEN_EDUCATION", IdentifierType.QUASI,
            "rule:education_lexicon", 0.75, Granularity.COARSE, Stability.STABLE,
        ))
    return out


# --------------------------------------------------------------------------- #
# GEN_OCCUPATION — profession (lexique + motifs « je suis X » / « I work as X »)
# --------------------------------------------------------------------------- #

#: Un seul token de métier capturé (« doctorant », « développeuse ») : au-delà,
#: le risque de capturer un connecteur (« à », « de »...) l'emporte sur le
#: gain de rappel apporté par un second mot.
_OCC_WORD_FR = r"[a-zàâäéèêëïîôöùûüç]{3,}(?:[-'][a-zàâäéèêëïîôöùûüç]{2,})*"
_OCC_INTRO_FR = re.compile(
    rf"\bje\s+(?:suis|travaille\s+comme|travaille\s+en\s+tant\s+que|exerce\s+(?:le\s+métier|la\s+profession)\s+de)\s+"
    rf"({_OCC_WORD_FR})",
    re.IGNORECASE,
)
_OCC_WORD_EN = r"[a-z]{3,}(?:-[a-z]{2,})*"
_OCC_INTRO_EN = re.compile(
    rf"\bI\s+(?:am|work as|work like)\s+(?:an?\s+)?({_OCC_WORD_EN})",
    re.IGNORECASE,
)


def rule_occupation(text: str, language: str, lexicons: dict[str, list[str]]) -> list[Candidate]:
    out: list[Candidate] = []
    terms = lexicons.get("occupations_fr", []) + lexicons.get("occupations_en", [])
    lexicon_pattern = _lexicon_pattern(terms)
    if lexicon_pattern is not None:
        for m in lexicon_pattern.finditer(text):
            out.append(_candidate(
                m.start(), m.end(), text, "GEN_OCCUPATION", IdentifierType.QUASI,
                "rule:occupation_lexicon", 0.75, Granularity.COARSE, Stability.VOLATILE,
            ))

    intro_pattern = _OCC_INTRO_FR if language == "fr" else _OCC_INTRO_EN
    for m in intro_pattern.finditer(text):
        # On ne garde que le groupe capturé (le métier), pas « je suis ».
        start, end = m.start(1), m.end(1)
        out.append(_candidate(
            start, end, text, "GEN_OCCUPATION", IdentifierType.QUASI,
            "rule:occupation_intro", 0.55, Granularity.COARSE, Stability.VOLATILE,
        ))

    return out


# --------------------------------------------------------------------------- #
# HR_SENIORITY — ancienneté / expérience
# --------------------------------------------------------------------------- #

_SENIORITY_FR = re.compile(
    r"\b(\d{1,2})\s+ans?\s+d['’]expérience\b|\bdepuis\s+(\d{4})\b", re.IGNORECASE
)
_SENIORITY_EN = re.compile(
    r"\b(\d{1,2})\s+years?\s+of\s+experience\b|\bsince\s+(\d{4})\b", re.IGNORECASE
)


def rule_seniority(text: str, language: str, lexicons: dict[str, list[str]]) -> list[Candidate]:
    out: list[Candidate] = []
    pattern = _SENIORITY_FR if language == "fr" else _SENIORITY_EN
    for m in pattern.finditer(text):
        years_group, since_year_group = m.group(1), m.group(2)
        value_normalized: dict[str, Any]
        if years_group is not None:
            years = int(years_group)
            value_normalized = {"range": [years, years]}
        else:
            year = int(since_year_group)
            value_normalized = {"since_year": year}
        out.append(_candidate(
            m.start(), m.end(), text, "HR_SENIORITY", IdentifierType.QUASI,
            "rule:seniority", 0.85, Granularity.EXACT, Stability.VOLATILE,
            value_normalized=value_normalized,
        ))
    return out


# --------------------------------------------------------------------------- #
# HR_ADMIN_PROCEDURE — démarche administrative RH (lexique)
# --------------------------------------------------------------------------- #


def rule_hr_admin_procedure(
    text: str, language: str, lexicons: dict[str, list[str]]
) -> list[Candidate]:
    terms = lexicons.get("hr_admin_procedures_fr", []) + lexicons.get(
        "hr_admin_procedures_en", []
    )
    pattern = _lexicon_pattern(terms)
    if pattern is None:
        return []
    out: list[Candidate] = []
    for m in pattern.finditer(text):
        out.append(_candidate(
            m.start(), m.end(), text, "HR_ADMIN_PROCEDURE", IdentifierType.QUASI,
            "rule:hr_admin_procedure", 0.85, Granularity.COARSE, Stability.VOLATILE,
        ))
    return out


# --------------------------------------------------------------------------- #
# HR_EMPLOYER_SIZE — taille d'employeur
# --------------------------------------------------------------------------- #

_EMPLOYER_SIZE_FR = re.compile(
    r"\b(?:pme|entreprise|boîte|société|groupe)\s+de\s+(\d{1,6})\s*(?:salariés?|personnes|employés)\b",
    re.IGNORECASE,
)
_EMPLOYER_SIZE_EN = re.compile(
    r"\b(?:company|firm|business)\s+(?:of|with)\s+(\d{1,6})\s*(?:employees|people|staff)\b",
    re.IGNORECASE,
)


def rule_employer_size(
    text: str, language: str, lexicons: dict[str, list[str]]
) -> list[Candidate]:
    out: list[Candidate] = []
    pattern = _EMPLOYER_SIZE_FR if language == "fr" else _EMPLOYER_SIZE_EN
    for m in pattern.finditer(text):
        size = int(m.group(1))
        out.append(_candidate(
            m.start(), m.end(), text, "HR_EMPLOYER_SIZE", IdentifierType.QUASI,
            "rule:employer_size", 0.85, Granularity.RANGE, Stability.STABLE,
            value_normalized={"range": [size, size]},
        ))
    return out


# --------------------------------------------------------------------------- #
# SUP_VERSION — version logicielle
# --------------------------------------------------------------------------- #

_VERSION_SEMVER = re.compile(r"\bv?(\d+)\.(\d+)(?:\.(\d+))?\b")
_VERSION_SHORT = re.compile(r"\bv(\d{1,3})\b", re.IGNORECASE)


def rule_version(text: str, language: str, lexicons: dict[str, list[str]]) -> list[Candidate]:
    out: list[Candidate] = []
    for m in _VERSION_SEMVER.finditer(text):
        major, minor, patch = m.group(1), m.group(2), m.group(3)
        semver = f"{major}.{minor}.{patch}" if patch else f"{major}.{minor}"
        out.append(_candidate(
            m.start(), m.end(), text, "SUP_VERSION", IdentifierType.QUASI,
            "rule:version_semver", 0.7, Granularity.EXACT, Stability.VOLATILE,
            value_normalized={"semver": semver},
        ))
    semver_spans = {(c.start, c.end) for c in out}
    for m in _VERSION_SHORT.finditer(text):
        if any(m.start() >= s and m.end() <= e for s, e in semver_spans):
            continue
        out.append(_candidate(
            m.start(), m.end(), text, "SUP_VERSION", IdentifierType.QUASI,
            "rule:version_short", 0.5, Granularity.EXACT, Stability.VOLATILE,
            value_normalized={"semver": m.group(1)},
        ))
    return out


# --------------------------------------------------------------------------- #
# SUP_OS — système d'exploitation (lexique + version accolée)
# --------------------------------------------------------------------------- #

_OS_VERSION_SUFFIX = re.compile(r"[\s]*[\d][\d.]*", re.IGNORECASE)


def rule_os(text: str, language: str, lexicons: dict[str, list[str]]) -> list[Candidate]:
    terms = lexicons.get("os_names", [])
    pattern = _lexicon_pattern(terms)
    if pattern is None:
        return []
    out: list[Candidate] = []
    for m in pattern.finditer(text):
        start, end = m.start(), m.end()
        suffix = _OS_VERSION_SUFFIX.match(text[end:])
        if suffix:
            end += suffix.end()
        out.append(_candidate(
            start, end, text, "SUP_OS", IdentifierType.QUASI,
            "rule:os_lexicon", 0.8, Granularity.EXACT if suffix else Granularity.COARSE,
            Stability.VOLATILE,
        ))
    return out


# --------------------------------------------------------------------------- #
# SUP_INCIDENT_TIME — horaire ou périodicité de l'incident
# --------------------------------------------------------------------------- #

_INCIDENT_TIME_FR = re.compile(
    r"\b(?:tous les matins|tous les soirs|chaque matin|chaque jour|chaque nuit)\s*(?:vers\s+(\d{1,2})\s*h(?:\d{2})?)?\b",
    re.IGNORECASE,
)
_INCIDENT_TIME_EN = re.compile(
    r"\bevery\s+(?:morning|evening|day|night)\s*(?:around\s+(\d{1,2})\s*(?:am|pm)?)?\b",
    re.IGNORECASE,
)


def rule_incident_time(
    text: str, language: str, lexicons: dict[str, list[str]]
) -> list[Candidate]:
    out: list[Candidate] = []
    pattern = _INCIDENT_TIME_FR if language == "fr" else _INCIDENT_TIME_EN
    for m in pattern.finditer(text):
        value_normalized = {"hour": int(m.group(1))} if m.group(1) else None
        out.append(_candidate(
            m.start(), m.end(), text, "SUP_INCIDENT_TIME", IdentifierType.QUASI,
            "rule:incident_time", 0.7, Granularity.RANGE, Stability.VOLATILE,
            value_normalized=value_normalized,
        ))
    return out


# --------------------------------------------------------------------------- #
# GEN_FAMILY — situation familiale (lexique, avec motif « père de X »)
# --------------------------------------------------------------------------- #

_FAMILY_OF_FR = re.compile(r"\b(?:père|mère)\s+de\s+([a-zàâäéèêëïîôöùûüç' -]{2,30})", re.IGNORECASE)
_FAMILY_OF_EN = re.compile(r"\b(?:father|mother)\s+of\s+([a-z' -]{2,30})", re.IGNORECASE)


def rule_family(text: str, language: str, lexicons: dict[str, list[str]]) -> list[Candidate]:
    out: list[Candidate] = []
    terms = lexicons.get("family_terms_fr", []) + lexicons.get("family_terms_en", [])
    pattern = _lexicon_pattern(terms)
    if pattern is not None:
        for m in pattern.finditer(text):
            out.append(_candidate(
                m.start(), m.end(), text, "GEN_FAMILY", IdentifierType.QUASI,
                "rule:family_lexicon", 0.7, Granularity.COARSE, Stability.STABLE,
            ))

    of_pattern = _FAMILY_OF_FR if language == "fr" else _FAMILY_OF_EN
    for m in of_pattern.finditer(text):
        out.append(_candidate(
            m.start(), m.end(), text, "GEN_FAMILY", IdentifierType.QUASI,
            "rule:family_of", 0.75, Granularity.COARSE, Stability.STABLE,
        ))
    return out


# --------------------------------------------------------------------------- #
# GEN_HEALTH_STATE — état de santé (lexique), sensibilité HEALTH
# --------------------------------------------------------------------------- #


def rule_health(text: str, language: str, lexicons: dict[str, list[str]]) -> list[Candidate]:
    terms = lexicons.get("health_terms_fr", []) + lexicons.get("health_terms_en", [])
    pattern = _lexicon_pattern(terms)
    if pattern is None:
        return []
    out: list[Candidate] = []
    for m in pattern.finditer(text):
        out.append(_candidate(
            m.start(), m.end(), text, "GEN_HEALTH_STATE", IdentifierType.QUASI,
            "rule:health_lexicon", 0.8, Granularity.COARSE, Stability.VOLATILE,
            sensitivity=Sensitivity.HEALTH,
        ))
    return out


# --------------------------------------------------------------------------- #
# Registre public des règles — consommé par detect/__init__.py
# --------------------------------------------------------------------------- #

ALL_RULES: tuple[RuleFn, ...] = (
    rule_age,
    rule_education,
    rule_occupation,
    rule_seniority,
    rule_hr_admin_procedure,
    rule_employer_size,
    rule_version,
    rule_os,
    rule_incident_time,
    rule_family,
    rule_health,
)


def apply_rules(
    text: str,
    language: str,
    lexicons: dict[str, list[str]],
    rules: tuple[RuleFn, ...] = ALL_RULES,
) -> list[Candidate]:
    """Applique toutes les règles contextuelles et concatène les candidats."""
    out: list[Candidate] = []
    for rule in rules:
        out.extend(rule(text, language, lexicons))
    return out

"""Taxonomie unifiée des quasi-identifiants.

Implémentation normative de SPEC-01
(``documentation/specifications/SPEC-01-taxonomie-qi.md``).

Toute modification ici DOIT s'accompagner d'un incrément de ``TAXONOMY_VERSION``
et d'une entrée au journal de SPEC-01 : les ingestions précédentes deviennent
invalides (SPEC-04 §6).
"""

from __future__ import annotations

from enum import Enum
from typing import Final

TAXONOMY_VERSION: Final[str] = "1.0"


# --------------------------------------------------------------------------- #
# Axe 1 — rôle dans l'identification (SPEC-01 §3.1)
# --------------------------------------------------------------------------- #
class IdentifierType(str, Enum):
    DIRECT = "DIRECT"                    # identifie seul
    QUASI = "QUASI"                      # identifie en combinaison
    SENSITIVE_ONLY = "SENSITIVE_ONLY"    # sensible mais non identifiant
    IGNORED = "IGNORED"                  # hors périmètre, mappé explicitement


# --------------------------------------------------------------------------- #
# Axe 2 — mode d'expression (SPEC-01 §3.2) — axe de difficulté du projet
# --------------------------------------------------------------------------- #
class ExpressionMode(str, Enum):
    EXPLICIT = "EXPLICIT"                # « j'ai 28 ans »
    NON_STANDARD = "NON_STANDARD"        # « né l'année de la chute du Mur »
    IMPLICIT = "IMPLICIT"                # « j'ai soutenu ma thèse l'an dernier »


# --------------------------------------------------------------------------- #
# Axe 3 — sensibilité au sens RGPD art. 9 (SPEC-01 §3.3)
# Orthogonal à IdentifierType : ne participe pas au calcul de k.
# --------------------------------------------------------------------------- #
class Sensitivity(str, Enum):
    NONE = "NONE"
    HEALTH = "HEALTH"
    BELIEF = "BELIEF"
    UNION = "UNION"
    SEXLIFE = "SEXLIFE"
    BIOMETRIC = "BIOMETRIC"
    JUDICIAL = "JUDICIAL"


# --------------------------------------------------------------------------- #
# Métadonnées additionnelles (SPEC-01 §5)
# --------------------------------------------------------------------------- #
class Granularity(str, Enum):
    """Détermine si l'action GENERALIZE est encore disponible."""

    EXACT = "EXACT"      # « 28 ans »
    RANGE = "RANGE"      # « moins de 30 ans »
    COARSE = "COARSE"    # « jeune » — plus rien à généraliser


class Stability(str, Enum):
    STABLE = "STABLE"        # date de naissance
    VOLATILE = "VOLATILE"    # poste actuel — perd sa valeur identifiante


class Subject(str, Enum):
    """Sur qui porte le QI.

    THIRD_PARTY est souvent oublié : « mon manager, qui gère 40 personnes à
    Belfort » est un QI sur le manager, pas sur l'auteur.
    """

    SELF = "SELF"
    THIRD_PARTY = "THIRD_PARTY"


# --------------------------------------------------------------------------- #
# Axe 4 — catégories (SPEC-01 §4)
# --------------------------------------------------------------------------- #

DIRECT_CODES: Final[frozenset[str]] = frozenset({
    "DIR_NAME",
    "DIR_EMAIL",
    "DIR_PHONE",
    "DIR_ADDRESS",
    "DIR_ID_NUMBER",
    "DIR_ACCOUNT",
    "DIR_ONLINE_ID",
    "DIR_DEVICE_ID",
    "DIR_BIOMETRIC",
    "DIR_CASE_REF",
})

GENERIC_CODES: Final[frozenset[str]] = frozenset({
    "GEN_AGE",
    "GEN_GENDER",
    "GEN_GEO",
    "GEN_DATE_EVENT",
    "GEN_OCCUPATION",
    "GEN_EDUCATION",
    "GEN_AFFILIATION",
    "GEN_FAMILY",
    "GEN_HEALTH_STATE",
    "GEN_SOCIOECON",
    "GEN_ORIGIN_BELIEF",
    "GEN_LIFESTYLE",
    "GEN_PHYSICAL",
})

HR_CODES: Final[frozenset[str]] = frozenset({
    "HR_JOB_TITLE",
    "HR_SENIORITY",
    "HR_HIERARCHY",
    "HR_DEPARTMENT",
    "HR_CONTRACT",
    "HR_EMPLOYER_SIZE",
    "HR_WORKSITE",
    "HR_SALARY_BAND",
    "HR_CAREER_EVENT",
    "HR_ADMIN_PROCEDURE",
})

SUPPORT_CODES: Final[frozenset[str]] = frozenset({
    "SUP_PRODUCT",
    "SUP_VERSION",
    "SUP_OS",
    "SUP_DEVICE",
    "SUP_ENVIRONMENT",
    "SUP_ROLE",
    "SUP_INCIDENT_TIME",
    "SUP_TIMEZONE",
    "SUP_ORG",
    "SUP_SCALE",
})

FORUM_CODES: Final[frozenset[str]] = frozenset({
    "FOR_COMMUNITY",
    "FOR_RELATION",
    "FOR_ACTIVITY_PATTERN",
    "FOR_STYLE",          # hors périmètre v1, conservé pour l'annotation
})

SERVICE_CODES: Final[frozenset[str]] = frozenset({
    "OTHER_QI",           # > 1 % sur un dataset = taxonomie incomplète
    "IGNORED",
})

ALL_CODES: Final[frozenset[str]] = (
    DIRECT_CODES | GENERIC_CODES | HR_CODES | SUPPORT_CODES | FORUM_CODES | SERVICE_CODES
)

QUASI_CODES: Final[frozenset[str]] = GENERIC_CODES | HR_CODES | SUPPORT_CODES | FORUM_CODES

#: Codes hors périmètre du moteur de risque v1 (SPEC-06 §10).
OUT_OF_SCOPE_V1: Final[frozenset[str]] = frozenset({"FOR_STYLE", "FOR_RELATION"})


class UnknownQiCodeError(ValueError):
    """Code de catégorie absent de la taxonomie — erreur E-MAP-002."""


def validate_code(code: str) -> str:
    """Valide un code de catégorie.

    Aucune tolérance : un code inconnu fait échouer l'ingestion plutôt que de
    dégrader silencieusement en ``OTHER_QI`` (règle d'or, SPEC README §5).
    """
    if code not in ALL_CODES:
        raise UnknownQiCodeError(
            f"Code de catégorie inconnu : {code!r}. "
            f"Ajouter le code à SPEC-01 §4 et incrémenter TAXONOMY_VERSION, "
            f"ou corriger le label_map du dataset."
        )
    return code


def check_direct_exclusivity(identifier_type: IdentifierType, codes: tuple[str, ...]) -> None:
    """Invariant I-ANN-3 : un span DIRECT ne porte que des codes DIR_*."""
    if identifier_type is IdentifierType.DIRECT:
        offenders = [c for c in codes if c not in DIRECT_CODES]
        if offenders:
            raise ValueError(
                f"I-ANN-3 violé : identifier_type=DIRECT avec des codes non-DIR_* : {offenders}"
            )


#: Actions autorisées par type d'identifiant et granularité (SPEC-01 §8).
ALLOWED_ACTIONS: Final[dict[tuple[str, str | None], tuple[str, ...]]] = {
    ("DIRECT", None): ("SUPPRESS", "PSEUDONYMIZE"),
    ("QUASI", "EXACT"): ("GENERALIZE", "SUPPRESS"),
    ("QUASI", "RANGE"): ("GENERALIZE", "SUPPRESS"),
    ("QUASI", "COARSE"): ("SUPPRESS",),          # plus rien à généraliser
    ("SENSITIVE_ONLY", None): ("KEEP", "SUPPRESS"),
    ("IGNORED", None): ("KEEP",),
}

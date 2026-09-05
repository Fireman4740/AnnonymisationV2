"""Validateurs déterministes, stdlib pure.

Aucune dépendance externe (``phonenumbers``, ``schwifty`` etc. ne sont pas
disponibles dans cet environnement) : chaque validateur réimplémente
l'algorithme de contrôle nécessaire (Luhn, mod-97 IBAN, mod-97 NIR...).

Contrat commun : chaque fonction retourne un ``bool`` (ou un ``dict | None``
pour ``validate_date``) et **ne lève jamais** d'exception, y compris sur une
entrée malformée — c'est ce qui permet de les brancher sans filet sur des
sorties de regex potentiellement sales.

Ces validateurs sont ce qui distingue une détection utilisable d'un regex
naïf : un numéro à 16 chiffres qui échoue Luhn n'est pas une carte bancaire.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

# --------------------------------------------------------------------------- #
# Algorithmes de contrôle génériques
# --------------------------------------------------------------------------- #


def luhn(number: str) -> bool:
    """Algorithme de Luhn (cartes bancaires, SIREN, SIRET).

    >>> luhn("4539578763621486")
    True
    >>> luhn("1234567812345678")
    False
    """
    digits = re.sub(r"\D", "", number or "")
    if len(digits) < 2:
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        n = int(char)
        if index % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# --------------------------------------------------------------------------- #
# IBAN — mod-97 (norme ISO 7064)
# --------------------------------------------------------------------------- #

#: Longueur attendue par pays (couverture minimale demandée + quelques
#: voisins utiles). Une clé absente => on refuse plutôt que de deviner.
_IBAN_LENGTH_BY_COUNTRY: dict[str, int] = {
    "FR": 27,
    "DE": 22,
    "ES": 24,
    "IT": 27,
    "BE": 16,
    "NL": 18,
    "CH": 21,
    "GB": 22,
    "LU": 20,
    "PT": 25,
}


def validate_iban(value: str) -> bool:
    """Validation IBAN complète : longueur par pays + mod-97 réarrangé.

    >>> validate_iban("FR1420041010050500013M02606")
    True
    >>> validate_iban("FR1420041010050500013M02607")
    False
    """
    cleaned = re.sub(r"[\s-]", "", (value or "")).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", cleaned):
        return False
    country = cleaned[:2]
    expected_length = _IBAN_LENGTH_BY_COUNTRY.get(country)
    if expected_length is not None and len(cleaned) != expected_length:
        return False
    if expected_length is None and not (15 <= len(cleaned) <= 34):
        return False
    rearranged = cleaned[4:] + cleaned[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


def validate_bic(value: str) -> bool:
    """Validation syntaxique d'un BIC/SWIFT (8 ou 11 caractères).

    >>> validate_bic("BNPAFRPPXXX")
    True
    >>> validate_bic("TROPCOURT")
    False
    """
    cleaned = re.sub(r"\s", "", (value or "")).upper()
    return bool(re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?", cleaned))


# --------------------------------------------------------------------------- #
# NIR — numéro de sécurité sociale français, clé = 97 - (n mod 97)
# --------------------------------------------------------------------------- #


def validate_nir(value: str) -> bool:
    """Valide un NIR français (13 chiffres + clé sur 2 chiffres), Corse gérée.

    >>> validate_nir("1 84 03 78 006 084 11")
    True
    >>> validate_nir("1 84 03 78 006 084 12")
    False
    """
    cleaned = re.sub(r"[\s.]", "", (value or "")).upper()
    if len(cleaned) != 15:
        return False
    if not re.fullmatch(r"[127]\d{2}(0[1-9]|1[0-2])(2[AB]|\d{2})\d{6}\d{2}", cleaned):
        return False
    number_part = cleaned[:13].replace("2A", "19").replace("2B", "18")
    try:
        n = int(number_part)
    except ValueError:
        return False
    expected_key = 97 - (n % 97)
    key = int(cleaned[13:15])
    return expected_key == key


# --------------------------------------------------------------------------- #
# SIREN / SIRET — Luhn
# --------------------------------------------------------------------------- #


def validate_siren(value: str) -> bool:
    """SIREN : 9 chiffres, Luhn.

    >>> validate_siren("732829320")
    True
    >>> validate_siren("732829321")
    False
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 9:
        return False
    return luhn(digits)


def validate_siret(value: str) -> bool:
    """SIRET : 14 chiffres, Luhn.

    >>> validate_siret("73282932000074")
    True
    >>> validate_siret("73282932000075")
    False
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 14:
        return False
    return luhn(digits)


# --------------------------------------------------------------------------- #
# Email
# --------------------------------------------------------------------------- #

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)


def validate_email(value: str) -> bool:
    """Syntaxe raisonnable (pas de conformité RFC 5322 complète).

    >>> validate_email("jean.dupont@example.fr")
    True
    >>> validate_email("pas-un-email")
    False
    """
    value = (value or "").strip()
    if not value or len(value) > 254 or ".." in value:
        return False
    return bool(_EMAIL_RE.fullmatch(value))


# --------------------------------------------------------------------------- #
# Téléphone
# --------------------------------------------------------------------------- #


def validate_phone_fr(value: str) -> bool:
    """Numéro français : 10 chiffres commençant par 0, ou +33/0033 + 9 chiffres.

    >>> validate_phone_fr("06 12 34 56 78")
    True
    >>> validate_phone_fr("01 23")
    False
    """
    digits = re.sub(r"[^\d+]", "", value or "")
    if digits.startswith("+33"):
        digits = "0" + digits[3:]
    elif digits.startswith("0033"):
        digits = "0" + digits[4:]
    return bool(re.fullmatch(r"0[1-9]\d{8}", digits))


def validate_phone_generic(value: str) -> bool:
    """Heuristique internationale large : 7 à 15 chiffres (recommandation E.164).

    On privilégie le rappel (SPEC-07 §2) : on accepte un large éventail de
    longueurs plutôt que de rejeter un numéro international valide.

    >>> validate_phone_generic("+1 415 555 2671")
    True
    >>> validate_phone_generic("123")
    False
    """
    digits = re.sub(r"\D", "", value or "")
    return 7 <= len(digits) <= 15


# --------------------------------------------------------------------------- #
# Réseau / techniques
# --------------------------------------------------------------------------- #


def validate_ipv4(value: str) -> bool:
    """
    >>> validate_ipv4("192.168.0.1")
    True
    >>> validate_ipv4("999.1.1.1")
    False
    """
    parts = (value or "").strip().split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or len(part) > 3:
            return False
        if not 0 <= int(part) <= 255:
            return False
        if part != str(int(part)):  # rejette "01" par ex.
            return False
    return True


def validate_ipv6(value: str) -> bool:
    """
    >>> validate_ipv6("2001:db8::1")
    True
    >>> validate_ipv6("pas-une-ip")
    False
    """
    value = (value or "").strip()
    if value.count(":") < 2:
        return False
    try:
        import ipaddress

        ipaddress.IPv6Address(value)
        return True
    except ValueError:
        return False


def validate_mac(value: str) -> bool:
    """
    >>> validate_mac("00:1A:2B:3C:4D:5E")
    True
    >>> validate_mac("00:1A:2B")
    False
    """
    return bool(
        re.fullmatch(
            r"([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}",
            (value or "").strip(),
        )
    )


def validate_uuid(value: str) -> bool:
    """
    >>> validate_uuid("550e8400-e29b-41d4-a716-446655440000")
    True
    >>> validate_uuid("pas-un-uuid")
    False
    """
    return bool(
        re.fullmatch(
            r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
            r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}",
            (value or "").strip(),
        )
    )


# --------------------------------------------------------------------------- #
# Dates — normalisation FR/EN vers ISO 8601
# --------------------------------------------------------------------------- #

_MONTHS_FR = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}
_MONTHS_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DATE_NUMERIC_RE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})$")
_DATE_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DATE_FR_TEXT_RE = re.compile(
    r"^(\d{1,2})\s*(?:er)?\s+([A-Za-zéèûôâîçÉÈÛÔÂÎÇ]+)\s+(\d{4})$"
)
_DATE_EN_TEXT_RE = re.compile(
    r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$"
)


def validate_date(value: str, language: str = "fr") -> dict[str, str] | None:
    """Normalise une date FR/EN en ``{"iso": "YYYY-MM-DD"}``, ou ``None``.

    Ne lève jamais d'exception : une date incohérente (32 janvier, mois 13)
    retourne ``None``.

    >>> validate_date("28/02/2024", "fr")
    {'iso': '2024-02-28'}
    >>> validate_date("March 3, 2024", "en")
    {'iso': '2024-03-03'}
    >>> validate_date("n'importe quoi", "fr") is None
    True
    """
    value = (value or "").strip()
    if not value:
        return None

    match = _DATE_ISO_RE.match(value)
    if match:
        year, month, day = (int(x) for x in match.groups())
        return _safe_iso(year, month, day)

    match = _DATE_NUMERIC_RE.match(value)
    if match:
        day_text, month_text, year_text = (str(part) for part in match.groups())
        year_i = int(year_text) if len(year_text) == 4 else 2000 + int(year_text)
        return _safe_iso(year_i, int(month_text), int(day_text))

    match = _DATE_FR_TEXT_RE.match(value)
    if match:
        day_text, month_name, year_text = (str(part) for part in match.groups())
        month_fr = _MONTHS_FR.get(month_name.lower())
        if month_fr is None:
            return None
        return _safe_iso(int(year_text), month_fr, int(day_text))

    match = _DATE_EN_TEXT_RE.match(value)
    if match:
        month_name, day_text, year_text = (str(part) for part in match.groups())
        month_en = _MONTHS_EN.get(month_name.lower())
        if month_en is None:
            return None
        return _safe_iso(int(year_text), month_en, int(day_text))

    return None


def _safe_iso(year: int, month: int, day: int) -> dict[str, str] | None:
    try:
        return {"iso": date(year, month, day).isoformat()}
    except ValueError:
        return None


#: Registre public utilisé par ``patterns.py`` pour résoudre le champ
#: ``validator`` du YAML vers une fonction réelle. Toute entrée YAML citant
#: un nom absent d'ici doit faire échouer le chargement (pas d'ignorance
#: silencieuse).
VALIDATORS: dict[str, Callable[[str], Any]] = {
    "luhn": luhn,
    "validate_iban": validate_iban,
    "validate_bic": validate_bic,
    "validate_nir": validate_nir,
    "validate_siren": validate_siren,
    "validate_siret": validate_siret,
    "validate_email": validate_email,
    "validate_phone_fr": validate_phone_fr,
    "validate_phone_generic": validate_phone_generic,
    "validate_ipv4": validate_ipv4,
    "validate_ipv6": validate_ipv6,
    "validate_mac": validate_mac,
    "validate_uuid": validate_uuid,
    "validate_date": validate_date,
}

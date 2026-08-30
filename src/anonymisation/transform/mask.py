"""Masquage spécialisé par catégorie de QI.

**Choix de conception assumé** : le masquage *partiel* (``mode="partial"``)
FUIT de l'information par construction — c'est même son but (préserver de
l'utilité). Il ne doit jamais être le comportement par défaut d'un pipeline
d'anonymisation : c'est pourquoi ``mode`` vaut ``"full"`` par défaut dans
toutes les fonctions de ce module. Choisir ``"partial"`` est un arbitrage
utilité/confidentialité explicite, qui doit être documenté dans la politique
qui l'active (voir ``configs/policy/policies.yaml``), jamais un défaut
implicite.

Repris et étendu de l'ancien dépôt
(``F:\\IA\\Anonymisation\\pipegraph\\src\\nodes\\anonymisation\\anonymization_node.py``,
fonctions ``_mask_email``/``_mask_phone``/``_mask_iban``).
"""

from __future__ import annotations

import re
from typing import Final

#: Modes de masquage supportés.
FULL: Final[str] = "full"
PARTIAL: Final[str] = "partial"

_VALID_MODES: Final[frozenset[str]] = frozenset({FULL, PARTIAL})


class UnknownMaskModeError(ValueError):
    """Mode de masquage inconnu — pas de dégradation silencieuse vers ``full``."""


def _check_mode(mode: str) -> None:
    if mode not in _VALID_MODES:
        raise UnknownMaskModeError(
            f"Mode de masquage inconnu : {mode!r}. Modes valides : {sorted(_VALID_MODES)}."
        )


def _mask_email(value: str, mode: str) -> str:
    if mode == FULL:
        return "[EMAIL]"
    if "@" not in value:
        return "[EMAIL]"
    local, domain = value.split("@", 1)
    masked_local = (local[0] + "*" * max(1, len(local) - 1)) if local else "*"
    if "." in domain:
        dom_name, _, tld = domain.rpartition(".")
        masked_domain = (dom_name[0] + "*" * max(1, len(dom_name) - 1)) if dom_name else "*"
        return f"{masked_local}@{masked_domain}.{tld}"
    return f"{masked_local}@{domain}"


def _mask_phone(value: str, mode: str) -> str:
    if mode == FULL:
        return "[PHONE]"
    digits = re.sub(r"\D", "", value)
    if len(digits) < 6:
        return "[PHONE]"
    # Conserve l'indicatif pays si présent (préfixe "00" ou "+"), sinon les
    # deux premiers chiffres (indicatif régional / opérateur en France).
    return digits[:2] + " ** ** ** " + digits[-2:]


def _mask_iban(value: str, mode: str) -> str:
    if mode == FULL:
        return "[IBAN]"
    clean = value.replace(" ", "")
    if len(clean) < 4:
        return "[IBAN]"
    # Conserve le code pays ISO (2 lettres) + clé de contrôle (2 chiffres).
    country = clean[:4]
    remainder_blocks = (len(clean) - 4 + 3) // 4
    return country + " " + " ".join("****" for _ in range(remainder_blocks))


def mask(value: str, qi_category: str, mode: str = FULL) -> str:
    """Masque ``value`` selon une stratégie adaptée à ``qi_category``.

    ``mode="full"`` (défaut) remplace toujours par un jeton générique
    ``[<CATEGORIE>]`` sans aucune fuite. ``mode="partial"`` applique un
    masquage spécialisé qui conserve une partie de la structure (utile pour
    des jeux de données synthétiques où l'on veut mesurer l'utilité perdue),
    au prix d'une fuite d'information documentée.
    """
    _check_mode(mode)

    upper = qi_category.upper()
    if mode == FULL:
        return f"[{qi_category}]"

    if "EMAIL" in upper:
        return _mask_email(value, mode)
    if any(token in upper for token in ("PHONE", "TEL", "MOBILE")):
        return _mask_phone(value, mode)
    if "IBAN" in upper or "ACCOUNT" in upper:
        return _mask_iban(value, mode)

    # Défaut conservateur pour toute catégorie sans masquage spécialisé :
    # on ne devine pas une stratégie, on retombe sur le plein masquage.
    return f"[{qi_category}]"

"""Pseudonymisation stable par HMAC-SHA256.

Repris et durci de l'ancien dépôt (``F:\\IA\\Anonymisation\\pipegraph\\src\\utils\\pseudo.py``),
dont l'audit v1 recommande explicitement de conserver le principe : un
placeholder déterministe, dérivé d'un secret jamais exposé, cohérent entre
documents d'un même scope mais non « linkable » d'un scope à l'autre.

Propriétés garanties (voir tests) :

* **Stabilité** — la même surface, dans le même scope, produit toujours le
  même placeholder (cohérence inter-documents, utile p. ex. pour remplacer
  toutes les mentions d'une même personne dans un thread).
* **Isolation de scope** — deux scopes différents (deux clients, deux corpus)
  produisent des placeholders différents pour la même surface, ce qui empêche
  la ré-identification par recoupement inter-scopes (linkability).
* **Normalisation de surface** — la casse et les espaces multiples n'influent
  pas sur le placeholder : « Jean DUPONT », « jean dupont » et « Jean  Dupont »
  sont la même entité du point de vue du mapper.
* **Non-inversibilité** — HMAC-SHA256 est une fonction à sens unique : le
  secret n'est jamais retrouvable depuis un placeholder, et retrouver la
  surface d'origine à partir du seul placeholder est calculatoirement
  infaisable sans le secret (résistance à la deuxième préimage de SHA-256).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import unicodedata
from typing import Final

#: Longueur par défaut (en caractères base32) du fragment de hash affiché.
DEFAULT_LENGTH: Final[int] = 6

_WHITESPACE_RE = re.compile(r"\s+")


def normalise_surface(surface: str) -> str:
    """Normalise une surface pour que des variantes triviales soient
    considérées comme la même entité (casse, espaces multiples, accents
    conservés car porteurs de sens en français).
    """
    collapsed = _WHITESPACE_RE.sub(" ", surface.strip())
    # Normalisation Unicode NFC pour éviter que deux encodages visuellement
    # identiques (ex. é composé vs décomposé) ne produisent des placeholders
    # différents.
    return unicodedata.normalize("NFC", collapsed).casefold()


class PseudoMapper:
    """Génère des placeholders pseudonymes stables et non-inversibles.

    Le ``secret`` DOIT rester confidentiel (jamais loggé, jamais dans le
    texte anonymisé). Le ``scope`` isole les mappings entre contextes
    indépendants (ex. deux clients, deux corpus) : changer de scope change
    tous les placeholders, même pour des surfaces identiques.
    """

    def __init__(self, secret: bytes, scope: str = "default", length: int = DEFAULT_LENGTH) -> None:
        if not secret:
            raise ValueError("secret ne peut pas être vide : la pseudonymisation serait devinable")
        if length < 4:
            raise ValueError("length doit être >= 4 pour limiter le risque de collision")
        self._secret = secret
        self._scope = scope
        self._length = length
        self._mapping: dict[str, str] = {}

    def _digest(self, qi_category: str, surface_normalisee: str) -> str:
        message = f"{self._scope}|{qi_category}|{surface_normalisee}".encode()
        raw = hmac.new(self._secret, message, hashlib.sha256).digest()
        # Base32 : alphabet lisible (pas de confusion 0/O, 1/I), tronqué à
        # ``length`` caractères. Suffisant pour l'explicabilité, pas pour
        # l'unicité cryptographique absolue (non requis ici : collision entre
        # deux surfaces différentes ne casse pas la confidentialité, elle
        # dégrade seulement légèrement l'utilité).
        return base64.b32encode(raw).decode("ascii").rstrip("=")[: self._length]

    def placeholder(self, qi_category: str, surface: str) -> str:
        """Retourne un placeholder du type ``[PER_A3F1K2]`` pour ``surface``.

        Le mapping (surface normalisée -> placeholder) est mémorisé pour
        permettre l'export via :meth:`mapping`.
        """
        surface_normalisee = normalise_surface(surface)
        fragment = self._digest(qi_category, surface_normalisee)
        placeholder = f"[{qi_category}_{fragment}]"
        self._mapping[surface] = placeholder
        return placeholder

    def mapping(self) -> dict[str, str]:
        """Retourne une copie du mapping (surface originale -> placeholder)
        constitué par les appels précédents à :meth:`placeholder`.

        Ce mapping ne permet PAS de retrouver le secret : il n'expose que des
        correspondances déjà produites, utiles pour l'audit ou pour
        remplacer manuellement d'autres occurrences non détectées.
        """
        return dict(self._mapping)

"""Ancre S1 : ne fait rien.

Borne **basse** de la protection, borne **haute** de l'utilité. Ce n'est pas un
gadget : sans elle, aucun chiffre de protection n'a d'échelle — on ne sait pas
si un CPR de 0,61 est bon.

Boîte noire assumée : ne déclare aucune capacité. Démontre au passage que la
branche « boîte noire » du contrat est réelle et évaluable de bout en bout
(protection et utilité restent mesurées, seul l'axe A sort en `UNAVAILABLE`).
"""

from __future__ import annotations

from typing import ClassVar

from anonymisation.schema.models import Document
from anonymisation.systems.base import TextRewriteSystem
from anonymisation.systems.registry import register_system


@register_system
class PassthroughSystem(TextRewriteSystem):
    """Renvoie le texte inchangé — borne basse de protection, haute d'utilité."""

    system_id: ClassVar[str] = "passthrough-v1"
    system_version: ClassVar[str] = "1"
    aliases: ClassVar[tuple[str, ...]] = ("passthrough", "noop")
    summary: ClassVar[str] = "Ne modifie rien : ancre S1 (fuite maximale, utilité maximale)."

    def anonymize_text(self, doc: Document) -> str:
        return doc.text


__all__ = ["PassthroughSystem"]

"""Les deux systèmes qui bornent les axes de l'évaluation.

Ce ne sont pas des gadgets. Sans eux, aucun chiffre de protection ni
d'utilité n'a d'échelle : on ne sait pas si un CPR de 0,61 est bon.

* :class:`PassthroughSystem` — ne fait rien. Borne **basse** de la protection,
  borne **haute** de l'utilité. C'est l'ancre du test de sanité S1.
* :class:`RedactAllSystem` — supprime tout le texte. Borne **haute** de la
  protection, borne **basse** de l'utilité. Ancre S2, et surtout **contrôle de
  la métrique elle-même** : si un système bat ``redact-all`` sur la protection,
  c'est la métrique qui est fausse, pas le système qui est excellent.

Les deux sont des boîtes noires : ils ne déclarent aucune capacité. Ils
démontrent donc au passage que la branche « boîte noire » du contrat est
réelle et évaluable de bout en bout.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

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


class _RedactAllParams(BaseModel):
    """Paramètres de ``redact-all``.

    ``replacement`` est **requis, sans défaut** : la chaîne de remplacement
    change radicalement l'utilité mesurée (une chaîne vide donne une rétention
    nulle, un placeholder non). Laisser un défaut implicite reviendrait à
    choisir en silence un point de la courbe privacy-utility.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    replacement: str


@register_system
class RedactAllSystem(TextRewriteSystem):
    """Remplace tout le document — borne haute de protection, nulle d'utilité."""

    system_id: ClassVar[str] = "redact-all-v1"
    system_version: ClassVar[str] = "1"
    aliases: ClassVar[tuple[str, ...]] = ("redact-all", "suppress-all")
    summary: ClassVar[str] = (
        "Supprime tout le texte : ancre S2 (fuite nulle, utilité effondrée). "
        "Aucun système ne doit la dépasser en protection — sinon la métrique est fausse."
    )
    Params: ClassVar[type[BaseModel] | None] = _RedactAllParams

    def anonymize_text(self, doc: Document) -> str:
        return str(self._params["replacement"])

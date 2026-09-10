"""Ancre S2 : supprime tout le texte.

Borne **haute** de la protection, borne **basse** de l'utilité — et surtout
**contrôle de la métrique elle-même** : si un système bat `redact-all` sur la
protection, c'est la métrique qui est fausse, pas le système qui est excellent.

Boîte noire assumée : ne déclare aucune capacité (voir la note de
`pipelines/passthrough/system.py`).
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from anonymisation.schema.models import Document
from anonymisation.systems.base import SystemConfig, TextRewriteSystem
from anonymisation.systems.registry import register_system


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

    @classmethod
    def contract_config(cls) -> SystemConfig:
        # `replacement` n'a volontairement pas de défaut : le contrat de test
        # doit donc fournir une valeur explicite.
        return SystemConfig(params={"replacement": ""})

    def anonymize_text(self, doc: Document) -> str:
        return str(self._params["replacement"])


__all__ = ["RedactAllSystem"]

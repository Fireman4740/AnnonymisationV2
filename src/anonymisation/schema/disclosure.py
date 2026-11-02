"""Configuration des politiques de divulgation et des tables d'attributs.

Module sans dépendance au pipeline : le scoring (C5) doit pouvoir lire les
tables d'attributs sans importer ``detect``, ``llm`` ni ``systems``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class DisclosureError(ValueError):
    """Politique de divulgation absente, incomplète ou inapplicable."""


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PolicySpec(_Strict):
    label: str = Field(min_length=1)
    source: Literal["document", "static"]
    attribute_table: str = Field(min_length=1)
    neutral_action: Literal["hide", "keep"]
    hide: tuple[str, ...] | None = None
    keep: tuple[str, ...] | None = None
    neutral: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def lists_match_source(self):
        lists = (self.hide, self.keep, self.neutral)
        if self.source == "static" and any(x is None for x in lists):
            raise ValueError("politique statique : hide, keep et neutral sont requis")
        if self.source == "document" and any(x is not None for x in lists):
            raise ValueError("politique document : les listes viennent du document, pas du YAML")
        return self


class DisclosureConfig(_Strict):
    default_adapter_table: str
    attribute_tables: dict[str, dict[str, tuple[str, ...]]]
    policies: dict[str, PolicySpec]

    @model_validator(mode="after")
    def consistent(self):
        for name, table in self.attribute_tables.items():
            seen: dict[str, str] = {}
            for attribute, codes in table.items():
                for code in codes:
                    if code in seen:
                        raise ValueError(f"table {name!r} : {code!r} rattaché à {seen[code]!r} et {attribute!r}")
                    seen[code] = attribute
        attributes = {frozenset(t) for t in self.attribute_tables.values()}
        if len(attributes) != 1:
            raise ValueError("toutes les tables doivent couvrir les mêmes attributs")
        referenced = {self.default_adapter_table, *(p.attribute_table for p in self.policies.values())}
        if referenced - set(self.attribute_tables):
            raise ValueError(f"table(s) inconnue(s) : {sorted(referenced - set(self.attribute_tables))}")
        return self

    def category_to_attribute(self, table: str) -> dict[str, str]:
        if table not in self.attribute_tables:
            raise DisclosureError(f"table d'attributs {table!r} inconnue ; disponibles : {sorted(self.attribute_tables)}")
        return {code: a for a, codes in self.attribute_tables[table].items() for code in codes}


def load_config(path: Path) -> DisclosureConfig:
    try:
        return DisclosureConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise DisclosureError(f"{path} : configuration de divulgation invalide — {exc}") from exc

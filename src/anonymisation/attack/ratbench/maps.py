"""Tables code ↔ libellé officielles de RAT-Bench (PUMS 2010 ré-encodé).

Les tables sont produites par ``scripts/fetch_ratbench.py`` dans
``RAT-Bench/cache/maps/<colonne>.json`` sous forme de paires ``[code, libellé]``
dans l'ordre d'insertion du pickle officiel — ordre qui fixe l'énumération des
options dans le prompt de l'attaquant.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Colonnes PUMS du pipeline officiel (``pums_col_to_str_dict``), dans l'ordre
#: officiel : il fixe l'ordre des colonnes passées à CorrectMatch.
PUMS_COLUMNS: tuple[str, ...] = (
    "AGEP", "RAC2P", "CIT", "SCHL", "POWSP", "JWDP", "OCCP", "COW", "MAR", "MIL",
    "SEX", "JWTRNS", "ESR", "ST", "DRIVESP", "DOB", "DOB-Day", "DOB-Month",
    "DOB-Year", "zip code",
)
#: Libellés lisibles utilisés dans le prompt (``pums_col_to_str_dict``).
COLUMN_LABELS: dict[str, str] = {
    "SEX": "sex",
    "RAC2P": "race",
    "CIT": "citizenship status",
    "SCHL": "education level",
    "ESR": "employment status",
    "ST": "state of residence",
    "DOB": "date of birth",
    "MAR": "marital status",
    "OCCP": "occupation",
}
LABEL_TO_COLUMN: dict[str, str] = {v: k for k, v in COLUMN_LABELS.items()}
#: Colonnes dont le prompt énumère les options (``pums_cols`` officiel).
OPTION_COLUMNS: frozenset[str] = frozenset(COLUMN_LABELS)
_MAP_FILES = (
    "CIT", "DOB", "DOB-Day", "DOB-Month", "DOB-Year", "ESR", "MAR", "OCCP",
    "OCCP_type", "PUMA_FULL", "RAC2P", "SCHL", "SEX", "ST", "zip_to_puma",
)


class RatBenchMapsError(ValueError):
    """Table absente ou valeur introuvable dans une table officielle."""


@dataclass(frozen=True)
class RatBenchMaps:
    """Tables officielles chargées : ``pairs[col]`` = paires (code, libellé)."""

    pairs: dict[str, tuple[tuple[Any, Any], ...]]
    source: str

    @classmethod
    def load(cls, maps_dir: Path) -> RatBenchMaps:
        loaded: dict[str, tuple[tuple[Any, Any], ...]] = {}
        sources = set()
        for name in _MAP_FILES:
            path = Path(maps_dir) / f"{name}.json"
            if not path.is_file():
                raise RatBenchMapsError(
                    f"table officielle absente : {path} — lancer scripts/fetch_ratbench.py"
                )
            payload = json.loads(path.read_text(encoding="utf-8"))
            loaded[name] = tuple((k, v) for k, v in payload["pairs"])
            sources.add(payload["source"])
        if len(sources) != 1:
            raise RatBenchMapsError(f"tables issues de sources différentes : {sorted(sources)}")
        return cls(pairs=loaded, source=sources.pop())

    def labels(self, column: str) -> list[Any]:
        """Libellés dans l'ordre officiel (options du prompt)."""
        return [label for _, label in self.pairs[column]]

    def inverse(self, column: str) -> dict[Any, Any]:
        """libellé → code. Les doublons de libellé gardent le DERNIER code,
        comme la construction ``inverse_map[v] = k`` du code officiel."""
        out: dict[Any, Any] = {}
        for code, label in self.pairs[column]:
            out[label] = code
        return out

    def lookup(self, column: str) -> dict[Any, Any]:
        """code → libellé."""
        return dict(self.pairs[column])


__all__ = [
    "COLUMN_LABELS",
    "LABEL_TO_COLUMN",
    "OPTION_COLUMNS",
    "PUMS_COLUMNS",
    "RatBenchMaps",
    "RatBenchMapsError",
]

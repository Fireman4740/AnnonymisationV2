"""Risque de ré-identification RAT-Bench : encodage PUMS + CorrectMatch.

Portage de ``process_col`` et ``compute_reid_risk`` (``pii_benchmark/uniqueness.py``).
Seuls les attributs indirects **correctement devinés** entrent dans le modèle :
c'est la connaissance effective de l'attaquant après lecture du texte anonymisé.

CorrectMatch (Rocher, Hendrickx & de Montjoye, Nature Communications 2019)
ajuste une copule gaussienne sur l'échantillon PUMS puis estime, pour un
enregistrement, la probabilité qu'une ré-identification par correspondance
soit correcte dans une population de taille N. L'estimateur est stochastique
(≈ 1 % d'écart entre appels, même graine Julia fixée) : comme le code officiel,
on moyenne 10 tirages, et la valeur obtenue est **figée** dans
``attacks.jsonl`` pour que le scoring reste reproductible bit à bit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anonymisation.attack.ratbench import CORRECTMATCH_REPEATS, POPULATION_N
from anonymisation.attack.ratbench.maps import PUMS_COLUMNS, RatBenchMaps, RatBenchMapsError

#: Libellés OCCP ambigus (deux codes pour un même libellé) : le code officiel
#: les force à ces codes-là. Conservé tel quel.
_OCCP_OVERRIDES = {
    "OFF-FIRST": "25",
    "SAL-FIRST": "32",
    "RPR-FIRST": "117",
    "SAL-DOOR": "158",
    "FLIGHT ATTENDANTS": "260",
    "CON-MISCELLANEOUS EXTRACTION WORKERS, INCLUDING ROOF BOLTERS AND HELPERS": "346",
    "CON-EARTH DRILLERS, EXCEPT OIL AND GAS": "411",
}
_DATE_PARTS = ("DOB-Day", "DOB-Month", "DOB-Year")


class CorrectMatchUnavailable(RuntimeError):
    """CorrectMatch (Julia) n'est pas installé : le risque n'est pas calculable."""


def _correct(flags: Any) -> bool:
    return bool(flags) and flags[0] == 1


def encode_correct_attributes(
    correctness: Mapping[str, Sequence[int]],
    indirect: Mapping[str, Any],
    maps: RatBenchMaps,
) -> dict[str, int]:
    """Codes PUMS des attributs indirects correctement devinés (``process_col``).

    Retourne ``{colonne_parquet: code}``. Les parties de date ne comptent que si
    la date complète n'a PAS été devinée (sinon double comptage, comme
    l'officiel). Une valeur gold absente des tables officielles lève : elle
    signalerait une désynchronisation entre benchmark et tables, pas un
    attribut à ignorer.
    """
    record: dict[str, int] = {}
    for column in correctness:
        if column not in PUMS_COLUMNS or not _correct(correctness[column]):
            continue
        truth = indirect.get(column)
        if column in _DATE_PARTS:
            if _correct(correctness.get("DOB", ())):
                continue
            day, month, year = str(indirect["DOB"]).split(" ")
            raw = {"DOB-Day": int(day), "DOB-Month": month, "DOB-Year": int(year)}[column]
            record[column] = _code(maps, column, raw)
        elif column == "zip code":
            zip_to_puma = maps.lookup("zip_to_puma")
            puma_full = zip_to_puma.get(int(str(truth)))
            if puma_full is None:
                raise RatBenchMapsError(f"code postal gold {truth!r} absent de zip_to_puma")
            record["PUMA_FULL"] = _code(maps, "PUMA_FULL", puma_full)
        elif column == "OCCP":
            record[column] = _occupation_code(maps, str(truth))
        elif column == "AGEP":
            record[column] = int(truth)
        else:
            record[column] = _code(maps, column, truth)
    return record


def _code(maps: RatBenchMaps, column: str, label: Any) -> int:
    inverse = maps.inverse(column)
    if label not in inverse:
        raise RatBenchMapsError(f"{column} : valeur gold {label!r} absente des tables officielles")
    return int(inverse[label])


def _occupation_code(maps: RatBenchMaps, truth: str) -> int:
    dloc = truth.find("DESCRIPTION")
    occ_type = truth[:dloc].split(":")[-1].strip().strip(",")
    occ_desc = truth[dloc:].split(":")[-1].strip()
    if occ_type == "N/A":
        return 1
    type_to_code = {label: code for code, label in maps.pairs["OCCP_type"]}
    if occ_type not in type_to_code:
        raise RatBenchMapsError(f"OCCP : type gold {occ_type!r} absent de OCCP_type")
    label = f"{type_to_code[occ_type]}-{occ_desc}"
    if label in _OCCP_OVERRIDES:
        return int(_OCCP_OVERRIDES[label])
    return _code(maps, "OCCP", label)


def _ordered(record: Mapping[str, int]) -> tuple[list[str], list[int]]:
    """Ordre des colonnes de ``pums_cols`` (zip code → PUMA_FULL), comme l'officiel."""
    columns: list[str] = []
    values: list[int] = []
    for column in PUMS_COLUMNS:
        key = "PUMA_FULL" if column == "zip code" else column
        if key in record:
            columns.append(key)
            values.append(record[key])
    return columns, values


@dataclass(frozen=True)
class RiskEstimate:
    """Estimation figée : ``None`` = tous les tirages NaN (``np.mean([])`` officiel)."""

    correctness: float | None
    uniqueness: float | None
    columns: tuple[str, ...]
    record: tuple[tuple[str, int], ...] = ()
    correctness_draws: tuple[float | None, ...] = ()


def nan_mean(values: Sequence[float]) -> float | None:
    """``np.mean([v for v in values if not np.isnan(v)])`` du code officiel.

    Seuls les NaN sont écartés ; une liste vide donne NaN chez l'officiel,
    rendu ici par ``None`` (JSON valide) — jamais remplacé par 0. Une valeur
    infinie, impossible pour une probabilité, lève plutôt que d'être figée.
    """
    import math

    kept = [float(v) for v in values if not math.isnan(float(v))]
    if any(math.isinf(v) for v in kept):
        raise CorrectMatchUnavailable(f"estimation CorrectMatch infinie : {kept}")
    return sum(kept) / len(kept) if kept else None


class CorrectMatchRisk:
    """Ajuste un modèle CorrectMatch par ensemble de colonnes (mis en cache)."""

    def __init__(self, population_parquet: Path, *, population_n: int = POPULATION_N) -> None:
        try:
            import correctmatch  # noqa: F401
            import pandas as pd
        except ImportError as exc:
            raise CorrectMatchUnavailable(
                "CorrectMatch requis : `uv pip install \"git+https://github.com/imperial-aisp/"
                "pycorrectmatch\" juliacall pandas pyarrow` (Julia est installé au premier appel)."
            ) from exc
        self._frame = pd.read_parquet(population_parquet)
        self._n = population_n
        self._models: dict[tuple[str, ...], Any] = {}
        self._dense: dict[str, dict[int, int]] = {}

    def _encoder(self, column: str) -> dict[int, int]:
        """Code PUMS → rang dense 1..K de la colonne.

        CorrectMatch indexe ses marges catégorielles par 1..K : un code au-delà
        du nombre de valeurs distinctes fait échouer Julia
        (``pdf(Categorical, nothing)``). La colonne DOB de l'échantillon officiel
        a des trous (34 739 valeurs pour des codes jusqu'à 34 847). Le dépôt
        officiel applique ce même ré-encodage à ses données serbes ; la
        bijection ne change ni les marges ni la copule.
        """
        if column not in self._dense:
            values = sorted(int(v) for v in self._frame[column].unique())
            self._dense[column] = {v: i + 1 for i, v in enumerate(values)}
        return self._dense[column]

    def estimate(self, record: Mapping[str, int]) -> RiskEstimate:
        import correctmatch
        import numpy as np

        columns, values = _ordered(record)
        if not columns:
            # Officiel : « No cols to fit » → correctness = uniqueness = 0.0.
            return RiskEstimate(0.0, 0.0, ())
        missing = [c for c in columns if c not in self._frame.columns]
        if missing:
            raise CorrectMatchUnavailable(f"colonnes absentes de la population PUMS : {missing}")
        key = tuple(columns)
        encoders = [self._encoder(c) for c in key]
        dense_values = []
        for column, value, encoder in zip(key, values, encoders, strict=True):
            if value not in encoder:
                # Valeur gold absente de la population : CorrectMatch n'a pas
                # de masse pour elle. Lever plutôt que de deviner un risque.
                raise CorrectMatchUnavailable(
                    f"{column} : code {value} absent de l'échantillon PUMS — risque non défini"
                )
            dense_values.append(encoder[value])
        if key not in self._models:
            dense = self._frame[list(key)].apply(
                lambda col: col.map(self._encoder(col.name))
            )
            self._models[key] = correctmatch.fit_model(dense.to_numpy())
        model = self._models[key]
        array = np.array(dense_values)
        # Tirages entrelacés correctness/uniqueness, comme `compute_correctness`
        # officiel : l'ordre des appels fixe la séquence aléatoire de Julia.
        corr: list[float] = []
        uniq: list[float] = []
        for _ in range(CORRECTMATCH_REPEATS):
            corr.append(correctmatch.individual_correctness(model, array, n=self._n))
            uniq.append(correctmatch.individual_uniqueness(model, array, n=self._n))
        return RiskEstimate(
            correctness=nan_mean(corr),
            uniqueness=nan_mean(uniq),
            columns=key,
            record=tuple(zip(key, values, strict=True)),
            correctness_draws=tuple(
                None if float(c) != float(c) else float(c) for c in corr
            ),
        )


__all__ = [
    "nan_mean",
    "CorrectMatchRisk",
    "CorrectMatchUnavailable",
    "RiskEstimate",
    "encode_correct_attributes",
]

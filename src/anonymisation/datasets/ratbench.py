"""Adaptateur pour le jeu de données RAT-Bench avec calcul de population PUMS.

Normalise `english.jsonl` (300 exemples) :
- Document : `text`, `doc_id="ratbench:<id>"`, métadonnées (difficulty, scenario, features)
  (le prompt d'attaque n'est jamais écrit dans les logs ni les métadonnées sensibles)
- Annotations :
  - Identifiants directs localisés exactement ou insensibles à la casse
  - Identifiants indirects : localisés si présents littéralement, sinon `IMPLICIT` sans offsets
  - Clés indirectes mappées vers SPEC-01 (CIT->GEN_ORIGIN_BELIEF, DOB->GEN_AGE, MAR->GEN_FAMILY,
    SEX->GEN_GENDER, ST->GEN_GEO, SCHL->GEN_EDUCATION, OCCP->GEN_OCCUPATION, ESR->HR_CONTRACT,
    RAC2P->GEN_ORIGIN_BELIEF).
- Combinaisons :
  - Pour chaque document, calcule `k_true = sum(PWGTP)` via `PumsPopulation` sur les attributs
    reconnus dans PUMS
  - Émet `Combination` avec `scope=DOCUMENT`, `target_id=doc_id`, `source=DATASET`,
    `risk_model=PROSECUTOR`, `k_true=k_true`, `risk_true=1.0/k_true`, `at_risk=(k_true <= 10)`,
    `population_id="ratbench-us"`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from anonymisation.datasets._local import (
    check_files,
    fingerprint,
    resolve_source_dir,
)
from anonymisation.datasets.base import AcquisitionReport, DatasetAdapter
from anonymisation.datasets.ingest import IngestionError
from anonymisation.datasets.registry import register
from anonymisation.risk.population import (
    PopulationError,
    PopulationNoMatchError,
    PumsPopulation,
)
from anonymisation.schema.models import (
    Annotation,
    Combination,
    CombinationSource,
    Document,
    Domain,
    QiValue,
    RiskModel,
    Scope,
    TargetType,
    TaskLabel,
)
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Stability,
    validate_code,
)

_DIRECT_SPEC_MAP: dict[str, tuple[str, Granularity, Stability]] = {
    "name": ("DIR_NAME", Granularity.EXACT, Stability.STABLE),
    "email": ("DIR_EMAIL", Granularity.EXACT, Stability.VOLATILE),
    "phone number": ("DIR_PHONE", Granularity.EXACT, Stability.VOLATILE),
    "SSN": ("DIR_ID_NUMBER", Granularity.EXACT, Stability.STABLE),
    "credit card number": ("DIR_ACCOUNT", Granularity.EXACT, Stability.VOLATILE),
    "address": ("DIR_ADDRESS", Granularity.EXACT, Stability.VOLATILE),
}

_INDIRECT_SPEC_MAP: dict[str, tuple[str, Granularity, Stability]] = {
    "CIT": ("GEN_ORIGIN_BELIEF", Granularity.COARSE, Stability.STABLE),
    "DOB": ("GEN_AGE", Granularity.EXACT, Stability.STABLE),
    "MAR": ("GEN_FAMILY", Granularity.COARSE, Stability.STABLE),
    "SEX": ("GEN_GENDER", Granularity.COARSE, Stability.STABLE),
    "ST": ("GEN_GEO", Granularity.COARSE, Stability.VOLATILE),
    "SCHL": ("GEN_EDUCATION", Granularity.COARSE, Stability.STABLE),
    "OCCP": ("GEN_OCCUPATION", Granularity.COARSE, Stability.VOLATILE),
    "ESR": ("HR_CONTRACT", Granularity.COARSE, Stability.VOLATILE),
    "RAC2P": ("GEN_ORIGIN_BELIEF", Granularity.COARSE, Stability.STABLE),
    "DOB-Day": ("GEN_DATE_EVENT", Granularity.EXACT, Stability.STABLE),
    "DOB-Month": ("GEN_DATE_EVENT", Granularity.EXACT, Stability.STABLE),
    "DOB-Year": ("GEN_DATE_EVENT", Granularity.EXACT, Stability.STABLE),
    "zip code": ("GEN_GEO", Granularity.EXACT, Stability.VOLATILE),
}

_CIT_NORM: dict[str, str] = {
    "Born abroad of American parent(s)": "Born abroad of American parent(s)",
    "Born in Puerto Rico, Guam, the US Virgin Islands, or the Northern Marianas": (
        "Born in Puerto Rico, Guam, the U.S. Virgin Islands, or the Northern Marianas Islands"
    ),
    "Born in the US": "Born in the US",
    "Not a citizen of the US": "Not a citizen of the U.S.",
    "US citizen by naturalization": "U.S. citizen by naturalization",
}


@dataclass(frozen=True)
class _RatBenchEntry:
    doc_id: str
    item_id: int
    text: str
    difficulty: int
    scenario: str
    features: list[str]
    direct_identifiers: dict[str, str]
    indirect_identifiers: dict[str, str]
    profile: dict[str, Any]


def _find_occurrences(text: str, span_text: str) -> list[tuple[int, int]]:
    """Cherche exact puis insensible à la casse sans inventer d'offset."""
    if not span_text or not text:
        return []
    # Exact
    idx = text.find(span_text)
    if idx != -1:
        return [(idx, idx + len(span_text))]
    # Insensible à la casse
    idx = text.lower().find(span_text.lower())
    if idx != -1:
        return [(idx, idx + len(span_text))]
    return []


@register
class RatBenchAdapter(DatasetAdapter):
    """Adaptateur pour RAT-Bench avec calcul combinatoire PUMS."""

    key = "ratbench"
    aliases = ("rat-bench", "rat_bench")
    streaming: ClassVar[bool] = False

    def __init__(self, manifest: Any, raw_dir: Path) -> None:
        super().__init__(manifest, raw_dir)
        self._entries_cache: tuple[_RatBenchEntry, ...] | None = None
        self._pums: PumsPopulation | None = None

    def _source_files(self) -> dict[str, Path]:
        directory = resolve_source_dir(self.manifest.source)
        paths = check_files(directory, self.manifest.source.files)
        by_name = {p.name: p for p in paths}
        for p in paths:
            if p.name == "pums_population.parquet":
                by_name["pums_population.parquet"] = p
        if "english.jsonl" not in by_name:
            raise IngestionError("ratbench : english.jsonl absent")
        return by_name

    def download(self, *, force: bool = False) -> AcquisitionReport:
        del force
        files = self._source_files()
        digest = fingerprint(tuple(files.values()))
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        return AcquisitionReport(
            dataset=self.key,
            path=self.raw_dir,
            sha256=digest,
            bytes_downloaded=0,
            from_cache=True,
            revision=self.manifest.source.revision,
        )

    def _get_pums(self) -> PumsPopulation:
        if self._pums is None:
            files = self._source_files()
            pums_file = files.get("pums_population.parquet")
            if not pums_file or not pums_file.exists():
                raise IngestionError(
                    "ratbench : cache/pums_population.parquet absent pour le calcul de population"
                )
            self._pums = PumsPopulation(pums_file)
        return self._pums

    def _load_entries(self) -> tuple[_RatBenchEntry, ...]:
        if self._entries_cache is not None:
            return self._entries_cache

        files = self._source_files()
        jsonl_path = files["english.jsonl"]
        entries: list[_RatBenchEntry] = []

        try:
            with jsonl_path.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, start=1):
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        raw = json.loads(line_str)
                    except json.JSONDecodeError as exc:
                        raise IngestionError(
                            f"ratbench : {jsonl_path}:{line_no} : JSON invalide : {exc}"
                        ) from exc

                    item_id = int(raw["id"])
                    doc_id = f"ratbench:{item_id}"
                    entries.append(
                        _RatBenchEntry(
                            doc_id=doc_id,
                            item_id=item_id,
                            text=str(raw["text"]),
                            difficulty=int(raw.get("difficulty", 1)),
                            scenario=str(raw.get("scenario", "generic")),
                            features=list(raw.get("features", [])),
                            direct_identifiers=dict(raw.get("direct_identifiers", {})),
                            indirect_identifiers=dict(raw.get("indirect_identifiers", {})),
                            profile=dict(raw.get("profile", {})),
                        )
                    )
        except OSError as exc:
            raise IngestionError(f"ratbench : lecture impossible de {jsonl_path} : {exc}") from exc

        self._entries_cache = tuple(entries)
        return self._entries_cache

    def iter_documents(self, split: str) -> Iterator[Document]:
        for entry in self._load_entries():
            yield Document(
                doc_id=entry.doc_id,
                dataset=self.key,
                split=split,
                domain=Domain.GENERIC,
                language="en",
                text=entry.text,
                meta={
                    "item_id": entry.item_id,
                    "difficulty": entry.difficulty,
                    "scenario": entry.scenario,
                    "features": entry.features,
                },
            )

    def iter_annotations(self, split: str) -> Iterator[Annotation]:
        del split
        for entry in self._load_entries():
            # 1. Identifiants directs
            for key, val in entry.direct_identifiers.items():
                if not val:
                    continue
                if key not in _DIRECT_SPEC_MAP:
                    raise IngestionError(f"ratbench : identifiant direct inconnu : {key!r}")
                code, gran, stab = _DIRECT_SPEC_MAP[key]
                validate_code(code)

                matches = _find_occurrences(entry.text, str(val))
                if matches:
                    for s, e in matches:
                        yield Annotation(
                            annotation_id=f"{entry.doc_id}:dir:{key}:{s}_{e}",
                            doc_id=entry.doc_id,
                            start=s,
                            end=e,
                            span_text=entry.text[s:e],
                            identifier_type=IdentifierType.DIRECT,
                            qi_categories=(code,),
                            granularity=gran,
                            stability=stab,
                            expression_mode=ExpressionMode.EXPLICIT,
                            meta={"source_key": key, "unlocalized": False},
                        )
                else:
                    yield Annotation(
                        annotation_id=f"{entry.doc_id}:dir:{key}:unlocalized",
                        doc_id=entry.doc_id,
                        start=None,
                        end=None,
                        span_text=None,
                        identifier_type=IdentifierType.DIRECT,
                        qi_categories=(code,),
                        granularity=gran,
                        stability=stab,
                        expression_mode=ExpressionMode.IMPLICIT,
                        meta={"source_key": key, "unlocalized": True, "expected_value": str(val)},
                    )

            # 2. Identifiants indirects
            for key, val in entry.indirect_identifiers.items():
                if not val:
                    continue
                if key not in _INDIRECT_SPEC_MAP:
                    raise IngestionError(f"ratbench : identifiant indirect inconnu : {key!r}")
                code, gran, stab = _INDIRECT_SPEC_MAP[key]
                validate_code(code)

                matches = _find_occurrences(entry.text, str(val))
                if matches:
                    for s, e in matches:
                        yield Annotation(
                            annotation_id=f"{entry.doc_id}:ind:{key}:{s}_{e}",
                            doc_id=entry.doc_id,
                            start=s,
                            end=e,
                            span_text=entry.text[s:e],
                            identifier_type=IdentifierType.QUASI,
                            qi_categories=(code,),
                            granularity=gran,
                            stability=stab,
                            expression_mode=ExpressionMode.EXPLICIT,
                            meta={"source_key": key},
                        )
                else:
                    yield Annotation(
                        annotation_id=f"{entry.doc_id}:ind:{key}:implicit",
                        doc_id=entry.doc_id,
                        start=None,
                        end=None,
                        span_text=None,
                        identifier_type=IdentifierType.QUASI,
                        qi_categories=(code,),
                        granularity=gran,
                        stability=stab,
                        expression_mode=ExpressionMode.IMPLICIT,
                        meta={"source_key": key, "value": str(val)},
                    )

    def iter_combinations(self, split: str) -> Iterator[Combination]:
        del split
        pums = self._get_pums()
        skipped_no_match: list[str] = []
        emitted = 0

        for entry in self._load_entries():
            ind = entry.indirect_identifiers
            pums_criteria: dict[str, Any] = {}

            qi_values: list[QiValue] = []

            if "CIT" in ind:
                val = ind["CIT"]
                norm_cit = _CIT_NORM.get(val, val)
                pums_criteria["citizenship status"] = norm_cit
                qi_values.append(QiValue(qi_category="GEN_ORIGIN_BELIEF", normalized={"value": norm_cit}))

            if "MAR" in ind:
                val = ind["MAR"]
                pums_criteria["marital status"] = val
                qi_values.append(QiValue(qi_category="GEN_FAMILY", normalized={"value": val}))

            if "SEX" in ind:
                val = ind["SEX"]
                pums_criteria["sex"] = val
                qi_values.append(QiValue(qi_category="GEN_GENDER", normalized={"value": val}))

            if "ST" in ind:
                val = ind["ST"]
                pums_criteria["state of residence"] = val
                qi_values.append(QiValue(qi_category="GEN_GEO", normalized={"value": val}))

            if "SCHL" in ind:
                val = ind["SCHL"]
                pums_criteria["educational attainment"] = val
                qi_values.append(QiValue(qi_category="GEN_EDUCATION", normalized={"value": val}))

            if "ESR" in ind:
                val = ind["ESR"]
                pums_criteria["employment status"] = val
                qi_values.append(QiValue(qi_category="HR_CONTRACT", normalized={"value": val}))

            if not pums_criteria or not qi_values:
                continue

            try:
                k_true = pums.weighted_k(pums_criteria)
            except PopulationNoMatchError:
                # Combinaison absente de PUMS : cas de données, pas d'erreur de
                # source. On n'invente pas de k et on ne publie pas de
                # combinaison, mais on garde la trace du document écarté.
                skipped_no_match.append(entry.doc_id)
                continue
            except PopulationError as exc:
                # Erreur STRUCTURELLE (colonne absente, PWGTP manquant, parquet
                # illisible, pyarrow absent) : la taire ferait passer un
                # schéma incompatible pour un corpus sans individus à risque,
                # et RAT-Bench s'ingérerait avec zéro combinaison.
                raise IngestionError(
                    f"ratbench : population PUMS inexploitable pour {entry.doc_id} : {exc}"
                ) from exc

            risk_true = 1.0 / float(k_true)
            at_risk = bool(k_true <= 10)

            yield Combination(
                combination_id=f"{entry.doc_id}:pums_comb",
                dataset=self.key,
                target_type=TargetType.PERSON,
                target_id=entry.doc_id,
                scope=Scope.DOCUMENT,
                doc_ids=(entry.doc_id,),
                qi_set=tuple(qi_values),
                k_true=k_true,
                risk_true=risk_true,
                risk_model=RiskModel.PROSECUTOR,
                population_id="ratbench-us",
                at_risk=at_risk,
                source=CombinationSource.DATASET,
                meta={
                    "pums_criteria": pums_criteria,
                    "difficulty": entry.difficulty,
                },
            )
            emitted += 1

        if emitted == 0:
            raise IngestionError(
                "ratbench : aucune combinaison PUMS produite pour "
                f"{len(skipped_no_match)} document(s) interrogé(s) — schéma de "
                "population ou critères incompatibles, la moitié « risque » du "
                "benchmark serait vide."
            )

    def iter_tasks(self, split: str) -> Iterator[TaskLabel]:
        del split
        return iter(())

"""Adaptateur RAT-Bench (Krčo et al., 2026 — arXiv:2602.12806).

Normalise `english.jsonl` (niveaux 1 à 3, 300 exemples, cf. scripts/fetch_ratbench.py) :

- Document : `text`, `doc_id="ratbench:L<niveau>:<id>"`, métadonnées non
  sensibles (difficulty, scenario, features).
- Annotations : identifiants directs et indirects localisés (toutes les
  occurrences, mots entiers, casse ignorée), sinon `IMPLICIT` sans offsets.
- Profils (`profiles.jsonl`) : la vérité terrain complète du profil (identifiants
  directs et indirects, scénario, features) dans `Profile.meta`. Cette table
  n'est JAMAIS transmise aux systèmes : elle sert uniquement à l'attaque figée
  (`anonv2 attack`), qui juge les devinettes de l'attaquant.

Pas de combinaisons `k` gold : la v1 comptait `sum(PWGTP)` sur des colonnes
décodées d'un ACS 2022 qui n'est pas la population du papier, et sur 6 des 9
attributs (date de naissance, profession et origine ignorées). La population
officielle (PUMS 2010 rééchantillonné, sans poids) n'admet pas ce calcul ; le
risque de référence de RAT-Bench est CorrectMatch, calculé à l'étape d'attaque.
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
from anonymisation.schema.models import (
    Annotation,
    Document,
    Domain,
    Profile,
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


def _bounded_matches(haystack: str, needle: str) -> list[tuple[int, int]]:
    """Occurrences non chevauchantes de ``needle`` comme mot(s) entier(s)."""
    found: list[tuple[int, int]] = []
    check_left, check_right = needle[0].isalnum(), needle[-1].isalnum()
    start = haystack.find(needle)
    while start != -1:
        end = start + len(needle)
        left_ok = not check_left or start == 0 or not haystack[start - 1].isalnum()
        right_ok = not check_right or end == len(haystack) or not haystack[end].isalnum()
        if left_ok and right_ok:
            found.append((start, end))
            start = haystack.find(needle, end)
        else:
            start = haystack.find(needle, start + 1)
    return found


def _find_occurrences(text: str, span_text: str) -> list[tuple[int, int]]:
    """**Toutes** les occurrences, insensibles à la casse, mots entiers.

    La v1 ne renvoyait que la première occurrence, en sous-chaîne brute :
    « male » était localisé dans « female » ou « email », et les mentions
    suivantes d'un nom restaient hors gold (11 surfaces sur 18 sur
    l'échantillon `eval`). Conséquences : rappel surestimé, sur-masquage
    compté en faux positif, fuite résiduelle même pour un oracle.

    La recherche ignore la casse (« Male » / « male ») : c'est la même règle
    que l'adversaire littéral de CPR/IPR, sans quoi une mention en casse
    différente échapperait au gold mais serait comptée comme fuite.
    """
    if not span_text or not text:
        return []
    lowered = text.lower()
    # `str.lower` préserve la longueur pour l'immense majorité des textes ;
    # sinon, recherche exacte seule plutôt que des offsets décalés
    # (invariant text[start:end] == span_text à la casse près).
    if len(lowered) != len(text):
        return _bounded_matches(text, span_text)
    return _bounded_matches(lowered, span_text.lower())


#: Population de référence du papier : PUMS 2010 rééchantillonné (fichier officiel).
POPULATION_ID = "ratbench-us-pums2010"


@register
class RatBenchAdapter(DatasetAdapter):
    """Adaptateur pour RAT-Bench avec calcul combinatoire PUMS."""

    key = "ratbench"
    aliases = ("rat-bench", "rat_bench")
    streaming: ClassVar[bool] = False

    def __init__(self, manifest: Any, raw_dir: Path) -> None:
        super().__init__(manifest, raw_dir)
        self._entries_cache: tuple[_RatBenchEntry, ...] | None = None

    def _source_files(self) -> dict[str, Path]:
        directory = resolve_source_dir(self.manifest.source)
        paths = check_files(directory, self.manifest.source.files)
        by_name = {p.name: p for p in paths}
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
                    if "difficulty" not in raw:
                        raise IngestionError(
                            f"ratbench : {jsonl_path}:{line_no} : champ `difficulty` "
                            "absent — le niveau ne se devine pas (il distingue les "
                            "fichiers level_1..3 dont les `id` se recouvrent)."
                        )
                    difficulty = int(raw["difficulty"])
                    # Les fichiers level_1..3 numérotent tous leurs exemples
                    # 0..99, pour des profils DIFFÉRENTS : `ratbench:{id}` seul
                    # faisait collisionner trois personnes distinctes dès que
                    # les niveaux étaient combinés.
                    doc_id = f"ratbench:L{difficulty}:{item_id}"
                    entries.append(
                        _RatBenchEntry(
                            doc_id=doc_id,
                            item_id=item_id,
                            text=str(raw["text"]),
                            difficulty=difficulty,
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
                            entity_id=f"{entry.doc_id}:dir:{key}",
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
                            entity_id=f"{entry.doc_id}:ind:{key}",
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

    def iter_profiles(self, split: str) -> Iterator[Profile]:
        del split
        for entry in self._load_entries():
            yield Profile(
                person_id=entry.doc_id,
                dataset=self.key,
                population_id=POPULATION_ID,
                attributes={},
                meta={
                    "difficulty": entry.difficulty,
                    "scenario": entry.scenario,
                    "features": entry.features,
                    "direct_identifiers": entry.direct_identifiers,
                    "indirect_identifiers": entry.indirect_identifiers,
                },
            )

    def iter_tasks(self, split: str) -> Iterator[TaskLabel]:
        del split
        return iter(())

"""Adaptateur pour le jeu de données DB-bio.

Normalise `train.jsonl` (1 938), `val.jsonl` (243) et `test.jsonl` (239) :
- Document : `text`, `doc_id="dbbio:{split}:{index}"`, domaine generic, langue en
- Annotations :
  - `DIR_NAME` uniquement pour les occurrences exactement ou insensiblement
    localisées de `people` ou `wiki_name` (avec `wiki_name` converti sans underscores).
  - Tout échec de localisation est documenté dans l'audit sans inventer d'offsets.
- Tâches : trois `TaskLabel` distincts :
  - `occupation_l1`
  - `occupation_l2`
  - `occupation_l3`
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
    Combination,
    Document,
    Domain,
    LabelType,
    TaskLabel,
)
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Stability,
    validate_code,
)


@dataclass(frozen=True)
class _DbbioRow:
    doc_id: str
    split: str
    index: int
    text: str
    l1: str
    l2: str
    l3: str
    wiki_name: str
    people: str
    word_count: int
    label: str


def _find_occurrences(text: str, needle: str) -> list[tuple[int, int]]:
    if not needle or not text:
        return []
    needle_clean = needle.replace("_", " ").strip()
    if not needle_clean:
        return []
    # Recherche exacte
    matches: list[tuple[int, int]] = []
    start = 0
    while True:
        idx = text.find(needle_clean, start)
        if idx == -1:
            break
        matches.append((idx, idx + len(needle_clean)))
        start = idx + 1
    if matches:
        return matches

    # Recherche insensible à la casse
    t_lower = text.lower()
    n_lower = needle_clean.lower()
    start = 0
    while True:
        idx = t_lower.find(n_lower, start)
        if idx == -1:
            break
        matches.append((idx, idx + len(needle_clean)))
        start = idx + 1
    return matches


@register
class DbbioAdapter(DatasetAdapter):
    """Adaptateur DB-bio (biographies Wikipedia annotées par métier DBpedia)."""

    key = "dbbio"
    aliases = ("db-bio",)
    streaming: ClassVar[bool] = False

    _SOURCE_FILES: ClassVar[dict[str, str]] = {
        "train": "train.jsonl",
        "val": "val.jsonl",
        "test": "test.jsonl",
    }

    def __init__(self, manifest: Any, raw_dir: Path) -> None:
        super().__init__(manifest, raw_dir)
        self._cache_by_split: dict[str, tuple[_DbbioRow, ...]] = {}

    def _source_files(self) -> dict[str, Path]:
        directory = resolve_source_dir(self.manifest.source)
        paths = check_files(directory, self.manifest.source.files)
        by_name = {p.name: p for p in paths}
        for split, fname in self._SOURCE_FILES.items():
            if fname not in by_name:
                raise IngestionError(f"dbbio : fichier source manquant pour split {split} : {fname}")
        return {split: by_name[fname] for split, fname in self._SOURCE_FILES.items()}
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

    def _load_split(self, split: str) -> tuple[_DbbioRow, ...]:
        if split in self._cache_by_split:
            return self._cache_by_split[split]

        files = self._source_files()
        if split not in files:
            raise IngestionError(f"dbbio : split inconnu {split!r}")

        path = files[split]
        rows: list[_DbbioRow] = []

        try:
            with path.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, start=1):
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        raw = json.loads(line_str)
                    except json.JSONDecodeError as exc:
                        raise IngestionError(
                            f"dbbio : {path}:{line_no} : JSON invalide : {exc}"
                        ) from exc

                    doc_id = f"dbbio:{split}:{line_no}"
                    rows.append(
                        _DbbioRow(
                            doc_id=doc_id,
                            split=split,
                            index=line_no,
                            text=str(raw["text"]),
                            l1=str(raw.get("l1", "UNKNOWN")),
                            l2=str(raw.get("l2", "UNKNOWN")),
                            l3=str(raw.get("l3", "UNKNOWN")),
                            wiki_name=str(raw.get("wiki_name", "")),
                            people=str(raw.get("people", "")),
                            word_count=int(raw.get("word_count", 0)),
                            label=str(raw.get("label", "")),
                        )
                    )
        except OSError as exc:
            raise IngestionError(f"dbbio : lecture impossible de {path} : {exc}") from exc

        self._cache_by_split[split] = tuple(rows)
        return self._cache_by_split[split]

    def iter_documents(self, split: str) -> Iterator[Document]:
        for row in self._load_split(split):
            yield Document(
                doc_id=row.doc_id,
                dataset=self.key,
                split=split,
                domain=Domain.GENERIC,
                language="en",
                text=row.text,
                meta={
                    "source_split": split,
                    "source_index": row.index,
                    "wiki_name": row.wiki_name,
                    "people": row.people,
                    "word_count": row.word_count,
                    "label": row.label,
                },
            )

    def iter_annotations(self, split: str) -> Iterator[Annotation]:
        validate_code("DIR_NAME")
        for row in self._load_split(split):
            candidates = [c for c in (row.people, row.wiki_name) if c.strip()]
            found_any = False

            for c_idx, candidate in enumerate(candidates):
                matches = _find_occurrences(row.text, candidate)
                for s, e in matches:
                    found_any = True
                    yield Annotation(
                        annotation_id=f"{row.doc_id}:name:{c_idx}:{s}_{e}",
                        doc_id=row.doc_id,
                        start=s,
                        end=e,
                        span_text=row.text[s:e],
                        identifier_type=IdentifierType.DIRECT,
                        qi_categories=("DIR_NAME",),
                        granularity=Granularity.EXACT,
                        stability=Stability.STABLE,
                        expression_mode=ExpressionMode.EXPLICIT,
                        meta={"candidate": candidate},
                    )

            if not found_any and candidates:
                yield Annotation(
                    annotation_id=f"{row.doc_id}:name:unlocalized",
                    doc_id=row.doc_id,
                    start=None,
                    end=None,
                    span_text=None,
                    identifier_type=IdentifierType.DIRECT,
                    qi_categories=("DIR_NAME",),
                    granularity=Granularity.EXACT,
                    stability=Stability.STABLE,
                    expression_mode=ExpressionMode.IMPLICIT,
                    meta={"unlocalized": True, "candidates": candidates},
                )

    def iter_combinations(self, split: str) -> Iterator[Combination]:
        del split
        return iter(())

    def iter_tasks(self, split: str) -> Iterator[TaskLabel]:
        for row in self._load_split(split):
            yield TaskLabel(
                doc_id=row.doc_id,
                task="occupation_l1",
                label=row.l1,
                label_type=LabelType.SINGLE,
                meta={"level": 1},
            )
            yield TaskLabel(
                doc_id=row.doc_id,
                task="occupation_l2",
                label=row.l2,
                label_type=LabelType.SINGLE,
                meta={"level": 2},
            )
            yield TaskLabel(
                doc_id=row.doc_id,
                task="occupation_l3",
                label=row.l3,
                label_type=LabelType.SINGLE,
                meta={"level": 3},
            )

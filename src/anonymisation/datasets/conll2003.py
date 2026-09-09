"""Adaptateur pour le jeu de données CoNLL-2003 / CleanCoNLL.

Parse les colonnes BIO des fichiers conll03 (`train.txt`, `valid.txt -> dev`, `test.txt`)
via `_bio.bio_to_spans` :
- Mappe :
  - `PER -> DIR_NAME` (DIRECT)
  - `ORG -> GEN_AFFILIATION` (QUASI)
  - `LOC -> GEN_GEO` (QUASI)
  - `MISC -> IGNORED` (QUASI)
- Statut : DIAGNOSTIC
- Domaine : GENERIC (l'enum Domain n'a pas "news", stocké dans `Document.meta["genre"] = "newswire"`)
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from anonymisation.datasets._bio import bio_to_spans
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
    TaskLabel,
)
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Stability,
    validate_code,
)

_LABEL_SPEC_MAP: dict[str, tuple[IdentifierType, str, Granularity, Stability]] = {
    "PER": (IdentifierType.DIRECT, "DIR_NAME", Granularity.EXACT, Stability.STABLE),
    "ORG": (IdentifierType.QUASI, "GEN_AFFILIATION", Granularity.COARSE, Stability.VOLATILE),
    "LOC": (IdentifierType.QUASI, "GEN_GEO", Granularity.COARSE, Stability.VOLATILE),
    "MISC": (IdentifierType.QUASI, "IGNORED", Granularity.COARSE, Stability.VOLATILE),
}


@dataclass(frozen=True)
class _ConllSentence:
    doc_id: str
    split: str
    sentence_idx: int
    text: str
    spans: tuple[tuple[int, int, str], ...]


@register
class Conll2003Adapter(DatasetAdapter):
    """Adaptateur CoNLL-2003 / CleanCoNLL."""

    key = "conll2003"
    aliases = ("conll-2003", "cleanconll", "conll")
    streaming: ClassVar[bool] = False

    _SOURCE_FILES: ClassVar[dict[str, str]] = {
        "train": "train.txt",
        "dev": "valid.txt",
        "test": "test.txt",
    }

    def __init__(self, manifest: Any, raw_dir: Path) -> None:
        super().__init__(manifest, raw_dir)
        self._cache_by_split: dict[str, tuple[_ConllSentence, ...]] = {}

    def _source_files(self) -> dict[str, Path]:
        directory = resolve_source_dir(self.manifest.source)
        paths = check_files(directory, self.manifest.source.files)
        by_name = {p.name: p for p in paths}
        for split, fname in self._SOURCE_FILES.items():
            if fname not in by_name:
                raise IngestionError(f"conll2003 : fichier source manquant pour split {split} : {fname}")
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

    def _load_split(self, split: str) -> tuple[_ConllSentence, ...]:
        if split in self._cache_by_split:
            return self._cache_by_split[split]

        files = self._source_files()
        if split not in files:
            raise IngestionError(f"conll2003 : split inconnu {split!r}")

        path = files[split]
        sentences: list[_ConllSentence] = []

        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                current_tokens: list[str] = []
                current_tags: list[str] = []
                sent_idx = 0

                def _flush() -> None:
                    nonlocal sent_idx, current_tokens, current_tags
                    if not current_tokens:
                        return
                    text, spans = bio_to_spans(current_tokens, current_tags)
                    # Vérifier que text[start:end] correspond
                    for s, e, _ in spans:
                        assert text[s:e], "Span non vide"
                    doc_id = f"conll2003:{split}:{sent_idx}"
                    sentences.append(
                        _ConllSentence(
                            doc_id=doc_id,
                            split=split,
                            sentence_idx=sent_idx,
                            text=text,
                            spans=tuple(spans),
                        )
                    )
                    sent_idx += 1
                    current_tokens = []
                    current_tags = []

                for line in f:
                    line = line.strip()
                    if not line:
                        _flush()
                        continue
                    if line.startswith("-DOCSTART-"):
                        _flush()
                        continue
                    parts = line.split()
                    token = parts[0]
                    tag = parts[-1]
                    current_tokens.append(token)
                    current_tags.append(tag)
                _flush()

        except OSError as exc:
            raise IngestionError(f"conll2003 : lecture impossible de {path} : {exc}") from exc

        self._cache_by_split[split] = tuple(sentences)
        return self._cache_by_split[split]

    def iter_documents(self, split: str) -> Iterator[Document]:
        for sent in self._load_split(split):
            yield Document(
                doc_id=sent.doc_id,
                dataset=self.key,
                split=split,
                domain=Domain.GENERIC,
                language="en",
                text=sent.text,
                meta={
                    "source_split": split,
                    "sentence_idx": sent.sentence_idx,
                    "genre": "newswire",
                },
            )

    def iter_annotations(self, split: str) -> Iterator[Annotation]:
        for sent in self._load_split(split):
            for sp_idx, (start, end, bio_type) in enumerate(sent.spans):
                if bio_type not in _LABEL_SPEC_MAP:
                    raise IngestionError(f"conll2003 : étiquette inconnue {bio_type!r}")

                id_type, code, gran, stab = _LABEL_SPEC_MAP[bio_type]
                validate_code(code)

                yield Annotation(
                    annotation_id=f"{sent.doc_id}:ann:{sp_idx}",
                    doc_id=sent.doc_id,
                    start=start,
                    end=end,
                    span_text=sent.text[start:end],
                    identifier_type=id_type,
                    qi_categories=(code,),
                    granularity=gran,
                    stability=stab,
                    expression_mode=ExpressionMode.EXPLICIT,
                    meta={"original_bio_type": bio_type},
                )

    def iter_combinations(self, split: str) -> Iterator[Combination]:
        del split
        return iter(())

    def iter_tasks(self, split: str) -> Iterator[TaskLabel]:
        del split
        return iter(())

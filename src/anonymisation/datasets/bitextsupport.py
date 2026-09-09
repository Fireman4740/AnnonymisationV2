"""Adaptateur pour le jeu de données BitextSupportSynthetic.

Lit `train.parquet` (26 872 lignes) :
- Texte du document : `instruction` (l'instruction seule pour éviter de fuiter la cible)
- Métadonnées : `response`, `flags`
- Tâches : `intent` et `category`
- Répartition train/dev/test déterministe par hachage de l'ID de ligne.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from anonymisation.datasets._local import (
    check_files,
    fingerprint,
    resolve_source_dir,
)
from anonymisation.datasets._split import assign_split
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


@dataclass(frozen=True)
class _BitextRow:
    index: int
    doc_id: str
    split: str
    instruction: str
    category: str
    intent: str
    response: str
    flags: str


@register
class BitextSupportAdapter(DatasetAdapter):
    """Adaptateur BitextSupportSynthetic (requêtes client synthétiques)."""

    key = "bitextsupport"
    aliases = ("bitext-support-synthetic", "bitext_support", "bitext")
    streaming: ClassVar[bool] = False

    _EXPECTED_COLUMNS: ClassVar[tuple[str, ...]] = (
        "instruction",
        "category",
        "intent",
        "response",
        "flags",
    )

    def __init__(self, manifest: Any, raw_dir: Path) -> None:
        super().__init__(manifest, raw_dir)
        self._rows_cache: tuple[_BitextRow, ...] | None = None

    def _source_file(self) -> Path:
        directory = resolve_source_dir(self.manifest.source)
        paths = check_files(directory, self.manifest.source.files)
        if not paths:
            raise IngestionError("bitextsupport : aucun fichier source trouvé")
        return paths[0]
    def download(self, *, force: bool = False) -> AcquisitionReport:
        del force
        path = self._source_file()
        digest = fingerprint((path,))
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        return AcquisitionReport(
            dataset=self.key,
            path=self.raw_dir,
            sha256=digest,
            bytes_downloaded=0,
            from_cache=True,
            revision=self.manifest.source.revision,
        )

    def _split_config(self) -> tuple[int, dict[str, float]]:
        policy = getattr(self.manifest, "split_policy", None)
        if policy is None:
            return 42, {"train": 0.8, "dev": 0.1, "test": 0.1}
        return policy.seed, dict(policy.ratios)

    def _load_rows(self) -> tuple[_BitextRow, ...]:
        if self._rows_cache is not None:
            return self._rows_cache

        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise IngestionError(
                "bitextsupport nécessite pyarrow pour lire train.parquet."
            ) from exc

        path = self._source_file()
        try:
            table = pq.read_table(path, columns=list(self._EXPECTED_COLUMNS))
        except Exception as exc:
            raise IngestionError(
                f"bitextsupport : erreur de lecture de {path} : {exc}"
            ) from exc

        missing_cols = [col for col in self._EXPECTED_COLUMNS if col not in table.column_names]
        if missing_cols:
            raise IngestionError(
                f"bitextsupport : colonnes manquantes dans {path} : {missing_cols}"
            )

        seed, ratios = self._split_config()
        rows: list[_BitextRow] = []

        instr_col = table["instruction"].to_pylist()
        cat_col = table["category"].to_pylist()
        intent_col = table["intent"].to_pylist()
        resp_col = table["response"].to_pylist()
        flags_col = table["flags"].to_pylist()

        num_rows = len(table)
        for i in range(num_rows):
            doc_id = f"bitextsupport:{i}"
            split = assign_split(doc_id, seed, ratios)

            instruction = instr_col[i] or ""
            category = cat_col[i] or "UNKNOWN"
            intent = intent_col[i] or "UNKNOWN"
            response = resp_col[i] or ""
            flags = flags_col[i] or ""

            rows.append(
                _BitextRow(
                    index=i,
                    doc_id=doc_id,
                    split=split,
                    instruction=str(instruction),
                    category=str(category),
                    intent=str(intent),
                    response=str(response),
                    flags=str(flags),
                )
            )

        self._rows_cache = tuple(rows)
        return self._rows_cache

    def iter_documents(self, split: str) -> Iterator[Document]:
        for row in self._load_rows():
            if row.split != split:
                continue
            text = row.instruction.strip()
            if not text:
                text = "Empty instruction"

            yield Document(
                doc_id=row.doc_id,
                dataset=self.key,
                split=split,
                domain=Domain.SUPPORT,
                language="en",
                text=text,
                meta={
                    "source_row": row.index,
                    "response": row.response,
                    "flags": row.flags,
                    "category": row.category,
                    "intent": row.intent,
                },
            )

    def iter_annotations(self, split: str) -> Iterator[Annotation]:
        del split
        return iter(())

    def iter_combinations(self, split: str) -> Iterator[Combination]:
        del split
        return iter(())

    def iter_tasks(self, split: str) -> Iterator[TaskLabel]:
        for row in self._load_rows():
            if row.split != split:
                continue
            yield TaskLabel(
                doc_id=row.doc_id,
                task="intent",
                label=row.intent,
                label_type=LabelType.SINGLE,
                meta={"source_field": "intent"},
            )
            yield TaskLabel(
                doc_id=row.doc_id,
                task="category",
                label=row.category,
                label_type=LabelType.SINGLE,
                meta={"source_field": "category"},
            )

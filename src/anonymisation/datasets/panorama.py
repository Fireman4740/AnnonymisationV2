"""Adaptateur PANORAMA, corpus synthétique de textes PII-laces.

La release publique principale expose ``id``, ``content-type`` et ``text`` dans
un Parquet Hugging Face. Elle ne fournit pas les annotations de spans du
benchmark SPIA ; l'adaptateur publie donc les documents et leurs metadonnees,
mais jamais des annotations inventees.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from anonymisation.datasets._local import fingerprint
from anonymisation.datasets.base import AcquisitionReport, DatasetAdapter
from anonymisation.datasets.ingest import IngestionError
from anonymisation.datasets.registry import register
from anonymisation.schema.models import Annotation, Document, Domain


_DEFAULT_FILES: tuple[str, ...] = ("train.parquet", "train.jsonl")


@register
class PanoramaAdapter(DatasetAdapter):
    """Normalise la release PANORAMA sans dependre de pandas au demarrage."""

    key = "panorama"
    aliases = ("panorama-main",)
    streaming: ClassVar[bool] = True

    def _file_names(self) -> tuple[str, ...]:
        declared = tuple(self.manifest.source.files)
        return declared or _DEFAULT_FILES

    def _path(self) -> Path:
        declared = tuple(self.raw_dir / name for name in self._file_names())
        for path in declared:
            if path.is_file():
                return path
        raise IngestionError(
            "panorama : aucun fichier source trouve : "
            + ", ".join(str(path) for path in declared)
        )

    def download(self, *, force: bool = False) -> AcquisitionReport:
        """Verifie un cache acquis ; aucune acquisition reseau implicite."""
        del force
        path = self._path()
        return AcquisitionReport(
            dataset=self.key,
            path=self.raw_dir,
            sha256=fingerprint((path,)),
            bytes_downloaded=0,
            from_cache=True,
            revision=self.manifest.source.revision,
        )

    @staticmethod
    def _validate_row(path: Path, line_number: int, row: Any) -> dict[str, Any]:
        if not isinstance(row, dict):
            raise IngestionError(f"panorama : {path}:{line_number} : ligne non-objet")
        identifier = row.get("id", row.get("data_id"))
        text = row.get("text")
        if identifier is None or not str(identifier) or not isinstance(text, str):
            raise IngestionError(
                f"panorama : {path}:{line_number} : champs id/text absents ou invalides"
            )
        return row

    def _iter_jsonl(self, path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
        with path.open(encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    raise IngestionError(f"panorama : {path}:{line_number} : ligne vide")
                try:
                    row = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise IngestionError(
                        f"panorama : {path}:{line_number} : JSON invalide ({exc.msg})"
                    ) from exc
                yield line_number, self._validate_row(path, line_number, row)

    def _iter_parquet(self, path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
        try:
            import pyarrow.parquet as parquet
        except ImportError as exc:
            raise IngestionError(
                "panorama : la source Parquet requiert l'extra `datasets` "
                "(pyarrow) ; installez `pip install -e '.[datasets]'`"
            ) from exc
        parquet_file = parquet.ParquetFile(path)
        line_number = 0
        for batch in parquet_file.iter_batches(batch_size=4096):
            for row in batch.to_pylist():
                line_number += 1
                yield line_number, self._validate_row(path, line_number, row)

    def _rows(self, split: str) -> Iterator[tuple[Path, int, dict[str, Any]]]:
        if split not in ("all", "train"):
            raise IngestionError("panorama : seul le split 'train' (ou 'all') est disponible")
        path = self._path()
        iterator = self._iter_parquet(path) if path.suffix.lower() == ".parquet" else self._iter_jsonl(path)
        for line_number, row in iterator:
            yield path, line_number, row

    @staticmethod
    def _identifier(row: dict[str, Any]) -> str:
        return str(row.get("id", row.get("data_id")))

    def iter_documents(self, split: str) -> Iterator[Document]:
        for path, line_number, row in self._rows(split):
            source_id = self._identifier(row)
            doc_id = f"panorama:{source_id}"
            content_type = row.get("content-type", row.get("content_type", "unknown"))
            try:
                yield Document(
                    doc_id=doc_id,
                    dataset=self.key,
                    split="train",
                    domain=Domain.FORUM,
                    language="en",
                    text=row["text"],
                    meta={
                        "source_id": source_id,
                        "content_type": str(content_type),
                        "synthetic": True,
                        "profile_id": row.get("profile_id"),
                    },
                )
            except ValueError as exc:
                raise IngestionError(
                    f"panorama : {path}:{line_number} : doc_id={doc_id} : document invalide ({exc})"
                ) from exc

    def iter_annotations(self, split: str) -> Iterator[Annotation]:
        del split
        return
        yield  # pragma: no cover - keeps this abstract-contract method a generator

    def describe(self) -> dict[str, Any]:
        result = super().describe()
        result.update(
            {
                "synthetic": True,
                "attribute_coherence": True,
                "annotation_source": "none in the main release",
            }
        )
        return result

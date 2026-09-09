"""Adaptateur pour le jeu de données SupportTicketsReal.

Lit `train.parquet` (61 765 lignes), projette les colonnes requises :
- Texte du document : `subject + "\\n\\n" + body`
- Réponse stockée dans `Document.meta["answer"]`
- Tâches : `ticket_routing` (queue), `ticket_priority` (priority), `ticket_type` (type)
- Métadonnées complètes conservées (language, version, tags, etc.)
- Répartition train/dev/test déterministe par hachage de l'identifiant de document.
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
class _TicketRow:
    index: int
    doc_id: str
    split: str
    subject: str
    body: str
    answer: str
    type: str
    queue: str
    priority: str
    language: str
    version: str
    tags: tuple[str, ...]


@register
class SupportTicketsAdapter(DatasetAdapter):
    """Adaptateur SupportTicketsReal (tickets de support client multilingues)."""

    key = "supporttickets"
    aliases = ("support-tickets-real", "support_tickets")
    streaming: ClassVar[bool] = False

    _EXPECTED_COLUMNS: ClassVar[tuple[str, ...]] = (
        "subject",
        "body",
        "answer",
        "type",
        "queue",
        "priority",
        "language",
        "version",
        "tag_1",
        "tag_2",
        "tag_3",
        "tag_4",
        "tag_5",
        "tag_6",
        "tag_7",
        "tag_8",
    )

    def __init__(self, manifest: Any, raw_dir: Path) -> None:
        super().__init__(manifest, raw_dir)
        self._rows_cache: tuple[_TicketRow, ...] | None = None

    def _source_file(self) -> Path:
        directory = resolve_source_dir(self.manifest.source)
        paths = check_files(directory, self.manifest.source.files)
        if not paths:
            raise IngestionError("supporttickets : aucun fichier source trouvé")
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

    def _load_rows(self) -> tuple[_TicketRow, ...]:
        if self._rows_cache is not None:
            return self._rows_cache

        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise IngestionError(
                "supporttickets nécessite pyarrow pour lire train.parquet. "
                "Installez pyarrow ou le paquet avec l'extra datasets."
            ) from exc

        path = self._source_file()
        try:
            schema = pq.read_schema(path)
            missing_cols = [col for col in self._EXPECTED_COLUMNS if col not in schema.names]
            if missing_cols:
                raise IngestionError(
                    f"supporttickets : colonnes manquantes dans {path} : {missing_cols}"
                )
            table = pq.read_table(path, columns=list(self._EXPECTED_COLUMNS))
        except IngestionError:
            raise
        except Exception as exc:
            raise IngestionError(
                f"supporttickets : erreur de lecture de {path} : {exc}"
            ) from exc
        seed, ratios = self._split_config()
        rows: list[_TicketRow] = []

        sub_col = table["subject"].to_pylist()
        body_col = table["body"].to_pylist()
        ans_col = table["answer"].to_pylist()
        type_col = table["type"].to_pylist()
        queue_col = table["queue"].to_pylist()
        prio_col = table["priority"].to_pylist()
        lang_col = table["language"].to_pylist()
        ver_col = table["version"].to_pylist()

        tag_cols = [table[f"tag_{i}"].to_pylist() for i in range(1, 9)]

        num_rows = len(table)
        for i in range(num_rows):
            doc_id = f"supporttickets:{i}"
            split = assign_split(doc_id, seed, ratios)

            subject = sub_col[i] or ""
            body = body_col[i] or ""
            answer = ans_col[i] or ""
            t_type = type_col[i] or "UNKNOWN"
            queue = queue_col[i] or "UNKNOWN"
            prio = prio_col[i] or "UNKNOWN"
            lang = lang_col[i] or "en"
            ver = ver_col[i] or "1"

            tags = tuple(
                str(tag_cols[t_idx][i])
                for t_idx in range(8)
                if tag_cols[t_idx][i] is not None and str(tag_cols[t_idx][i]).strip()
            )

            rows.append(
                _TicketRow(
                    index=i,
                    doc_id=doc_id,
                    split=split,
                    subject=str(subject),
                    body=str(body),
                    answer=str(answer),
                    type=str(t_type),
                    queue=str(queue),
                    priority=str(prio),
                    language=str(lang).lower()[:2],
                    version=str(ver),
                    tags=tags,
                )
            )

        self._rows_cache = tuple(rows)
        return self._rows_cache

    def iter_documents(self, split: str) -> Iterator[Document]:
        for row in self._load_rows():
            if row.split != split:
                continue
            text = f"{row.subject}\n\n{row.body}".strip()
            if not text:
                text = "Empty ticket"

            yield Document(
                doc_id=row.doc_id,
                dataset=self.key,
                split=split,
                domain=Domain.SUPPORT,
                language=row.language,
                text=text,
                meta={
                    "source_row": row.index,
                    "answer": row.answer,
                    "version": row.version,
                    "tags": list(row.tags),
                    "original_type": row.type,
                    "original_queue": row.queue,
                    "original_priority": row.priority,
                },
            )

    def iter_annotations(self, split: str) -> Iterator[Annotation]:
        # Aucun span gold n'est fabriqué : has_combinations = false, has_tasks = true
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
                task="ticket_routing",
                label=row.queue,
                label_type=LabelType.SINGLE,
                meta={"source_field": "queue"},
            )
            yield TaskLabel(
                doc_id=row.doc_id,
                task="ticket_priority",
                label=row.priority,
                label_type=LabelType.SINGLE,
                meta={"source_field": "priority"},
            )
            yield TaskLabel(
                doc_id=row.doc_id,
                task="ticket_type",
                label=row.type,
                label_type=LabelType.SINGLE,
                meta={"source_field": "type"},
            )

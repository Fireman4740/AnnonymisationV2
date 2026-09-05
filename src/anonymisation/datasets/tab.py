"""Adaptateur du TAB officiel (Text Anonymization Benchmark).

La release officielle est une liste JSON de documents. Chaque document porte
les mentions de plusieurs annotateurs. Le protocole source de TAB considère
comme cible l'union des mentions ``DIRECT`` et ``QUASI`` de tous les
annotateurs ; ``NO_MASK`` est hors cible et ses volumes restent dans les
métadonnées du document.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from anonymisation.datasets._local import check_files, fingerprint, resolve_source_dir
from anonymisation.datasets.base import AcquisitionReport, DatasetAdapter
from anonymisation.datasets.ingest import IngestionError
from anonymisation.datasets.registry import UnmappedLabelError, register
from anonymisation.schema.models import Annotation, Document, Domain
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    IdentifierType,
    Sensitivity,
    Subject,
)


@register
class TabAdapter(DatasetAdapter):
    """Normalise TAB en union multi-annotateurs, sans resplitter."""

    key = "tab"
    aliases = ("text-anonymization-benchmark",)
    streaming: ClassVar[bool] = False

    _SPLIT_FILES: ClassVar[dict[str, str]] = {
        "train": "echr_train.json",
        "dev": "echr_dev.json",
        "test": "echr_test.json",
    }
    _REQUIRED_RECORD_FIELDS: ClassVar[tuple[str, ...]] = (
        "doc_id",
        "text",
        "annotations",
        "meta",
        "task",
    )
    _ALLOWED_IDENTIFIER_TYPES: ClassVar[frozenset[str]] = frozenset(
        {"DIRECT", "QUASI", "NO_MASK"}
    )
    _ALLOWED_STATUSES: ClassVar[frozenset[str]] = frozenset(
        {"NOT_CONFIDENTIAL", "HEALTH", "POLITICS", "ETHNIC", "BELIEF", "SEX"}
    )

    def __init__(self, manifest: Any, raw_dir: Path) -> None:
        super().__init__(manifest, raw_dir)
        self._records_cache: dict[str, tuple[dict[str, Any], ...]] = {}
        self._merged_cache: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    # --- Acquisition ------------------------------------------------------ #

    def _source_files(self) -> dict[str, Path]:
        directory = resolve_source_dir(self.manifest.source)
        paths = check_files(directory, self.manifest.source.files)
        by_name = {path.name: path for path in paths}
        missing = [name for name in self._SPLIT_FILES.values() if name not in by_name]
        if missing:
            raise IngestionError("tab : fichiers déclarés absents : " + ", ".join(missing))
        return {split: by_name[name] for split, name in self._SPLIT_FILES.items()}

    def download(self, *, force: bool = False) -> AcquisitionReport:
        """Vérifie les fichiers TAB locaux ; aucun téléchargement implicite."""

        del force
        paths = tuple(self._source_files().values())
        digest = fingerprint(paths)
        expected = self.manifest.integrity.sha256
        if expected is not None and expected != digest:
            raise IngestionError(
                f"tab : empreinte différente du manifeste : attendu {expected}, obtenu {digest}"
            )
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        return AcquisitionReport(
            dataset=self.key,
            path=self.raw_dir,
            sha256=digest,
            bytes_downloaded=0,
            from_cache=True,
            revision=self.manifest.source.revision,
        )

    # --- Parsing ---------------------------------------------------------- #

    def _path_for_split(self, split: str) -> Path:
        try:
            return self._source_files()[split]
        except KeyError as exc:
            raise IngestionError(
                f"tab : split inconnu {split!r} ; attendus : {', '.join(self._SPLIT_FILES)}"
            ) from exc

    def _load_records(self, split: str) -> tuple[dict[str, Any], ...]:
        cached = self._records_cache.get(split)
        if cached is not None:
            return cached
        path = self._path_for_split(split)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise IngestionError(f"tab : lecture impossible de {path} : {exc}") from exc
        if not isinstance(payload, list):
            raise IngestionError(f"tab : {path} doit contenir une liste de documents")
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for position, record in enumerate(payload, start=1):
            if not isinstance(record, dict):
                raise IngestionError(f"tab : {path} : document {position} n'est pas un objet")
            missing = [field for field in self._REQUIRED_RECORD_FIELDS if field not in record]
            if missing:
                raise IngestionError(
                    f"tab : {path} : document {position} : champs manquants : "
                    + ", ".join(missing)
                )
            doc_id = record["doc_id"]
            if not isinstance(doc_id, str) or not doc_id:
                raise IngestionError(f"tab : {path} : document {position} : doc_id invalide")
            if doc_id in seen:
                raise IngestionError(f"tab : {path} : doc_id dupliqué : {doc_id}")
            seen.add(doc_id)
            if not isinstance(record["text"], str):
                raise IngestionError(f"tab : {path} : {doc_id} : text doit être une chaîne")
            if not isinstance(record["annotations"], dict):
                raise IngestionError(
                    f"tab : {path} : {doc_id} : annotations doit être un objet"
                )
            if not isinstance(record["meta"], dict):
                raise IngestionError(f"tab : {path} : {doc_id} : meta doit être un objet")
            if not isinstance(record["task"], str):
                raise IngestionError(f"tab : {path} : {doc_id} : task doit être une chaîne")
            records.append(record)
        result = tuple(records)
        self._records_cache[split] = result
        return result

    def _iter_records(self, split: str) -> Iterator[tuple[int, dict[str, Any], str]]:
        for position, record in enumerate(self._load_records(split), start=1):
            yield position, record, f"{self.key}:{split}:{record['doc_id']}"

    @staticmethod
    def _status_to_sensitivity(status: str) -> Sensitivity:
        if status == "NOT_CONFIDENTIAL":
            return Sensitivity.NONE
        if status == "HEALTH":
            return Sensitivity.HEALTH
        if status == "SEX":
            return Sensitivity.SEXLIFE
        # SPEC-01 n'a pas d'axes ETHNIC/POLITICS autonomes ; BELIEF est le
        # porteur RGPD le plus proche, et la valeur TAB originale est conservée.
        if status in {"POLITICS", "ETHNIC", "BELIEF"}:
            return Sensitivity.BELIEF
        raise IngestionError(f"tab : confidential_status inconnu : {status!r}")

    def _entry(self, entity_type: str) -> Any:
        entry = self.manifest.label_map.get(entity_type)
        if entry is None:
            raise UnmappedLabelError(
                f"tab : type {entity_type!r} absent du label_map — erreur E-MAP-001"
            )
        return entry

    def _merge_mentions(
        self, split: str, record: dict[str, Any], doc_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        cached = self._merged_cache.get(doc_id)
        if cached is not None:
            return cached
        text = record["text"]
        annotations = record["annotations"]
        by_key: dict[tuple[int, int, str], list[tuple[str, dict[str, Any]]]] = {}
        annotator_ids: list[str] = []
        source_counts: Counter[str] = Counter()
        source_identifier_counts: Counter[str] = Counter()
        no_mask_counts: Counter[str] = Counter()
        all_mention_count = 0
        for annotator_id in sorted(annotations):
            annotator = annotations[annotator_id]
            if not isinstance(annotator_id, str) or not isinstance(annotator, dict):
                raise IngestionError(f"tab : {doc_id} : annotateur invalide : {annotator_id!r}")
            annotator_ids.append(annotator_id)
            mentions = annotator.get("entity_mentions")
            if not isinstance(mentions, list):
                raise IngestionError(
                    f"tab : {doc_id} : {annotator_id} : entity_mentions doit être une liste"
                )
            for mention_index, mention in enumerate(mentions, start=1):
                if not isinstance(mention, dict):
                    raise IngestionError(
                        f"tab : {doc_id} : {annotator_id} : mention {mention_index} invalide"
                    )
                required = (
                    "entity_type",
                    "entity_mention_id",
                    "start_offset",
                    "end_offset",
                    "span_text",
                    "identifier_type",
                    "entity_id",
                    "confidential_status",
                )
                missing = [field for field in required if field not in mention]
                if missing:
                    raise IngestionError(
                        f"tab : {doc_id} : {annotator_id} : mention {mention_index} "
                        f"champs manquants : {', '.join(missing)}"
                    )
                entity_type = mention["entity_type"]
                identifier_type = mention["identifier_type"]
                status = mention["confidential_status"]
                start = mention["start_offset"]
                end = mention["end_offset"]
                span = mention["span_text"]
                if not isinstance(entity_type, str) or not entity_type:
                    raise IngestionError(f"tab : {doc_id} : type d'entité invalide")
                if identifier_type not in self._ALLOWED_IDENTIFIER_TYPES:
                    raise IngestionError(
                        f"tab : {doc_id} : {entity_type} : identifier_type inconnu "
                        f"{identifier_type!r}"
                    )
                if status not in self._ALLOWED_STATUSES:
                    raise IngestionError(
                        f"tab : {doc_id} : {entity_type} : confidential_status inconnu "
                        f"{status!r}"
                    )
                if (
                    not isinstance(start, int)
                    or isinstance(start, bool)
                    or not isinstance(end, int)
                    or isinstance(end, bool)
                    or not isinstance(span, str)
                    or start < 0
                    or end <= start
                    or end > len(text)
                    or text[start:end] != span
                ):
                    raise IngestionError(
                        f"tab : {doc_id} : {annotator_id} : mention {mention_index} "
                        "offsets incohérents (E-VAL-101)"
                    )
                all_mention_count += 1
                source_counts[entity_type] += 1
                source_identifier_counts[identifier_type] += 1
                if identifier_type == "NO_MASK":
                    no_mask_counts[entity_type] += 1
                    continue
                by_key.setdefault((start, end, entity_type), []).append(
                    (annotator_id, mention)
                )

        merged: list[dict[str, Any]] = []
        for mention_index, (key, contributions) in enumerate(
            sorted(by_key.items()), start=1
        ):
            start, end, entity_type = key
            ordered = sorted(contributions, key=lambda item: item[0])
            canonical_annotator, canonical = ordered[0]
            source_types = sorted({item[1]["identifier_type"] for item in ordered})
            source_statuses = sorted({item[1]["confidential_status"] for item in ordered})
            # Union multi-annotateurs : le statut retenu est le plus sensible,
            # jamais le premier par ordre alphabétique — « NOT_CONFIDENTIAL »
            # précède « SEX », et le prendre effacerait la sensibilité déclarée
            # par un annotateur sur la même mention.
            effective_status = next(
                (status for status in source_statuses if status != "NOT_CONFIDENTIAL"),
                source_statuses[0],
            )
            effective_source_type = (
                "DIRECT" if "DIRECT" in source_types else source_types[0]
            )
            entry = self._entry(entity_type)
            output_identifier = IdentifierType.DIRECT if effective_source_type == "DIRECT" else IdentifierType.QUASI
            adjusted = False
            if output_identifier is IdentifierType.DIRECT and any(
                not code.startswith("DIR_") for code in entry.qi_categories
            ):
                # TAB has a few DIRECT flags on semantic types for which the
                # v2 taxonomy has no DIR_* counterpart. Preserve the raw flag
                # in meta, but obey I-ANN-3 instead of inventing a direct code.
                output_identifier = IdentifierType.QUASI
                adjusted = True
            source_entity_ids = sorted(
                {
                    str(item[1]["entity_id"])
                    for item in ordered
                    if item[1].get("entity_id") is not None
                }
            )
            canonical_entity_id = canonical.get("entity_id")
            output_entity_id = (
                f"{doc_id}:{canonical_annotator}:{canonical_entity_id}"
                if canonical_entity_id is not None
                else None
            )
            merged.append(
                {
                    "annotation_index": mention_index,
                    "start": start,
                    "end": end,
                    "span_text": text[start:end],
                    "entity_type": entity_type,
                    "entry": entry,
                    "identifier_type": output_identifier,
                    "source_identifier_types": source_types,
                    "identifier_type_adjusted": adjusted,
                    "confidential_status": effective_status,
                    "source_confidential_statuses": source_statuses,
                    "sensitivity": self._status_to_sensitivity(effective_status),
                    "annotator_id": canonical_annotator,
                    "annotators": [item[0] for item in ordered],
                    "entity_id": output_entity_id,
                    "source_entity_ids": source_entity_ids,
                    "source_mention_ids": [
                        str(item[1]["entity_mention_id"]) for item in ordered
                    ],
                }
            )

        audit = {
            "official_aggregation": "union",
            "annotator_ids": annotator_ids,
            "annotator_count": len(annotator_ids),
            "raw_mention_count": all_mention_count,
            "included_mention_count": len(merged),
            "union_collapsed_duplicates": all_mention_count
            - sum(no_mask_counts.values())
            - len(merged),
            "source_type_counts": dict(sorted(source_counts.items())),
            "source_identifier_type_counts": dict(sorted(source_identifier_counts.items())),
            "excluded_no_mask_counts": dict(sorted(no_mask_counts.items())),
            "excluded_no_mask_total": sum(no_mask_counts.values()),
            "entity_count": len({item["entity_id"] for item in merged if item["entity_id"]}),
            "task": record["task"],
            "source_meta": record["meta"],
            "quality_checked": record.get("quality_checked", []),
            "source_dataset_type": record.get("dataset_type", split),
        }
        result = (tuple(merged), audit)
        self._merged_cache[doc_id] = result
        return result

    # --- Normalisation ---------------------------------------------------- #

    def iter_documents(self, split: str) -> Iterator[Document]:
        for _position, record, doc_id in self._iter_records(split):
            _mentions, audit = self._merge_mentions(split, record, doc_id)
            meta = {
                "source_doc_id": record["doc_id"],
                "source_split": split,
                "task": record["task"],
                "source_meta": record["meta"],
                "quality_checked": record.get("quality_checked", []),
                "dataset_type": record.get("dataset_type", split),
                "official_aggregation": audit["official_aggregation"],
                "annotator_ids": audit["annotator_ids"],
                "annotator_count": audit["annotator_count"],
                "raw_mention_count": audit["raw_mention_count"],
                "included_mention_count": audit["included_mention_count"],
                "union_collapsed_duplicates": audit["union_collapsed_duplicates"],
                "source_type_counts": audit["source_type_counts"],
                "source_identifier_type_counts": audit["source_identifier_type_counts"],
                "excluded_no_mask_counts": audit["excluded_no_mask_counts"],
                "excluded_no_mask_total": audit["excluded_no_mask_total"],
                "entity_count": audit["entity_count"],
            }
            try:
                document = Document(
                    doc_id=doc_id,
                    dataset=self.key,
                    split=split,
                    domain=Domain.LEGAL,
                    language="en",
                    text=record["text"],
                    meta=meta,
                )
            except ValueError as exc:
                raise IngestionError(f"tab : {doc_id} : document invalide ({exc})") from exc
            yield document

    def iter_annotations(self, split: str) -> Iterator[Annotation]:
        for _position, record, doc_id in self._iter_records(split):
            mentions, _audit = self._merge_mentions(split, record, doc_id)
            for item in mentions:
                entry = item["entry"]
                annotation_meta = {
                    "source_entity_type": item["entity_type"],
                    "official_aggregation": "union",
                    "source_identifier_types": item["source_identifier_types"],
                    "source_confidential_statuses": item["source_confidential_statuses"],
                    "source_annotators": item["annotators"],
                    "source_mention_ids": item["source_mention_ids"],
                    "source_entity_ids": item["source_entity_ids"],
                    "tab_identifier_type": item["source_identifier_types"][0],
                    "tab_confidential_status": item["confidential_status"],
                }
                if item["identifier_type_adjusted"]:
                    annotation_meta["identifier_type_adjusted"] = {
                        "source": "DIRECT",
                        "reason": "aucun code DIR_* pour le type TAB",
                    }
                try:
                    annotation = Annotation(
                        annotation_id=f"{doc_id}:a{item['annotation_index']}",
                        doc_id=doc_id,
                        start=item["start"],
                        end=item["end"],
                        span_text=item["span_text"],
                        identifier_type=item["identifier_type"],
                        qi_categories=tuple(entry.qi_categories),
                        expression_mode=ExpressionMode.EXPLICIT,
                        sensitivity=item["sensitivity"],
                        granularity=entry.granularity,
                        stability=entry.stability,
                        subject=Subject.THIRD_PARTY,
                        entity_id=item["entity_id"],
                        annotator_id=item["annotator_id"],
                        meta=annotation_meta,
                    )
                except ValueError as exc:
                    raise IngestionError(
                        f"tab : {doc_id} : annotation {item['annotation_index']} invalide ({exc})"
                    ) from exc
                yield annotation

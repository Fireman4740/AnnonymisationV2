"""Adaptateur SPIA (Subject-level PII Inference Assessment).

SPIA publie deux JSONL : 144 documents issus de TAB et 531 documents issus de
PANORAMA. Une ligne contient un texte et la liste des sujets dont les PII ont
ete annotees. L'adaptateur conserve l'origine TAB/PANORAMA dans ``Document.meta``
et materialise les liens ``Document.subject_ids`` / ``Annotation.subject_id``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from anonymisation.datasets._local import fingerprint
from anonymisation.datasets.base import AcquisitionReport, DatasetAdapter
from anonymisation.datasets.ingest import IngestionError
from anonymisation.datasets.registry import UnmappedLabelError, register
from anonymisation.schema.models import (
    Annotation,
    AttributeValue,
    Document,
    Domain,
    Profile,
)
from anonymisation.schema.taxonomy import ExpressionMode, Subject


_DEFAULT_FILES: tuple[str, ...] = (
    "spia_tab_144.jsonl",
    "spia_panorama_531.jsonl",
)


@register
class SpiaAdapter(DatasetAdapter):
    """Normalise le format public ``maisonOP/spia`` vers SPEC-02 v2.1."""

    key = "spia"
    aliases = ("spia-benchmark",)
    streaming: ClassVar[bool] = False

    _TAG_SOURCE_TO_MANIFEST: ClassVar[dict[str, str]] = {
        "ID NUMBER": "ID_NUMBER",
        "DRIVER LICENSE": "DRIVER_LICENSE",
        "PHONE": "PHONE",
        "PASSPORT": "PASSPORT",
        "EMAIL": "EMAIL",
        "NAME": "NAME",
        "SEX": "SEX",
        "AGE": "AGE",
        "LOCATION": "LOCATION",
        "NATIONALITY": "NATIONALITY",
        "EDUCATION": "EDUCATION",
        "RELATIONSHIP": "RELATIONSHIP",
        "OCCUPATION": "OCCUPATION",
        "AFFILIATION": "AFFILIATION",
        "POSITION": "POSITION",
    }

    def _file_names(self) -> tuple[str, ...]:
        declared = tuple(self.manifest.source.files)
        return declared or _DEFAULT_FILES

    def _paths(self) -> tuple[Path, ...]:
        paths = tuple(self.raw_dir / name for name in self._file_names())
        missing = tuple(path for path in paths if not path.is_file())
        if missing:
            raise IngestionError(
                "spia : fichier(s) source manquant(s) : "
                + ", ".join(str(path) for path in missing)
            )
        return paths

    def download(self, *, force: bool = False) -> AcquisitionReport:
        """Verifie le cache local ; SPIA est redistribue, aucun telechargement implicite."""
        del force
        paths = self._paths()
        return AcquisitionReport(
            dataset=self.key,
            path=self.raw_dir,
            sha256=fingerprint(paths),
            bytes_downloaded=0,
            from_cache=True,
            revision=self.manifest.source.revision,
        )

    def _rows(self, split: str) -> Iterator[tuple[Path, int, dict[str, Any], str]]:
        if split not in ("all", "test"):
            raise IngestionError("spia : seul le split 'test' (ou 'all') est disponible")
        for path in self._paths():
            origin = "tab" if "tab" in path.stem.lower() else "panorama"
            with path.open(encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    if not raw_line.strip():
                        raise IngestionError(f"spia : {path}:{line_number} : ligne vide")
                    try:
                        row = json.loads(raw_line)
                    except json.JSONDecodeError as exc:
                        raise IngestionError(
                            f"spia : {path}:{line_number} : JSON invalide ({exc.msg})"
                        ) from exc
                    if not isinstance(row, dict):
                        raise IngestionError(
                            f"spia : {path}:{line_number} : la ligne doit etre un objet JSON"
                        )
                    metadata = row.get("metadata")
                    subjects = row.get("subjects")
                    text = row.get("text")
                    if not isinstance(metadata, dict) or not isinstance(text, str):
                        raise IngestionError(
                            f"spia : {path}:{line_number} : metadata/text absents ou invalides"
                        )
                    if not isinstance(subjects, list):
                        raise IngestionError(
                            f"spia : {path}:{line_number} : subjects doit etre une liste"
                        )
                    data_id = metadata.get("data_id", row.get("id"))
                    if data_id is None or not str(data_id):
                        raise IngestionError(
                            f"spia : {path}:{line_number} : metadata.data_id absent"
                        )
                    expected_subjects = metadata.get("number_of_subjects")
                    if expected_subjects is not None and expected_subjects != len(subjects):
                        raise IngestionError(
                            f"spia : {path}:{line_number} : data_id={data_id!r} : "
                            f"number_of_subjects={expected_subjects} != {len(subjects)}"
                        )
                    yield path, line_number, row, origin

    @staticmethod
    def _data_id(row: dict[str, Any]) -> str:
        metadata = row["metadata"]
        return str(metadata.get("data_id", row.get("id")))

    @staticmethod
    def _subject_id(data_id: str, subject: dict[str, Any]) -> str:
        if "id" not in subject:
            raise IngestionError(f"spia : data_id={data_id!r} : sujet sans id")
        return f"spia:{data_id}:subject:{subject['id']}"

    def _entry(self, path: Path, line_number: int, tag: str) -> Any:
        source_tag = tag.strip().upper()
        manifest_key = self._TAG_SOURCE_TO_MANIFEST.get(source_tag, source_tag)
        entry = self.manifest.label_map.get(manifest_key)
        if entry is None:
            raise UnmappedLabelError(
                f"spia : {path}:{line_number} : etiquette {tag!r} absente du label_map "
                "(E-MAP-001)"
            )
        return entry

    @staticmethod
    def _subjects(row: dict[str, Any], data_id: str) -> tuple[tuple[str, dict[str, Any]], ...]:
        values: list[tuple[str, dict[str, Any]]] = []
        for subject in row["subjects"]:
            if not isinstance(subject, dict):
                raise IngestionError(f"spia : data_id={data_id!r} : sujet malforme")
            subject_id = SpiaAdapter._subject_id(data_id, subject)
            values.append((subject_id, subject))
        return tuple(values)

    def iter_documents(self, split: str) -> Iterator[Document]:
        for path, line_number, row, origin in self._rows(split):
            data_id = self._data_id(row)
            subjects = self._subjects(row, data_id)
            doc_id = f"spia:{data_id}"
            try:
                yield Document(
                    doc_id=doc_id,
                    dataset=self.key,
                    split="test",
                    domain=Domain.LEGAL if origin == "tab" else Domain.FORUM,
                    language="en",
                    text=row["text"],
                    subject_ids=tuple(subject_id for subject_id, _ in subjects),
                    meta={
                        "source_corpus": origin,
                        "source_file": path.name,
                        "source_data_id": data_id,
                        "tab_overlap": origin == "tab",
                        "number_of_subjects": len(subjects),
                    },
                )
            except ValueError as exc:
                raise IngestionError(
                    f"spia : {path}:{line_number} : doc_id={doc_id} : document invalide ({exc})"
                ) from exc

    def iter_annotations(self, split: str) -> Iterator[Annotation]:
        for path, line_number, row, origin in self._rows(split):
            del origin
            data_id = self._data_id(row)
            doc_id = f"spia:{data_id}"
            text = row["text"]
            for subject_id, subject in self._subjects(row, data_id):
                piis = subject.get("PIIs", subject.get("piis"))
                if not isinstance(piis, list):
                    raise IngestionError(
                        f"spia : {path}:{line_number} : doc_id={doc_id} : "
                        f"subject_id={subject_id!r} : PIIs absent ou invalide"
                    )
                search_from = 0
                for pii_index, pii in enumerate(piis, start=1):
                    if not isinstance(pii, dict):
                        raise IngestionError(
                            f"spia : {path}:{line_number} : doc_id={doc_id} : "
                            f"PII {pii_index} malformee"
                        )
                    tag = pii.get("tag")
                    keyword = pii.get("keyword")
                    if not isinstance(tag, str) or not isinstance(keyword, str) or not keyword:
                        raise IngestionError(
                            f"spia : {path}:{line_number} : doc_id={doc_id} : "
                            f"PII {pii_index} tag/keyword invalide"
                        )
                    start = text.find(keyword, search_from)
                    if start < 0:
                        start = text.find(keyword)
                    if start < 0:
                        raise IngestionError(
                            f"spia : {path}:{line_number} : doc_id={doc_id} : "
                            f"keyword {keyword!r} absent du texte"
                        )
                    end = start + len(keyword)
                    search_from = end
                    entry = self._entry(path, line_number, tag)
                    certainty = pii.get("certainty")
                    hardness = pii.get("hardness")
                    if certainty is None:
                        confidence = 1.0
                    else:
                        try:
                            confidence = min(1.0, max(0.0, float(certainty) / 5.0))
                        except (TypeError, ValueError):
                            confidence = 1.0
                    try:
                        yield Annotation(
                            annotation_id=f"{doc_id}:{subject_id}:pii:{pii_index}",
                            doc_id=doc_id,
                            subject_id=subject_id,
                            start=start,
                            end=end,
                            span_text=keyword,
                            identifier_type=entry.identifier_type,
                            qi_categories=tuple(entry.qi_categories),
                            expression_mode=ExpressionMode.EXPLICIT,
                            granularity=entry.granularity,
                            stability=entry.stability,
                            subject=Subject.SELF,
                            value_normalized={
                                "source_tag": tag,
                                "certainty": certainty,
                                "hardness": hardness,
                                "value": keyword,
                            },
                            entity_id=f"{subject_id}:{tag.strip().upper()}:{keyword}",
                            confidence=confidence,
                            meta={"source_tag": tag, "source_file": path.name},
                        )
                    except ValueError as exc:
                        raise IngestionError(
                            f"spia : {path}:{line_number} : doc_id={doc_id} : "
                            f"annotation {pii_index} invalide ({exc})"
                        ) from exc

    def iter_profiles(self, split: str) -> Iterator[Profile]:
        seen: set[str] = set()
        for path, line_number, row, origin in self._rows(split):
            data_id = self._data_id(row)
            for subject_id, subject in self._subjects(row, data_id):
                if subject_id in seen:
                    continue
                seen.add(subject_id)
                attributes: dict[str, AttributeValue] = {}
                piis = subject.get("PIIs", subject.get("piis", []))
                if not isinstance(piis, list):
                    raise IngestionError(
                        f"spia : {path}:{line_number} : subject_id={subject_id!r} : PIIs invalide"
                    )
                for pii in piis:
                    if not isinstance(pii, dict) or not isinstance(pii.get("tag"), str):
                        raise IngestionError(
                            f"spia : {path}:{line_number} : subject_id={subject_id!r} : PII invalide"
                        )
                    tag = pii["tag"].strip().upper()
                    entry = self._entry(path, line_number, tag)
                    for category in entry.qi_categories:
                        attributes[category] = AttributeValue(
                            value=pii.get("keyword"),
                            normalized={"source_tag": pii["tag"]},
                        )
                yield Profile(
                    person_id=subject_id,
                    dataset=self.key,
                    population_id=f"spia-{origin}",
                    attributes=attributes,
                    meta={
                        "source_corpus": origin,
                        "description": subject.get("description"),
                    },
                )

    def overlap_tab_ids(self) -> tuple[str, ...]:
        """Retourne les identifiants SPIA dont la source est TAB."""
        ids = {f"spia:{self._data_id(row)}" for _, _, row, origin in self._rows("all") if origin == "tab"}
        return tuple(sorted(ids))

    def describe(self) -> dict[str, Any]:
        result = super().describe()
        result.update(
            {
                "multi_subject": True,
                "tab_overlap_exposed": True,
                "tab_overlap_source_files": [name for name in self._file_names() if "tab" in name],
            }
        )
        return result

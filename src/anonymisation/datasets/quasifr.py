"""Adaptateur du corpus QI français ``quasifr``.

La source V1 contient trois JSON dont la racine est ``{"examples": [...]}``.
Un fichier devient un split pivot afin de conserver la structure publiée ; les
identifiants sont préfixés par le nom du fichier car ``ticket_001`` existe dans
plusieurs variantes.

La normalisation est explicite :

* les offsets cohérents sont conservés ;
* un offset incohérent est ré-ancré uniquement si ``annotation.text`` apparaît
  exactement une fois dans le document ;
* un texte absent ou ambigu n'est pas deviné : l'annotation est écartée et le
  document porte une trace ``dropped_annotations`` ;
* les types techniques et ``COREF`` sont conservés comme ``IGNORED``. Ils sont
  hors périmètre QI mais restent visibles dans le pivot.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _Offset:
    start: int
    end: int
    repaired: bool = False


@register
class QuasifrAdapter(DatasetAdapter):
    """Normalise les exemples QI français annotés."""

    key = "quasifr"
    aliases = ("quasi-fr", "quasi_fr")
    streaming: ClassVar[bool] = False

    _SPLIT_FILES: ClassVar[dict[str, str]] = {
        "anonymization": "anonymization_dataset.json",
        "hard_quasi_id": "hard_quasi_id_dataset.json",
        "max_anonymization": "max_anonymization_dataset.json",
    }

    # Les labels source sans équivalent QI restent dans le pivot sous le code
    # de service IGNORED. Ce n'est pas une approximation vers OTHER_QI.
    _IGNORED_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "COREF",
            "ERROR_CODE",
            "PATH",
            "STYLE",
            "PRODUCT",
            "API",
            "TOOL",
            "CONFIG",
            "MODEL",
            "PROJECT",
            "LICENSE",
        }
    )

    def __init__(self, manifest: Any, raw_dir: Path) -> None:
        super().__init__(manifest, raw_dir)
        self._file_cache: dict[Path, tuple[dict[str, Any], ...]] = {}

    # --- Acquisition ------------------------------------------------------ #

    def _source_files(self) -> tuple[Path, ...]:
        source = self.manifest.source
        directory = resolve_source_dir(source)
        paths = check_files(directory, source.files)
        by_name = {path.name: path for path in paths}
        missing = [name for name in self._SPLIT_FILES.values() if name not in by_name]
        if missing:
            raise IngestionError(
                "quasifr : fichiers déclarés absents de la source locale : "
                + ", ".join(missing)
            )
        return tuple(by_name[name] for name in self._SPLIT_FILES.values())

    def download(self, *, force: bool = False) -> AcquisitionReport:
        """Vérifie la source locale ; aucun téléchargement n'est nécessaire."""

        del force  # Une source locale ne possède pas de cache téléchargeable.
        paths = self._source_files()
        digest = fingerprint(paths)
        expected = self.manifest.integrity.sha256
        if expected is not None and expected != digest:
            raise IngestionError(
                "quasifr : empreinte de la source différente du manifeste : "
                f"attendu {expected}, obtenu {digest}"
            )
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        return AcquisitionReport(
            dataset=self.key,
            path=self.raw_dir,
            sha256=digest,
            bytes_downloaded=0,
            from_cache=True,
            revision=None,
        )

    # --- Source parsing --------------------------------------------------- #

    def _path_for_split(self, split: str) -> Path:
        try:
            filename = self._SPLIT_FILES[split]
        except KeyError as exc:
            raise IngestionError(
                f"quasifr : split inconnu {split!r} ; attendus : "
                f"{', '.join(self._SPLIT_FILES)}"
            ) from exc
        paths = self._source_files()
        for path in paths:
            if path.name == filename:
                return path
        raise IngestionError(f"quasifr : fichier du split {split!r} introuvable : {filename}")

    def _load_examples(self, path: Path) -> tuple[dict[str, Any], ...]:
        cached = self._file_cache.get(path)
        if cached is not None:
            return cached
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise IngestionError(f"quasifr : lecture impossible de {path} : {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("examples"), list):
            raise IngestionError(
                f"quasifr : {path} doit être un objet JSON avec une liste `examples`"
            )
        examples: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, example in enumerate(payload["examples"], start=1):
            if not isinstance(example, dict):
                raise IngestionError(f"quasifr : {path} : example {index} n'est pas un objet")
            required = ("id", "langue", "original_text", "annotations")
            missing = [name for name in required if name not in example]
            if missing:
                raise IngestionError(
                    f"quasifr : {path} : example {index} : champs manquants : "
                    + ", ".join(missing)
                )
            raw_id = example["id"]
            if not isinstance(raw_id, str) or not raw_id:
                raise IngestionError(
                    f"quasifr : {path} : example {index} : id doit être une chaîne non vide"
                )
            if raw_id in seen_ids:
                raise IngestionError(
                    f"quasifr : {path} : id dupliqué dans le fichier : {raw_id!r}"
                )
            seen_ids.add(raw_id)
            if not isinstance(example["langue"], str) or not example["langue"]:
                raise IngestionError(
                    f"quasifr : {path} : {raw_id} : langue invalide"
                )
            if not isinstance(example["original_text"], str):
                raise IngestionError(
                    f"quasifr : {path} : {raw_id} : original_text doit être une chaîne"
                )
            if not isinstance(example["annotations"], list):
                raise IngestionError(
                    f"quasifr : {path} : {raw_id} : annotations doit être une liste"
                )
            examples.append(example)
        result = tuple(examples)
        self._file_cache[path] = result
        return result

    def _iter_examples(self, split: str) -> Iterator[tuple[Path, int, dict[str, Any], str]]:
        path = self._path_for_split(split)
        stem = path.stem.removesuffix("_dataset")
        for position, example in enumerate(self._load_examples(path), start=1):
            doc_id = f"{self.key}:{stem}:{example['id']}"
            yield path, position, example, doc_id

    @staticmethod
    def _source_meta(
        path: Path,
        position: int,
        example: dict[str, Any],
        audit: dict[str, Any],
    ) -> dict[str, Any]:
        preserved = {
            key: value
            for key, value in example.items()
            if key not in {"id", "langue", "original_text", "annotations"}
        }
        return {
            "source_file": path.name,
            "source_position": position,
            "source_id": example["id"],
            "source_language": example["langue"],
            "source_fields": preserved,
            "annotation_counts": audit["annotation_counts"],
            "emitted_annotation_counts": audit["emitted_annotation_counts"],
            "ignored_annotation_counts": audit["ignored_annotation_counts"],
            "repaired_offsets": audit["repaired_offsets"],
            "dropped_annotations": audit["dropped_annotations"],
        }

    # --- Mapping and offsets ---------------------------------------------- #

    def _mapping(self, label: str, risk_note: str | None) -> Any:
        entry = self.manifest.label_map.get(label)
        if entry is None:
            raise UnmappedLabelError(
                f"quasifr : label {label!r} absent du label_map — erreur E-MAP-001"
            )

        # ID est un label source hétérogène : les quatre formes connues sont
        # distinguées par leur justification, sans inventer une catégorie pour
        # une note inconnue.
        if label == "ID":
            note = (risk_note or "").casefold()
            if "contrat" in note:
                code = "DIR_CASE_REF"
            elif "compte" in note or "cb" in note or "carte" in note:
                code = "DIR_ACCOUNT"
            elif "session" in note:
                code = "DIR_ONLINE_ID"
            else:
                code = entry.qi_categories[0]
            from types import SimpleNamespace

            return SimpleNamespace(
                identifier_type=entry.identifier_type,
                qi_categories=(code,),
                granularity=entry.granularity,
                stability=entry.stability,
            )
        return entry

    @staticmethod
    def _find_unique(text: str, span: str) -> list[int]:
        if not span:
            return []
        positions: list[int] = []
        cursor = 0
        while True:
            position = text.find(span, cursor)
            if position < 0:
                return positions
            positions.append(position)
            cursor = position + 1

    def _offset(
        self,
        text: str,
        annotation: dict[str, Any],
        path: Path,
        doc_id: str,
        index: int,
    ) -> tuple[_Offset | None, dict[str, Any] | None]:
        required = ("type", "start", "end", "text")
        missing = [key for key in required if key not in annotation]
        if missing:
            raise IngestionError(
                f"quasifr : {path} : {doc_id} : annotation {index} : "
                f"champs manquants : {', '.join(missing)}"
            )
        label = annotation["type"]
        span = annotation["text"]
        start = annotation["start"]
        end = annotation["end"]
        if not isinstance(label, str) or not label:
            raise IngestionError(
                f"quasifr : {path} : {doc_id} : annotation {index} : type invalide"
            )
        if not isinstance(span, str) or not span:
            raise IngestionError(
                f"quasifr : {path} : {doc_id} : annotation {index} : text invalide"
            )
        if not isinstance(start, int) or isinstance(start, bool):
            raise IngestionError(
                f"quasifr : {path} : {doc_id} : annotation {index} : start invalide"
            )
        if not isinstance(end, int) or isinstance(end, bool):
            raise IngestionError(
                f"quasifr : {path} : {doc_id} : annotation {index} : end invalide"
            )
        if 0 <= start < end <= len(text) and text[start:end] == span:
            return _Offset(start, end), None

        matches = self._find_unique(text, span)
        if len(matches) == 1:
            repaired_start = matches[0]
            return (
                _Offset(repaired_start, repaired_start + len(span), repaired=True),
                None,
            )
        reason = "texte introuvable" if not matches else "texte présent plusieurs fois"
        return None, {
            "index": index,
            "type": label,
            "text": span,
            "original_start": start,
            "original_end": end,
            "reason": reason,
        }

    def _audit_and_plans(
        self,
        path: Path,
        position: int,
        example: dict[str, Any],
        doc_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        text = example["original_text"]
        counts: Counter[str] = Counter()
        emitted: Counter[str] = Counter()
        ignored: Counter[str] = Counter()
        repaired: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []
        plans: list[dict[str, Any]] = []

        for index, raw_annotation in enumerate(example["annotations"], start=1):
            if not isinstance(raw_annotation, dict):
                raise IngestionError(
                    f"quasifr : {path} : {doc_id} : annotation {index} n'est pas un objet"
                )
            label = raw_annotation.get("type")
            if isinstance(label, str):
                counts[label] += 1
            offset, drop = self._offset(text, raw_annotation, path, doc_id, index)
            if drop is not None:
                dropped.append(drop)
                continue
            assert offset is not None
            note = raw_annotation.get("risk_note")
            if note is not None and not isinstance(note, str):
                raise IngestionError(
                    f"quasifr : {path} : {doc_id} : annotation {index} : risk_note invalide"
                )
            mapping = self._mapping(label, note)
            emitted[label] += 1
            if mapping.identifier_type is IdentifierType.IGNORED:
                ignored[label] += 1
            if offset.repaired:
                repaired.append(
                    {
                        "index": index,
                        "type": label,
                        "original_start": raw_annotation["start"],
                        "original_end": raw_annotation["end"],
                        "new_start": offset.start,
                        "new_end": offset.end,
                    }
                )
            plans.append(
                {
                    "index": index,
                    "raw": raw_annotation,
                    "offset": offset,
                    "mapping": mapping,
                }
            )

        audit = {
            "annotation_counts": dict(sorted(counts.items())),
            "emitted_annotation_counts": dict(sorted(emitted.items())),
            "ignored_annotation_counts": dict(sorted(ignored.items())),
            "repaired_offsets": repaired,
            "dropped_annotations": dropped,
        }
        meta = self._source_meta(path, position, example, audit)
        return meta, {"plans": plans, "audit": audit}

    @staticmethod
    def _expression_mode(label: str, risk_note: str | None) -> ExpressionMode:
        if label == "DATE_REL":
            return ExpressionMode.NON_STANDARD
        note = (risk_note or "").casefold()
        implicit_markers = (
            "déduction",
            "indirect",
            "unique",
            "rare",
            "spécifique",
            "combinaison",
            "local",
            "seule",
        )
        if label == "QUASI_ID" and any(marker in note for marker in implicit_markers):
            return ExpressionMode.IMPLICIT
        return ExpressionMode.EXPLICIT

    @staticmethod
    def _sensitivity(risk_note: str | None) -> Sensitivity:
        note = (risk_note or "").casefold()
        if any(word in note for word in ("maladie", "blessure", "médical", "pathologie")):
            return Sensitivity.HEALTH
        if any(word in note for word in ("sexuel", "sexuelle", "orientation sexuelle")):
            return Sensitivity.SEXLIFE
        if any(word in note for word in ("judiciaire", "plainte", "procédure")):
            return Sensitivity.JUDICIAL
        return Sensitivity.NONE

    # --- Normalisation ---------------------------------------------------- #

    def iter_documents(self, split: str) -> Iterator[Document]:
        for path, position, example, doc_id in self._iter_examples(split):
            meta, _ = self._audit_and_plans(path, position, example, doc_id)
            try:
                document = Document(
                    doc_id=doc_id,
                    dataset=self.key,
                    split=split,
                    domain=Domain.GENERIC,
                    language=example["langue"].casefold(),
                    text=example["original_text"],
                    meta=meta,
                )
            except ValueError as exc:
                raise IngestionError(
                    f"quasifr : {path} : {doc_id} : document invalide ({exc})"
                ) from exc
            yield document

    def iter_annotations(self, split: str) -> Iterator[Annotation]:
        for path, position, example, doc_id in self._iter_examples(split):
            _meta, result = self._audit_and_plans(path, position, example, doc_id)
            for plan in result["plans"]:
                raw = plan["raw"]
                mapping = plan["mapping"]
                offset: _Offset = plan["offset"]
                label = raw["type"]
                note = raw.get("risk_note")
                annotation_meta: dict[str, Any] = {
                    "source_type": label,
                    "source_annotation_index": plan["index"],
                    "risk_note": note,
                    "replacement_suggestion": raw.get("replacement"),
                }
                if raw.get("coref_id") is not None:
                    annotation_meta["source_coref_id"] = raw["coref_id"]
                if offset.repaired:
                    annotation_meta["offset_repaired"] = True
                    annotation_meta["offset_original"] = {
                        "start": raw["start"],
                        "end": raw["end"],
                    }
                try:
                    annotation = Annotation(
                        annotation_id=f"{doc_id}:a{plan['index']}",
                        doc_id=doc_id,
                        start=offset.start,
                        end=offset.end,
                        span_text=raw["text"],
                        identifier_type=mapping.identifier_type,
                        qi_categories=tuple(mapping.qi_categories),
                        expression_mode=self._expression_mode(label, note),
                        sensitivity=self._sensitivity(note),
                        granularity=mapping.granularity,
                        stability=mapping.stability,
                        subject=Subject.SELF,
                        entity_id=raw.get("coref_id"),
                        meta=annotation_meta,
                    )
                except ValueError as exc:
                    raise IngestionError(
                        f"quasifr : {path} : {doc_id} : annotation {plan['index']} "
                        f"invalide ({exc})"
                    ) from exc
                yield annotation

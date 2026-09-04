"""Adaptateur de la release synthétique PersonalReddit.

Les fichiers ``train.jsonl`` et ``test.jsonl`` sont des partitions de source,
non des partitions par auteur : les mêmes 40 profils apparaissent dans les
deux. L'adaptateur dérive donc un ``person_id`` du JSON canonique de
``personality`` puis applique l'algorithme de split groupé de SPEC-04 §9.
La partition d'origine est conservée dans ``Document.meta.source_split``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from anonymisation.datasets._local import check_files, fingerprint, resolve_source_dir
from anonymisation.datasets._split import assign_split
from anonymisation.datasets.base import AcquisitionReport, DatasetAdapter
from anonymisation.datasets.ingest import IngestionError
from anonymisation.datasets.registry import register
from anonymisation.schema.models import (
    Annotation,
    AttributeValue,
    Document,
    Domain,
    LabelType,
    Profile,
    TaskLabel,
)
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Sensitivity,
    Stability,
    Subject,
)


@dataclass(frozen=True)
class _Row:
    path: Path
    line_no: int
    source_split: str
    doc_id: str
    person_id: str
    pivot_split: str
    payload: dict[str, Any]


@register
class PersonalRedditAdapter(DatasetAdapter):
    """Normalise les exemples synthétiques d'inférence d'attributs."""

    key = "personalreddit"
    aliases = ("personal-reddit",)
    streaming: ClassVar[bool] = False

    _SOURCE_FILES: ClassVar[dict[str, str]] = {
        "train": "train.jsonl",
        "test": "test.jsonl",
    }
    _PERSONALITY_FIELDS: ClassVar[tuple[str, ...]] = (
        "age",
        "sex",
        "city_country",
        "birth_city_country",
        "education",
        "occupation",
        "income",
        "income_level",
        "relationship_status",
    )
    _REQUIRED_FIELDS: ClassVar[tuple[str, ...]] = (
        "feature",
        "guess",
        "guess_correctness",
        "hardness",
        "label",
        "personality",
        "question_asked",
        "response",
    )
    _ATTRIBUTE_MAP: ClassVar[dict[str, tuple[str, Granularity, Stability]]] = {
        "age": ("GEN_AGE", Granularity.EXACT, Stability.STABLE),
        "sex": ("GEN_GENDER", Granularity.COARSE, Stability.STABLE),
        "city_country": ("GEN_GEO", Granularity.COARSE, Stability.VOLATILE),
        "birth_city_country": ("GEN_GEO", Granularity.COARSE, Stability.STABLE),
        "education": ("GEN_EDUCATION", Granularity.COARSE, Stability.STABLE),
        "occupation": ("GEN_OCCUPATION", Granularity.COARSE, Stability.VOLATILE),
        "income": ("GEN_SOCIOECON", Granularity.EXACT, Stability.VOLATILE),
        "income_level": ("GEN_SOCIOECON", Granularity.COARSE, Stability.STABLE),
        "relationship_status": ("GEN_FAMILY", Granularity.COARSE, Stability.STABLE),
    }

    def __init__(self, manifest: Any, raw_dir: Path) -> None:
        super().__init__(manifest, raw_dir)
        self._rows_cache: tuple[_Row, ...] | None = None

    # --- Acquisition ------------------------------------------------------ #

    def _source_files(self) -> dict[str, Path]:
        directory = resolve_source_dir(self.manifest.source)
        paths = check_files(directory, self.manifest.source.files)
        by_name = {path.name: path for path in paths}
        missing = [name for name in self._SOURCE_FILES.values() if name not in by_name]
        if missing:
            raise IngestionError(
                "personalreddit : fichiers déclarés absents : " + ", ".join(missing)
            )
        return {
            source_split: by_name[filename]
            for source_split, filename in self._SOURCE_FILES.items()
        }

    def download(self, *, force: bool = False) -> AcquisitionReport:
        """Vérifie la copie locale et retourne son empreinte déterministe."""

        del force
        paths = tuple(self._source_files().values())
        digest = fingerprint(paths)
        expected = self.manifest.integrity.sha256
        if expected is not None and expected != digest:
            raise IngestionError(
                "personalreddit : empreinte différente du manifeste : "
                f"attendu {expected}, obtenu {digest}"
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

    # --- Configuration du split ------------------------------------------ #

    def _split_config(self) -> tuple[int, dict[str, float]]:
        seed = self.manifest.source.seed
        annotation = self.manifest.annotation or {}
        ratios = annotation.get("split_ratios")
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise IngestionError(
                "personalreddit : source.seed doit déclarer la graine entière du split"
            )
        if not isinstance(ratios, dict) or not ratios:
            raise IngestionError(
                "personalreddit : annotation.split_ratios doit déclarer les ratios"
            )
        try:
            normalized = {str(name): float(value) for name, value in ratios.items()}
        except (TypeError, ValueError) as exc:
            raise IngestionError(
                "personalreddit : annotation.split_ratios contient une valeur invalide"
            ) from exc
        expected = set(self.manifest.structure.splits)
        if set(normalized) != expected:
            raise IngestionError(
                "personalreddit : split_ratios et structure.splits divergent : "
                f"{sorted(normalized)} != {sorted(expected)}"
            )
        return seed, normalized

    @staticmethod
    def _canonical_personality(personality: dict[str, Any]) -> str:
        return json.dumps(
            personality,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @classmethod
    def _person_id(cls, personality: dict[str, Any]) -> str:
        digest = hashlib.sha256(cls._canonical_personality(personality).encode("utf-8")).hexdigest()
        return f"{cls.key}:person:{digest}"

    def _validate_row(
        self, path: Path, line_no: int, row: Any, source_split: str
    ) -> dict[str, Any]:
        if not isinstance(row, dict):
            raise IngestionError(
                f"personalreddit : {path}:{line_no} : ligne non-objet JSON"
            )
        missing = [field for field in self._REQUIRED_FIELDS if field not in row]
        if missing:
            raise IngestionError(
                f"personalreddit : {path}:{line_no} : champs manquants : "
                + ", ".join(missing)
            )
        for field in ("feature", "question_asked", "response", "label", "guess"):
            if not isinstance(row[field], str):
                raise IngestionError(
                    f"personalreddit : {path}:{line_no} : {field} doit être une chaîne"
                )
        if not isinstance(row["personality"], dict):
            raise IngestionError(
                f"personalreddit : {path}:{line_no} : personality doit être un objet"
            )
        missing_personality = [
            field for field in self._PERSONALITY_FIELDS if field not in row["personality"]
        ]
        if missing_personality:
            raise IngestionError(
                f"personalreddit : {path}:{line_no} : attributs personality manquants : "
                + ", ".join(missing_personality)
            )
        if set(row["personality"]) != set(self._PERSONALITY_FIELDS):
            extra = sorted(set(row["personality"]) - set(self._PERSONALITY_FIELDS))
            raise IngestionError(
                f"personalreddit : {path}:{line_no} : attributs personality inconnus : {extra}"
            )
        if not isinstance(row["hardness"], int) or isinstance(row["hardness"], bool):
            raise IngestionError(
                f"personalreddit : {path}:{line_no} : hardness doit être un entier"
            )
        if not 1 <= row["hardness"] <= 5:
            raise IngestionError(
                f"personalreddit : {path}:{line_no} : hardness hors intervalle [1, 5]"
            )
        if not isinstance(row["guess_correctness"], dict):
            raise IngestionError(
                f"personalreddit : {path}:{line_no} : guess_correctness doit être un objet"
            )
        if source_split not in self._SOURCE_FILES:
            raise IngestionError(f"personalreddit : split source inconnu {source_split!r}")
        if row["feature"] not in self._ATTRIBUTE_MAP:
            raise IngestionError(
                f"personalreddit : {path}:{line_no} : feature non mappée : {row['feature']!r}"
            )
        return row

    def _load_rows(self) -> tuple[_Row, ...]:
        if self._rows_cache is not None:
            return self._rows_cache
        seed, ratios = self._split_config()
        rows: list[_Row] = []
        for source_split, path in self._source_files().items():
            try:
                handle = path.open("r", encoding="utf-8")
            except OSError as exc:
                raise IngestionError(f"personalreddit : lecture impossible de {path} : {exc}") from exc
            with handle:
                for line_no, line in enumerate(handle, start=1):
                    if not line.strip():
                        raise IngestionError(f"personalreddit : {path}:{line_no} : ligne vide")
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise IngestionError(
                            f"personalreddit : {path}:{line_no} : JSON invalide ({exc.msg})"
                        ) from exc
                    row = self._validate_row(path, line_no, raw, source_split)
                    person_id = self._person_id(row["personality"])
                    pivot_split = assign_split(person_id, seed, ratios)
                    rows.append(
                        _Row(
                            path=path,
                            line_no=line_no,
                            source_split=source_split,
                            doc_id=f"{self.key}:{source_split}:{line_no}",
                            person_id=person_id,
                            pivot_split=pivot_split,
                            payload=row,
                        )
                    )
        self._rows_cache = tuple(rows)
        return self._rows_cache

    def _rows_for_split(self, split: str) -> tuple[_Row, ...]:
        if split not in self.manifest.structure.splits:
            raise IngestionError(
                f"personalreddit : split inconnu {split!r} ; attendus : "
                f"{', '.join(self.manifest.structure.splits)}"
            )
        return tuple(row for row in self._load_rows() if row.pivot_split == split)

    @staticmethod
    def _document_meta(row: _Row, seed: int, ratios: dict[str, float]) -> dict[str, Any]:
        payload = row.payload
        return {
            "source_file": row.path.name,
            "source_line": row.line_no,
            "source_split": row.source_split,
            "split_algorithm": "blake2b(f'{seed}:{person_id}', digest_size=8)",
            "split_seed": seed,
            "split_ratios": ratios,
            "feature": payload["feature"],
            "label": payload["label"],
            "hardness": payload["hardness"],
            "question_asked": payload["question_asked"],
            "guess": payload["guess"],
            "guess_correctness": payload["guess_correctness"],
            "source_personality": payload["personality"],
        }

    # --- Profils ---------------------------------------------------------- #

    def _profile_records(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for row in self._load_rows():
            previous = records.get(row.person_id)
            if previous is None:
                records[row.person_id] = {
                    "personality": row.payload["personality"],
                    "source_splits": {row.source_split},
                    "pivot_split": row.pivot_split,
                }
            else:
                previous["source_splits"].add(row.source_split)
                if previous["pivot_split"] != row.pivot_split:
                    raise IngestionError(
                        f"personalreddit : profil {row.person_id} affecté à deux splits"
                    )
        return records

    @classmethod
    def _profile_attributes(cls, personality: dict[str, Any]) -> dict[str, AttributeValue]:
        # Deux paires de champs source partagent un code SPEC-01. Les valeurs
        # sont regroupées dans une seule AttributeValue ; aucune des 9 valeurs
        # n'est écrasée, et la copie complète reste dans Profile.meta.
        return {
            "GEN_AGE": AttributeValue(
                value=personality["age"], normalized={"source_attribute": "age"}
            ),
            "GEN_GENDER": AttributeValue(
                value=personality["sex"], normalized={"source_attribute": "sex"}
            ),
            "GEN_GEO": AttributeValue(
                value={
                    "current": personality["city_country"],
                    "birth": personality["birth_city_country"],
                },
                normalized={
                    "current": personality["city_country"],
                    "birth": personality["birth_city_country"],
                },
            ),
            "GEN_EDUCATION": AttributeValue(
                value=personality["education"], normalized={"source_attribute": "education"}
            ),
            "GEN_OCCUPATION": AttributeValue(
                value=personality["occupation"], normalized={"source_attribute": "occupation"}
            ),
            "GEN_SOCIOECON": AttributeValue(
                value={
                    "income": personality["income"],
                    "income_level": personality["income_level"],
                },
                normalized={
                    "income": personality["income"],
                    "income_level": personality["income_level"],
                },
            ),
            "GEN_FAMILY": AttributeValue(
                value=personality["relationship_status"],
                normalized={"source_attribute": "relationship_status"},
            ),
        }

    def iter_profiles(self, split: str) -> Iterator[Profile]:
        seed, ratios = self._split_config()
        population_id = self.manifest.population.population_id
        if population_id is None:
            raise IngestionError(
                "personalreddit : population.population_id est requis pour les profils"
            )
        for person_id, record in self._profile_records().items():
            if record["pivot_split"] != split:
                continue
            personality = record["personality"]
            try:
                profile = Profile(
                    person_id=person_id,
                    dataset=self.key,
                    population_id=population_id,
                    attributes=self._profile_attributes(personality),
                    meta={
                        "source_personality": personality,
                        "source_splits": sorted(record["source_splits"]),
                        "pivot_split": split,
                        "split_seed": seed,
                        "split_ratios": ratios,
                        "attribute_mapping": {
                            field: self._ATTRIBUTE_MAP[field][0]
                            for field in self._PERSONALITY_FIELDS
                        },
                    },
                )
            except ValueError as exc:
                raise IngestionError(
                    f"personalreddit : profil {person_id} invalide ({exc})"
                ) from exc
            yield profile

    # --- Documents, annotations, tasks ----------------------------------- #

    def iter_documents(self, split: str) -> Iterator[Document]:
        seed, ratios = self._split_config()
        for row in self._rows_for_split(split):
            try:
                document = Document(
                    doc_id=row.doc_id,
                    dataset=self.key,
                    split=split,
                    domain=Domain.FORUM,
                    language="en",
                    text=row.payload["response"],
                    author_id=row.person_id,
                    subject_ids=(row.person_id,),
                    meta=self._document_meta(row, seed, ratios),
                )
            except ValueError as exc:
                raise IngestionError(
                    f"personalreddit : {row.path}:{row.line_no} : {row.doc_id} : "
                    f"document invalide ({exc})"
                ) from exc
            yield document

    def iter_annotations(self, split: str) -> Iterator[Annotation]:
        for row in self._rows_for_split(split):
            feature = row.payload["feature"]
            code, granularity, stability = self._ATTRIBUTE_MAP[feature]
            try:
                annotation = Annotation(
                    annotation_id=f"{row.doc_id}:a1",
                    doc_id=row.doc_id,
                    subject_id=row.person_id,
                    identifier_type=IdentifierType.QUASI,
                    qi_categories=(code,),
                    expression_mode=ExpressionMode.IMPLICIT,
                    granularity=granularity,
                    stability=stability,
                    sensitivity=Sensitivity.NONE,
                    subject=Subject.SELF,
                    value_normalized={
                        "source_attribute": feature,
                        "value": row.payload["personality"][feature],
                    },
                    meta={
                        "source_feature": feature,
                        "source_label": row.payload["label"],
                        "source_split": row.source_split,
                        "inference_level": "document",
                    },
                )
            except ValueError as exc:
                raise IngestionError(
                    f"personalreddit : {row.path}:{row.line_no} : {row.doc_id} : "
                    f"annotation invalide ({exc})"
                ) from exc
            yield annotation

    def iter_tasks(self, split: str) -> Iterator[TaskLabel]:
        for row in self._rows_for_split(split):
            try:
                task = TaskLabel(
                    doc_id=row.doc_id,
                    task="personality_prediction",
                    label=row.payload["label"],
                    label_type=LabelType.SINGLE,
                    meta={
                        "feature": row.payload["feature"],
                        "source_split": row.source_split,
                        "guess": row.payload["guess"],
                        "guess_correctness": row.payload["guess_correctness"],
                    },
                )
            except ValueError as exc:
                raise IngestionError(
                    f"personalreddit : {row.path}:{row.line_no} : {row.doc_id} : "
                    f"task invalide ({exc})"
                ) from exc
            yield task

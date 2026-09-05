"""Pipeline d'ingestion en 5 étapes (SPEC-04).

```
ACQUIRE → PARSE → NORMALIZE → VALIDATE → PUBLISH
source   → objets bruts → objets SPEC-02 → invariants → data/processed/
```

L'adaptateur connaît le format source, le pipeline connaît SPEC-01/SPEC-02.
Chaque étape a une sortie inspectable et peut être relancée seule.

Règle d'or : une violation bloquante de validation **échoue** l'ingestion —
elle n'est jamais journalisée en avertissement (SPEC-04 §5). La volumétrie
observée est contrôlée **par le pipeline** (G5, SPEC-03) pour déterminer le
statut, car ``E-VAL-109`` n'est qu'un avertissement dans le rapport.

Déterminisme (SPEC-04 §9) : aucun horodatage dans les données — la date va
uniquement dans le lock ; la réingestion produit des fichiers identiques bit
à bit (test de non-régression, SPEC-09 §3.3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from itertools import islice
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from anonymisation.datasets._local import (
    LocalSourceError,
    SourceResolution,
    resolve_local_source,
)
from anonymisation.datasets.base import DatasetAdapter
from anonymisation.datasets.manifest import DatasetManifest
from anonymisation.schema.io import read_jsonl, sha256_file, write_json, write_jsonl
from anonymisation.schema.models import (
    SCHEMA_VERSION,
    Annotation,
    Combination,
    Document,
    Organization,
    Profile,
    TaskLabel,
)
from anonymisation.schema.taxonomy import TAXONOMY_VERSION
from anonymisation.schema.validation import ValidationIssue, ValidationReport, validate_dataset

__all__ = [
    "LOCK_NAME",
    "TABLES",
    "TABLE_MODELS",
    "VALIDATION_NAME",
    "IngestionError",
    "IngestionResult",
    "LocalSourceError",
    "LockIncompatibleError",
    "check_lock_compatibility",
    "ingest",
    "validate_streaming_output",
]


class IngestionError(ValueError):
    """Échec du pipeline d'ingestion (E-ING-*) — message actionnable."""


class LockIncompatibleError(ValueError):
    """Lock incompatible avec la taxonomie courante — réingestion requise."""


#: Tables du format pivot : nom → modèle SPEC-02, dans l'ordre d'écriture.
#: Source unique de vérité — la collecte (``iter_<table>`` de l'adaptateur),
#: l'écriture, la relecture et la validation en dérivent toutes.
TABLE_MODELS: dict[str, type[BaseModel]] = {
    "documents": Document,
    "annotations": Annotation,
    "profiles": Profile,
    "organizations": Organization,
    "combinations": Combination,
    "tasks": TaskLabel,
}

#: Noms des tables, dans l'ordre d'écriture (SPEC-02 §2).
TABLES: tuple[str, ...] = tuple(TABLE_MODELS)

#: Fichiers annexes écrits par :func:`ingest` dans ``data/processed/<clé>/``.
LOCK_NAME = ".manifest.lock.json"
VALIDATION_NAME = ".validation.json"


@dataclass(frozen=True)
class IngestionResult:
    """Résultat d'une ingestion : statut, comptes, empreintes, chemins.

    ``counts`` est le ``counts`` du rapport de validation — les dénominateurs
    des métriques déclinées de SPEC-07. ``files`` mappe chaque chemin relatif
    de table écrite vers son sha256 (reprise du lock, pour les tests de
    non-régression).
    """

    dataset: str
    split: str
    status: str  # "official" | "sampled" | "diagnostic"
    counts: dict[str, Any]
    files: dict[str, str]
    lock_path: Path
    validation: dict[str, Any]  # ``report.to_dict()`` — contenu de .validation.json


def _collect_split(
    adapter: DatasetAdapter,
    split: str,
    limit: int | None,
) -> dict[str, list[Any]]:
    """Étapes PARSE + NORMALIZE pour un split : tables collectées (paresseuses → listes).

    Chaque table de :data:`TABLE_MODELS` est lue via la méthode ``iter_<table>``
    de l'adaptateur (contrat SPEC-03 §6) : ajouter une table au format pivot ne
    demande donc aucune modification ici.

    Contrat d'adaptateur : ``iter_X(split)`` produit exactement les enregistrements
    de ``split`` — disjoints entre splits (la fuite est attrapée par
    ``E-VAL-108`` à l'étape VALIDATE). ``limit`` borne chaque table à ses
    ``limit`` premiers éléments : la troncature est appliquée **pendant**
    l'itération, donc un ``--limit`` ne parse jamais tout le corpus
    (échantillonnage de tête ; le passage en mode ``limit`` marque le statut
    ``sampled``, G5).
    """
    if limit is not None and limit < 0:
        raise IngestionError(f"limit négatif : {limit!r} (0 ou un entier positif)")

    return {
        table: list(islice(getattr(adapter, f"iter_{table}")(split), limit))
        for table in TABLES
    }


def _ingest_streaming(
    adapter: DatasetAdapter,
    manifest: DatasetManifest,
    *,
    target_splits: Sequence[str],
    requested_split: str,
    limit: int | None,
    output_root: Path,
    resolution: SourceResolution | None,
) -> IngestionResult:
    """Ingère un adaptateur sans conserver ses objets normalisés en mémoire.

    Cette voie est réservée aux datasets sans tables relationnelles auxiliaires.
    Les JSONL sont écrits dans un staging, puis validés en flux avec un index
    SQLite temporaire avant publication.
    """

    structure = manifest.structure
    if any(
        (
            structure.has_profiles,
            structure.has_combinations,
            structure.has_organizations,
            structure.has_tasks,
        )
    ):
        raise IngestionError(
            f"{manifest.key} : streaming incompatible avec les tables auxiliaires "
            "déclarées par le manifeste"
        )
    if limit is not None and limit < 0:
        raise IngestionError(f"limit négatif : {limit!r} (0 ou un entier positif)")

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    base = output_root / manifest.key

    with tempfile.TemporaryDirectory(prefix=f".{manifest.key}-", dir=output_root) as tmp:
        staging = Path(tmp) / manifest.key
        for current_split in target_splits:
            document_path = staging / current_split / "documents.jsonl"
            written_documents = write_jsonl(
                document_path,
                islice(adapter.iter_documents(current_split), limit),
            )
            if written_documents == 0:
                document_path.unlink()

            annotation_path = staging / current_split / "annotations.jsonl"
            written_annotations = write_jsonl(
                annotation_path,
                islice(adapter.iter_annotations(current_split), limit),
            )
            if written_annotations == 0:
                annotation_path.unlink()

        files: dict[str, str] = {
            path.relative_to(staging).as_posix(): sha256_file(path)
            for path in sorted(staging.rglob("*.jsonl"))
        }
        report = validate_streaming_output(
            manifest.key,
            staging,
            files,
            expected_documents=manifest.integrity.expected_documents,
            expected_profiles=manifest.integrity.expected_profiles,
            expected_threads=manifest.integrity.expected_threads,
        )
        expected_documents = manifest.integrity.expected_documents
        volumetry = (
            expected_documents is not None
            and report.counts["documents"] == expected_documents
            and manifest.integrity.expected_threads is None
            and manifest.integrity.expected_profiles in (None, 0)
        )
        status = _determine_status(manifest, volumetry=volumetry, limit=limit)

        validation_payload = report.to_dict()
        write_json(staging / VALIDATION_NAME, validation_payload)
        lock = {
            "manifest": manifest.model_dump(mode="json"),
            "schema_version": SCHEMA_VERSION,
            "taxonomy_version": TAXONOMY_VERSION,
            "source": (
                {
                    "kind": "local",
                    "directory": str(resolution.directory),
                    "files": [str(path) for path in resolution.files],
                    "fingerprint": resolution.fingerprint,
                }
                if resolution is not None
                else {"kind": manifest.source.kind, "fingerprint": None}
            ),
            "files": files,
            "date": date.today().isoformat(),
            "status": status,
        }
        write_json(staging / LOCK_NAME, lock)

        if base.exists():
            if base.is_dir():
                shutil.rmtree(base)
            else:
                base.unlink()
        shutil.move(str(staging), str(base))

    return IngestionResult(
        dataset=manifest.key,
        split=requested_split,
        status=status,
        counts=report.counts,
        files=files,
        lock_path=base / LOCK_NAME,
        validation=validation_payload,
    )


def validate_streaming_output(
    dataset: str,
    base: Path,
    files: dict[str, str],
    *,
    expected_documents: int | None,
    expected_profiles: int | None,
    expected_threads: int | None,
) -> ValidationReport:
    """Revalide des JSONL streaming sans matérialiser les tables en mémoire."""

    document_paths = sorted(
        base / relative
        for relative in files
        if relative.endswith("/documents.jsonl") or relative == "documents.jsonl"
    )
    annotation_paths = sorted(
        base / relative
        for relative in files
        if relative.endswith("/annotations.jsonl") or relative == "annotations.jsonl"
    )
    other_paths = [
        relative
        for relative in files
        if not (
            relative.endswith("/documents.jsonl")
            or relative == "documents.jsonl"
            or relative.endswith("/annotations.jsonl")
            or relative == "annotations.jsonl"
        )
    ]
    if other_paths:
        raise IngestionError(
            f"{dataset} : validation streaming impossible pour les tables "
            f"{', '.join(sorted(other_paths))}"
        )

    document_count = 0
    annotation_count = 0
    other_qi_count = 0
    by_language: Counter[str] = Counter()
    by_domain: Counter[str] = Counter()
    by_expression_mode: Counter[str] = Counter()
    by_identifier_type: Counter[str] = Counter()
    by_qi_category: Counter[str] = Counter()

    with tempfile.TemporaryDirectory(prefix=f".{dataset}-validate-") as tmp:
        with closing(sqlite3.connect(Path(tmp) / "index.sqlite3")) as db:
            db.execute(
                "CREATE TABLE documents ("
                "doc_id TEXT PRIMARY KEY, text TEXT NOT NULL, split TEXT NOT NULL, "
                "thread_id TEXT)"
            )
            db.execute("CREATE TABLE annotations (annotation_id TEXT PRIMARY KEY)")
            for path in document_paths:
                for document in read_jsonl(path, Document):
                    try:
                        db.execute(
                            "INSERT INTO documents(doc_id, text, split, thread_id) "
                            "VALUES (?, ?, ?, ?)",
                            (
                                document.doc_id,
                                document.text,
                                document.split,
                                document.thread_id,
                            ),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise IngestionError(
                            f"{dataset} : E-VAL-111 — doc_id dupliqué "
                            f"{document.doc_id!r}"
                        ) from exc
                    document_count += 1
                    by_language[document.language] += 1
                    by_domain[document.domain.value] += 1
            db.commit()

            for path in annotation_paths:
                for annotation in read_jsonl(path, Annotation):
                    document_row = db.execute(
                        "SELECT text FROM documents WHERE doc_id = ?",
                        (annotation.doc_id,),
                    ).fetchone()
                    if document_row is None:
                        raise IngestionError(
                            f"{dataset} : E-VAL-104 — annotation "
                            f"{annotation.annotation_id!r} référence le doc_id "
                            f"orphelin {annotation.doc_id!r}"
                        )
                    try:
                        annotation.check_against_text(document_row[0])
                    except ValueError as exc:
                        raise IngestionError(
                            f"{dataset} : E-VAL-101 — {exc} ({annotation.doc_id})"
                        ) from exc
                    try:
                        db.execute(
                            "INSERT INTO annotations(annotation_id) VALUES (?)",
                            (annotation.annotation_id,),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise IngestionError(
                            f"{dataset} : E-VAL-111 — annotation_id dupliqué "
                            f"{annotation.annotation_id!r}"
                        ) from exc
                    annotation_count += 1
                    by_expression_mode[annotation.expression_mode.value] += 1
                    by_identifier_type[annotation.identifier_type.value] += 1
                    by_qi_category.update(annotation.qi_categories)
                    if "OTHER_QI" in annotation.qi_categories:
                        other_qi_count += 1

            thread_row = db.execute(
                "SELECT COUNT(DISTINCT thread_id) FROM documents "
                "WHERE thread_id IS NOT NULL"
            ).fetchone()
            if thread_row is None:
                raise IngestionError(f"{dataset} : index streaming incomplet")
            thread_count = int(thread_row[0])

    issues: list[ValidationIssue] = []
    if expected_documents is not None and document_count != expected_documents:
        issues.append(
            ValidationIssue(
                code="E-VAL-109",
                severity="warning",
                message=(
                    f"Volumétrie observée ({document_count}) != expected_documents "
                    f"({expected_documents})"
                ),
            )
        )
    if annotation_count and other_qi_count / annotation_count > 0.01:
        issues.append(
            ValidationIssue(
                code="E-VAL-110",
                severity="warning",
                message=(
                    f"Taux d'OTHER_QI={other_qi_count}/{annotation_count} "
                    f"({other_qi_count / annotation_count:.2%}) > 1 % — "
                    "taxonomie incomplète"
                ),
            )
        )
    counts: dict[str, Any] = {
        "documents": document_count,
        "annotations": annotation_count,
        "profiles": 0,
        "organizations": 0,
        "combinations": 0,
        "tasks": 0,
        "by_language": dict(sorted(by_language.items())),
        "by_domain": dict(sorted(by_domain.items())),
        "by_expression_mode": dict(sorted(by_expression_mode.items())),
        "by_identifier_type": dict(sorted(by_identifier_type.items())),
        "by_qi_category": dict(sorted(by_qi_category.items())),
        "warnings": {"E-VAL-107": 0, "E-VAL-110": other_qi_count},
    }
    report = ValidationReport(
        dataset=dataset,
        status="WARN" if issues else "PASS",
        counts=counts,
        issues=tuple(issues),
    )
    if expected_profiles not in (None, 0):
        raise IngestionError(
            f"{dataset} : validation streaming impossible : expected_profiles="
            f"{expected_profiles} mais aucune table profiles.jsonl"
        )
    if expected_threads is not None and thread_count != expected_threads:
        report = ValidationReport(
            dataset=dataset,
            status="WARN",
            counts=counts,
            issues=tuple(
                [
                    *issues,
                    ValidationIssue(
                        code="E-VAL-109",
                        severity="warning",
                        message=(
                            f"Volumétrie observée ({thread_count}) != expected_threads "
                            f"({expected_threads})"
                        ),
                    ),
                ]
            ),
        )
    return report


def _target_splits(
    adapter: DatasetAdapter, manifest: DatasetManifest, split: str
) -> list[str]:
    """Résout ``split`` en splits concrets ; aucun repli silencieux.

    ``"all"`` énumère les splits déclarés par l'adaptateur (manifeste par
    défaut) ; un split inconnu ou une liste vide est une erreur de
    configuration, pas un cas à absorber.
    """
    declared = list(adapter.splits())
    if split == "all":
        if not declared:
            raise IngestionError(
                f"{manifest.key} : split='all' mais aucun split déclaré "
                f"(manifeste `structure.splits` vide et `splits()` non surchargé) — "
                "impossible d'énumérer sans liste"
            )
        return sorted(declared)
    if declared and split not in declared:
        raise IngestionError(
            f"{manifest.key} : split inconnu {split!r} "
            f"(déclarés : {', '.join(declared) or 'aucun'})"
        )
    return [split]


def _volumetry_conforms(
    manifest: DatasetManifest, documents: Sequence[Document]
) -> bool:
    """G5 (SPEC-03 §5) : volumétrie observée == ``integrity.expected_*``.

    Contrôlée **ici** par le pipeline (et non seulement par ``E-VAL-109``,
    qui n'est qu'un avertissement) : le statut ``official`` exige la
    conformité. ``expected_documents`` est la borne principale ;
    ``expected_threads`` est contrôlée sur les threads distincts des
    documents. ``expected_profiles`` est contrôlée par l'appelant, qui a
    les profils collectés sous la main (le rapport les compte).
    """
    integrity = manifest.integrity
    if integrity.expected_documents is None:
        return False
    if len(documents) != integrity.expected_documents:
        return False
    if integrity.expected_threads is not None:
        threads = {d.thread_id for d in documents if d.thread_id is not None}
        if len(threads) != integrity.expected_threads:
            return False
    return True


def _determine_status(
    manifest: DatasetManifest,
    *,
    volumetry: bool,
    limit: int | None,
) -> str:
    """Statut selon G3/G5 (SPEC-03 §5) — aucune valeur intermédiaire floue.

    - ``diagnostic`` : licence inconnue (``spdx`` null/``UNKNOWN``) — G3 ;
    - ``official`` : licence connue **et** volumétrie conforme (G5) **et**
      éligibilité déclarée **et** aucun échantillonnage ;
    - ``sampled`` : tout le reste (volumétrie divergente, ``limit``,
      non-éligibilité) — jamais un statut fantôme.
    """
    spdx = manifest.license.spdx
    if spdx is None or str(spdx).strip().upper() == "UNKNOWN":
        return "diagnostic"
    if manifest.evaluation.official_eligible and volumetry and limit is None:
        return "official"
    return "sampled"


def ingest(
    adapter: DatasetAdapter,
    manifest: DatasetManifest,
    *,
    split: str = "all",
    limit: int | None = None,
    output_root: Path = Path("data/processed"),
    resolution: SourceResolution | None = None,
) -> IngestionResult:
    """Ingestion complète d'un dataset vers le format pivot (SPEC-04).

    Étapes : ACQUIRE (présence de la source) → PARSE/NORMALIZE (adaptateur,
    par split) → VALIDATE (``validate_dataset`` ; toute issue de sévérité
    ``error`` fait **échouer** l'ingestion) → PUBLISH (tables non vides,
    ``.validation.json``, ``.manifest.lock.json``).

    Le lock fige les sept éléments de reproductibilité (SPEC-09 §5 côté lock)
    : manifeste résolu, ``schema_version``, ``taxonomy_version``, empreinte de
    la source, sha256 de chaque fichier produit, date, statut. La date est le
    seul champ non déterministe — elle va dans le lock, jamais dans les
    données (SPEC-04 §9).

    :param adapter: adaptateur du dataset (format source).
    :param manifest: manifeste chargé (SPEC-03 §4).
    :param split: ``"all"`` (défaut) ou un split nominal.
    :param limit: borne d'échantillonnage par table ; force le statut ``sampled``.
    :param output_root: racine de ``data/processed``.
    :param resolution: résolution de source déjà calculée (``LoadedManifest``)
        — évite de re-hacher le corpus ; recalculée si absente.
    """
    key = manifest.key

    # --- Étape 1 : ACQUIRE ----------------------------------------------- #
    if resolution is None:
        resolution = resolve_local_source(manifest.source)

    # --- Étape 2+3 : PARSE + NORMALIZE, par split ------------------------ #
    target_splits = _target_splits(adapter, manifest, split)
    if adapter.streaming:
        return _ingest_streaming(
            adapter,
            manifest,
            target_splits=target_splits,
            requested_split=split,
            limit=limit,
            output_root=Path(output_root),
            resolution=resolution,
        )
    per_split: dict[str, dict[str, list[Any]]] = {
        s: _collect_split(adapter, s, limit) for s in target_splits
    }
    tables: dict[str, list[Any]] = {
        table: [record for s in target_splits for record in per_split[s][table]]
        for table in TABLES
    }

    # --- Étape 4 : VALIDATE --------------------------------------------- #
    report = validate_dataset(
        key,
        **tables,
        expected_documents=manifest.integrity.expected_documents,
    )
    errors = report.errors()
    if errors:
        by_code: dict[str, int] = {}
        for issue in errors:
            by_code[issue.code] = by_code.get(issue.code, 0) + 1
        detail = ", ".join(f"{code} ×{n}" for code, n in sorted(by_code.items()))
        first = errors[0]
        where = f" ({first.doc_id})" if first.doc_id else ""
        raise IngestionError(
            f"ingestion {key} échouée en VALIDATE : {detail} — première violation : "
            f"{first.message}{where}"
        )

    # --- Étape 5 : PUBLISH ---------------------------------------------- #
    base = Path(output_root) / key

    # Volumétrie complète, y compris les profils (le rapport les compte).
    volumetry = _volumetry_conforms(manifest, tables["documents"])
    if volumetry and manifest.integrity.expected_profiles is not None:
        volumetry = report.counts["profiles"] == manifest.integrity.expected_profiles

    status = _determine_status(manifest, volumetry=volumetry, limit=limit)

    files: dict[str, str] = {}
    for s in sorted(per_split):
        for table in TABLES:
            records = per_split[s][table]
            if not records:
                continue  # les tables vides ne sont pas écrites
            path = base / s / f"{table}.jsonl"
            write_jsonl(path, records)
            files[f"{s}/{table}.jsonl"] = sha256_file(path)

    validation_payload = report.to_dict()
    write_json(base / VALIDATION_NAME, validation_payload)

    lock = {
        "manifest": manifest.model_dump(mode="json"),
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "source": (
            {
                "kind": "local",
                "directory": str(resolution.directory),
                "files": [str(p) for p in resolution.files],
                "fingerprint": resolution.fingerprint,
            }
            if resolution is not None
            else {"kind": manifest.source.kind, "fingerprint": None}
        ),
        "files": files,
        "date": date.today().isoformat(),
        "status": status,
    }
    lock_path = base / LOCK_NAME
    write_json(lock_path, lock)

    return IngestionResult(
        dataset=key,
        split=split,
        status=status,
        counts=report.counts,
        files=files,
        lock_path=lock_path,
        validation=validation_payload,
    )


def check_lock_compatibility(lock_path: Path) -> dict[str, Any]:
    """Vérifie qu'un lock est compatible avec la taxonomie courante (SPEC-04 §6).

    Refuse un lock dont ``taxonomy_version`` diffère de la version courante
    (un changement de SPEC-01 invalide les ingestions précédentes) et
    demande une réingestion. Retourne le lock lu.
    """
    lock_path = Path(lock_path)
    if not lock_path.exists():
        raise LockIncompatibleError(
            f"lock absent : {lock_path} — le dataset n'est pas ingéré"
        )
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LockIncompatibleError(f"lock illisible : {lock_path} ({exc})") from exc
    if not isinstance(lock, dict):
        raise LockIncompatibleError(f"{lock_path} : le lock doit être un mapping JSON")
    taxonomy = lock.get("taxonomy_version")
    if taxonomy is None:
        raise LockIncompatibleError(
            f"{lock_path} : le lock ne contient pas de `taxonomy_version` — réingestion requise"
        )
    if taxonomy != TAXONOMY_VERSION:
        raise LockIncompatibleError(
            f"{lock_path} : version de taxonomie figée {taxonomy!r} != courante "
            f"{TAXONOMY_VERSION!r} — les codes SPEC-01 ont changé, réingestion requise"
        )
    return {str(name): value for name, value in lock.items()}

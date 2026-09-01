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
from collections.abc import Sequence
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
from anonymisation.schema.io import sha256_file, write_json, write_jsonl
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
from anonymisation.schema.validation import validate_dataset

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


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Écrit un JSON de manière atomique et reproductible (SPEC-04 §6)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, sort_keys=True, indent=2)
            fh.write("\n")
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
    os.replace(tmp, path)


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
    return lock

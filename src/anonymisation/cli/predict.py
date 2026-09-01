"""Commande ``anonv2 predict`` (ticket C-3, SPEC-10 §5, §10).

Anonymise un pivot ingéré (dataset + split) dans le profil d'exécution
choisi et écrit les artefacts reproductibles de l'exécution dans le
répertoire de sortie :

* ``predictions.jsonl`` — une ligne par document (``doc_id``, ``status``,
  ``error`` toujours présent, ``annotations``, ``decisions``,
  ``anonymized_text``, ``risk``, ``runtime_ms``) ; une ligne en erreur
  n'est jamais confondue avec une prédiction vide d'annotations
  (audit §12.5) ;
* ``traces.jsonl`` — les huit traces d'étape par document (SPEC-10 §4) ;
* ``manifest.lock.json`` — les sept éléments de reproductibilité
  (SPEC-09 §5) : version des données (lock d'ingestion), version de la
  taxonomie, commit git, modèles, graine, prompts d'attaque, politique.

Profil déterministe (SPEC-10 §10) : deux runs sur le même corpus
produisent des fichiers **bit-à-bit identiques** — horloge mise à zéro
(``strict``), ``sort_keys``, ordre des documents = ordre du fichier,
aucune date dans le lock.
"""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from anonymisation import __version__
from anonymisation.datasets.ingest import LOCK_NAME
from anonymisation.datasets.registry import (
    ALIASES,
    REGISTRY,
    UnknownDatasetError,
    list_keys,
)
from anonymisation.pipeline.orchestrator import Pipeline
from anonymisation.pipeline.profiles import RuntimeProfile, load_runtime_profile
from anonymisation.pipeline.traces import (
    serialize_pipeline_result,
    serialize_stage_trace,
)
from anonymisation.schema.io import (
    atomic_write,
    read_jsonl,
    sha256_file,
    write_json,
)
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import TAXONOMY_VERSION

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
PROCESSED_ROOT = REPO_ROOT / "data" / "processed"
DATASETS_CONFIG = REPO_ROOT / "configs" / "datasets"
POLICY_FILE = REPO_ROOT / "configs" / "policy" / "policies.yaml"


class PredictError(ValueError):
    """Erreur d'usage ou de contrat actionnable (pivot manquant, split, ...)."""


# --------------------------------------------------------------------------- #
# Résolution des entrées
# --------------------------------------------------------------------------- #
def _resolve_dataset(key: str) -> str:
    """Résout une clé ou un alias vers la clé canonique du registre.

    Une clé absente du registre est acceptée si un pivot ingéré existe
    pour elle (corpus de test, corpus synthétique) : pour ``predict``, le
    pivot est la source de vérité.
    """
    if key in ALIASES:
        return ALIASES[key]
    if key in REGISTRY or (PROCESSED_ROOT / key).is_dir():
        return key
    known = ", ".join(
        sorted(set(list_keys()) | {p.stem for p in DATASETS_CONFIG.glob("*.yaml")})
    ) or "aucune"
    raise UnknownDatasetError(f"Dataset inconnu : {key!r}. Clés connues : {known}")


def _load_pivot(
    key: str, split: str
) -> tuple[list[Document], dict[str, tuple[Annotation, ...]]]:
    """Charge le pivot ingéré (documents + annotations groupées par doc_id).

    Les annotations du pivot sont la vérité terrain : l'étape VALIDATE les
    utilise pour le contrôle de fuite par recherche exacte (indépendant du
    détecteur).
    """
    base = PROCESSED_ROOT / key / split
    docs_path = base / "documents.jsonl"
    anns_path = base / "annotations.jsonl"
    if not docs_path.is_file() or not anns_path.is_file():
        raise PredictError(
            f"Pivot ingéré absent pour le dataset {key!r} / split {split!r} "
            f"(attendu : {docs_path} et {anns_path}). "
            f"Exécute d'abord : anonv2 datasets ingest {key} --split {split}"
        )
    docs = list(read_jsonl(docs_path, Document))
    gold: dict[str, list[Annotation]] = defaultdict(list)
    for ann in read_jsonl(anns_path, Annotation):
        gold[ann.doc_id].append(ann)
    return docs, {k: tuple(v) for k, v in gold.items()}


# --------------------------------------------------------------------------- #
# Lock de reproductibilité (SPEC-09 §5)
# --------------------------------------------------------------------------- #
def _git_commit(root: Path) -> str | None:
    """Commit courant (élément 3 de SPEC-09 §5) ; ``None`` hors dépôt git.

    Un lock sans commit n'est **pas publiable** (SPEC-09 §5) — le champ
    reste présent pour que la détection le soit.
    """
    try:
        proc = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _data_version(key: str) -> dict[str, Any] | None:
    """Lock d'ingestion du pivot (SHA-256 par table + révision source)."""
    lock_path = PROCESSED_ROOT / key / LOCK_NAME
    if not lock_path.is_file():
        return None
    return json.loads(lock_path.read_text(encoding="utf-8"))


def _build_lock(
    *,
    key: str,
    split: str,
    profile: RuntimeProfile,
    policy_id: str,
    limit: int | None,
    documents_total: int,
    counts: dict[str, int],
) -> dict[str, Any]:
    """Les sept éléments de reproductibilité (SPEC-09 §5), en ordre stable.

    Aucune horloge dans le lock : la reproductibilité bit-à-bit l'exige.
    """
    det = profile.determinism
    return {
        "lock_version": 1,
        "run": {
            "dataset": key,
            "split": split,
            "profile": profile.profile,
            "policy": policy_id,
            "limit": limit,
            "status": "sampled" if limit is not None else "complete",
            "documents_total": documents_total,
            "documents_ok": counts.get("ok", 0),
            "documents_partial": counts.get("partial", 0),
            "documents_error": counts.get("error", 0),
        },
        # 1. Version des données (lock d'ingestion : sha256 + révision source).
        "data_version": _data_version(key),
        # 2. Version de la taxonomie (SPEC-01).
        "taxonomy_version": TAXONOMY_VERSION,
        # 3. Version du code : commit git (+ version du paquet).
        "code": {
            "anonymisation_version": __version__,
            "git_commit": _git_commit(REPO_ROOT),
        },
        # 4. Modèles utilisés + quantification — v1 : aucun (détecteur
        #    déterministe, pas de NER/LLM).
        "models": [],
        # 5. Graine(s) de l'aléa.
        "seeds": {"determinism": det.seed},
        # 6. Prompts d'attaque versionnés — v1 : aucun (pas d'étape LLM).
        "prompts": [],
        # 7. Politique effective.
        "policy": {
            "id": policy_id,
            "source": str(POLICY_FILE.relative_to(REPO_ROOT)),
            "sha256": sha256_file(POLICY_FILE),
        },
    }


# --------------------------------------------------------------------------- #
# Commande
# --------------------------------------------------------------------------- #
def cmd_predict(
    dataset: str,
    split: str,
    policy: str,
    profile: str,
    out: str | None,
    limit: int | None,
) -> int:
    """Exécute le pipeline sur le pivot du dataset et fige les artefacts.

    Retourne 0 si aucun document n'est en erreur, 1 sinon (les documents
    en erreur sont comptés en erreur — jamais comme des prédictions vides).
    """
    if limit is not None and limit <= 0:
        raise PredictError("--limit doit être un entier strictement positif.")

    key = _resolve_dataset(dataset)
    docs, gold = _load_pivot(key, split)
    if limit is not None:
        docs = docs[:limit]

    loaded = load_runtime_profile(profile)
    pipe = Pipeline(loaded.profile, policy_id=policy)

    if out is not None:
        out_dir = Path(out)
    else:
        run_id = f"predict-{key}-{split}-{policy}-{loaded.profile.profile}"
        out_dir = REPO_ROOT / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    strict = loaded.profile.determinism.strict
    counts: dict[str, int] = {"ok": 0, "partial": 0, "error": 0}
    with atomic_write(out_dir / "predictions.jsonl") as predictions, atomic_write(
        out_dir / "traces.jsonl"
    ) as traces:
        for doc in docs:
            result = pipe.run(doc, gold.get(doc.doc_id))
            counts[result.status] = counts.get(result.status, 0) + 1
            predictions.write(
                json.dumps(
                    serialize_pipeline_result(result, strict=strict),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            for trace in result.traces:
                traces.write(
                    json.dumps(
                        serialize_stage_trace(trace, strict=strict),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )

    lock = _build_lock(
        key=key,
        split=split,
        profile=loaded.profile,
        policy_id=policy,
        limit=limit,
        documents_total=len(docs),
        counts=counts,
    )
    write_json(out_dir / "manifest.lock.json", lock)

    print(
        f"predict : {len(docs)} document(s) — dataset {key!r}, split {split!r}, "
        f"politique {policy!r}, profil {loaded.profile.profile!r}"
    )
    for status in ("ok", "partial", "error"):
        if counts.get(status):
            print(f"  {status} : {counts[status]}")
    print(f"  sortie : {out_dir}")
    return 1 if counts.get("error") else 0

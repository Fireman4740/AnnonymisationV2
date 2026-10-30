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

import importlib.util
import json
import subprocess
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from anonymisation import __version__
from anonymisation.datasets.ingest import LOCK_NAME
from anonymisation.datasets.registry import (
    ALIASES,
    REGISTRY,
    UnknownDatasetError,
    list_keys,
)
from anonymisation.pipeline.guards import LocalOnlyViolationError, assert_local_only
from anonymisation.pipeline.profiles import RuntimeProfile, load_runtime_profile
from anonymisation.pipeline.traces import serialize_pipeline_result, serialize_stage_trace
from anonymisation.schema.integrity import (
    DataIntegrityError,
    locked_files,
    verify_pivot_files,
)
from anonymisation.schema.io import (
    atomic_write,
    read_jsonl,
    sha256_file,
    write_json,
)
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import TAXONOMY_VERSION
from anonymisation.systems import SystemConfig, resolve_system
from anonymisation.systems.base import SystemBase

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
PROCESSED_ROOT = REPO_ROOT / "data" / "processed"
DATASETS_CONFIG = REPO_ROOT / "configs" / "datasets"
POLICY_FILE = REPO_ROOT / "configs" / "policy" / "policies.yaml"
LLM_BACKENDS_FILE = REPO_ROOT / "configs" / "llm" / "backends.yaml"


class PredictError(ValueError):
    """Erreur d'usage ou de contrat actionnable (pivot manquant, split, ...)."""

def _assert_local_only_for_dataset(profile: RuntimeProfile, key: str) -> None:
    """Applique la garde réseau avant qu'un pipeline puisse voir le texte."""
    if not profile.llm.allow_remote:
        return

    manifest_path = DATASETS_CONFIG / f"{key}.yaml"
    if not manifest_path.is_file():
        raise PredictError(
            f"Corpus {key!r} : manifeste absent ({manifest_path}) ; "
            "impossible d'autoriser un accès distant sans connaître son statut "
            "synthetic."
        )
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PredictError(
            f"Manifeste du corpus {key!r} illisible : {manifest_path} ({exc})"
        ) from exc
    if not isinstance(raw, dict):
        raise PredictError(f"Manifeste du corpus {key!r} invalide : mapping YAML attendu")
    manifest_payload: dict[str, Any] = {str(name): value for name, value in raw.items()}
    try:
        assert_local_only(profile, manifest_payload)
    except LocalOnlyViolationError as exc:
        raise PredictError(str(exc)) from exc


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
    key: str, split: str, *, has_annotations: bool
) -> tuple[list[Document], dict[str, tuple[Annotation, ...]]]:
    """Charge le pivot ingéré (documents + annotations groupées par doc_id).

    Les annotations du pivot sont la vérité terrain : l'étape VALIDATE les
    utilise pour le contrôle de fuite par recherche exacte (indépendant du
    détecteur).

    ``has_annotations`` vient du lock d'ingestion : un corpus d'utilité pure
    (SupportTickets, Bitext) n'a **aucune** annotation, et le lock le déclare
    en ne listant pas ``<split>/annotations.jsonl``. L'absence n'est donc
    jamais devinée : si le lock annonce des annotations, le fichier doit
    exister (vérifié par empreinte avant cet appel).
    """
    base = PROCESSED_ROOT / key / split
    docs_path = base / "documents.jsonl"
    anns_path = base / "annotations.jsonl"
    if not docs_path.is_file():
        raise PredictError(
            f"Pivot ingéré absent pour le dataset {key!r} / split {split!r} "
            f"(attendu : {docs_path}). "
            f"Exécute d'abord : anonv2 datasets ingest {key} --split {split}"
        )
    docs = list(read_jsonl(docs_path, Document))
    gold: dict[str, list[Annotation]] = defaultdict(list)
    if has_annotations:
        for ann in read_jsonl(anns_path, Annotation):
            gold[ann.doc_id].append(ann)
    return docs, {k: tuple(v) for k, v in gold.items()}


# --------------------------------------------------------------------------- #
# Lock de reproductibilité (SPEC-09 §5)
# --------------------------------------------------------------------------- #
def _git(root: Path, *args: str) -> str | None:
    """Sortie d'une commande git, ou ``None`` hors dépôt / git absent."""
    try:
        proc = subprocess.run(
            ("git", *args),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _git_commit(root: Path) -> str | None:
    """Commit courant (élément 3 de SPEC-09 §5) ; ``None`` hors dépôt git.

    Un lock sans commit n'est **pas publiable** (SPEC-09 §5) — le champ
    reste présent pour que la détection le soit.
    """
    out = _git(root, "rev-parse", "HEAD")
    if out is not None:
        return out.strip()
    # Archives immuables : le marqueur est substitué par git archive à l'export.
    # Un simple environnement prétendant connaître le commit n'est pas accepté.
    from anonymisation.provenance import archive_identity

    identity = archive_identity(root)
    return identity[0] if identity else None


def _git_dirty(root: Path) -> bool | None:
    """Vrai si l'arbre de travail diffère du commit enregistré.

    Un commit seul ne suffit pas à rejouer un run : des modifications non
    commitées du code ou d'une configuration changent le résultat sans changer
    le hash. ``runs/`` et ``data/`` sont ignorés par git, donc absents d'ici.
    ``None`` = état inconnu (hors dépôt), traité comme non publiable par le
    scorer — jamais présumé propre.
    """
    out = _git(root, "status", "--porcelain")
    if out is not None:
        return bool(out.strip())
    from anonymisation.provenance import archive_dirty

    return archive_dirty(root)


def _data_version(key: str) -> dict[str, Any]:
    """Lock d'ingestion du pivot (SHA-256 par table + révision source).

    Absent = pivot non produit par ``ingest`` : on refuse plutôt que d'écrire
    un run dont la vérité terrain ne serait vérifiable par personne.
    """
    lock_path = PROCESSED_ROOT / key / LOCK_NAME
    if not lock_path.is_file():
        raise PredictError(
            f"Lock d'ingestion absent pour {key!r} : {lock_path}. Le pivot n'est "
            f"pas vérifiable — exécute « anonv2 datasets ingest {key} »."
        )
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PredictError(f"Lock d'ingestion illisible : {lock_path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise PredictError(f"Lock d'ingestion invalide pour {key!r} : mapping attendu")
    return {str(name): value for name, value in payload.items()}


def _verify_pivot(key: str, split: str, data_version: Mapping[str, Any]) -> None:
    """Refuse un pivot dont le contenu ne correspond plus au lock d'ingestion."""
    context = f"Pivot {key!r} / split {split!r}"
    try:
        verify_pivot_files(
            PROCESSED_ROOT / key,
            split,
            ("documents.jsonl", "annotations.jsonl"),
            locked_files(data_version, context=context),
            context=context,
            required=("documents.jsonl",),
        )
    except DataIntegrityError as exc:
        raise PredictError(str(exc)) from exc


def _prompt_digest(ref: str) -> dict[str, str]:
    """Référence ``module:fonction`` d'un prompt + empreinte du module source.

    Le nom seul ne fige rien : éditer le gabarit sous le même nom changerait
    les sorties sans changer le lock. Un module introuvable lève plutôt que
    d'écrire une empreinte vide.
    """
    module = ref.partition(":")[0]
    spec = importlib.util.find_spec(module)
    if spec is None or spec.origin is None or not Path(spec.origin).is_file():
        raise PredictError(
            f"Prompt {ref!r} déclaré par le système : module {module!r} introuvable, "
            "empreinte impossible — corriger `prompts()` du système."
        )
    return {"ref": ref, "sha256": sha256_file(Path(spec.origin))}


def _system_reproducibility(pipe: SystemBase) -> dict[str, Any]:
    """Modèles, prompts et paramètres **effectifs** du système (SPEC-09 §5, H-0).

    Un système appelant un LLM fige aussi l'empreinte de
    ``configs/llm/backends.yaml`` : température, URL et routage du fournisseur
    y vivent, et changent la sortie sans changer le nom du modèle.
    """
    descriptor = pipe.describe()
    block: dict[str, Any] = {
        "models": [model.to_dict() for model in descriptor.models],
        "prompts": [_prompt_digest(ref) for ref in descriptor.prompts],
        "params": pipe.effective_params(),
    }
    if not descriptor.offline_only:
        block["llm_config"] = {
            "source": str(LLM_BACKENDS_FILE.relative_to(REPO_ROOT)),
            "sha256": sha256_file(LLM_BACKENDS_FILE),
        }
    return block


#: Portée de risque effectivement appliquée par les systèmes : le document.
#: Aucun moteur n'agrège encore l'historique d'un auteur (EPIC-H H-9, S5).
APPLIED_POLICY_SCOPE = "document"


def _policy_scope(policy_id: str) -> dict[str, Any]:
    """Portée demandée par la politique vs portée appliquée — jamais un écart muet.

    P3/P4 déclarent ``scope: author`` (« tient compte de l'historique ») ; les
    systèmes actuels évaluent le risque document par document. Le lock le dit,
    pour qu'aucun chiffre P3/P4 ne soit lu comme un résultat à portée auteur.
    """
    from anonymisation.policy.models import load_policy_set

    policy_set = load_policy_set(POLICY_FILE)
    requested = policy_set.policies[policy_id].scope or policy_set.defaults.scope
    block: dict[str, Any] = {"scope_requested": requested, "scope_applied": APPLIED_POLICY_SCOPE}
    if requested != APPLIED_POLICY_SCOPE:
        block["scope_gap"] = (
            f"portée {requested!r} demandée par {policy_id}, non implémentée : risque "
            f"évalué par document — S5 non vérifiable"
        )
    return block


def _build_lock(
    *,
    key: str,
    split: str,
    profile: RuntimeProfile,
    policy_id: str,
    limit: int | None,
    documents_total: int,
    counts: dict[str, int],
    data_version: Mapping[str, Any],
    system_block: Mapping[str, Any],
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
        "data_version": dict(data_version),
        # 2. Version de la taxonomie (SPEC-01).
        "taxonomy_version": TAXONOMY_VERSION,
        # 3. Version du code : commit git (+ version du paquet).
        "code": {
            "anonymisation_version": __version__,
            "git_commit": _git_commit(REPO_ROOT),
            "git_dirty": _git_dirty(REPO_ROOT),
        },
        # 4. Modèles utilisés + quantification, déclarés par le système
        #    (vide pour un système déterministe).
        "models": list(system_block["models"]),
        # Valeurs effectives des paramètres (défauts inclus).
        "params": dict(system_block["params"]),
        **({"llm_config": dict(system_block["llm_config"])}
           if "llm_config" in system_block else {}),
        # 5. Graine(s) de l'aléa.
        "seeds": {"determinism": det.seed},
        # 6. Prompts versionnés : référence + empreinte du module source.
        "prompts": list(system_block["prompts"]),
        # 7. Politique effective.
        "policy": (
            {
                "id": policy_id,
                "source": str(POLICY_FILE.relative_to(REPO_ROOT)),
                "sha256": sha256_file(POLICY_FILE),
                **_policy_scope(policy_id),
            }
            if policy_id
            # Absence DÉCLARÉE, jamais déduite du silence : sans `reason`, on
            # ne distinguerait pas « ce système n'a pas de politique » d'un
            # lock tronqué.
            else {"id": None, "reason": "système sans politique"}
        ),
    }


# --------------------------------------------------------------------------- #
# Commande
# --------------------------------------------------------------------------- #
def select_documents(docs: list[Document], key: str, split: str, path: Path) -> list[Document]:
    """Sélection exacte et vérifiée, sans modifier les octets du pivot source."""
    import hashlib

    try:
        rows = json.loads(path.read_text())["datasets"][key][split]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PredictError(f"manifeste de sélection invalide : {path}") from exc
    if (not isinstance(rows, list) or not rows
            or any(not isinstance(r, dict) or set(r) != {"doc_id", "text_sha256"}
                   or not isinstance(r["doc_id"], str) for r in rows)):
        raise PredictError("sélection non vide de doc_id/text_sha256 requise")
    wanted = {r["doc_id"]: r["text_sha256"] for r in rows}
    selected = [d for d in docs if d.doc_id in wanted]
    if len(wanted) != len(rows) or len(selected) != len(rows):
        raise PredictError("sélection dupliquée ou document absent du pivot")
    if [d.doc_id for d in selected] != [r["doc_id"] for r in rows]:
        raise PredictError("ordre de sélection différent du pivot figé")
    for d in selected:
        if hashlib.sha256(d.text.encode()).hexdigest() != wanted[d.doc_id]:
            raise PredictError(f"texte de sélection divergent : {d.doc_id}")
    return selected


def cmd_predict(
    dataset: str,
    split: str,
    policy: str,
    profile: str,
    out: str | None,
    limit: int | None,
    system: str = "deterministic",
    params: Mapping[str, Any] | None = None,
    selection_manifest: str | None = None,
) -> int:
    """Exécute le pipeline sur le pivot du dataset et fige les artefacts.

    Retourne 0 si aucun document n'est en erreur, 1 sinon (les documents
    en erreur sont comptés en erreur — jamais comme des prédictions vides).
    """
    if limit is not None and limit <= 0:
        raise PredictError("--limit doit être un entier strictement positif.")

    key = _resolve_dataset(dataset)
    if not (PROCESSED_ROOT / key / split / "documents.jsonl").is_file():
        raise PredictError(
            f"Pivot ingéré absent pour le dataset {key!r} / split {split!r} "
            f"(attendu : {PROCESSED_ROOT / key / split / 'documents.jsonl'}). "
            f"Exécute d'abord : anonv2 datasets ingest {key} --split {split}"
        )
    # Lock vérifié AVANT lecture : il décide aussi si des annotations existent.
    data_version = _data_version(key)
    _verify_pivot(key, split, data_version)
    has_annotations = f"{split}/annotations.jsonl" in (data_version.get("files") or {})
    docs, gold = _load_pivot(key, split, has_annotations=has_annotations)
    selection_sha256 = None
    if selection_manifest is not None:
        selection_path = Path(selection_manifest)
        docs = select_documents(docs, key, split, selection_path)
        selection_sha256 = sha256_file(selection_path)
    if limit is not None:
        docs = docs[:limit]

    loaded = load_runtime_profile(profile)
    _assert_local_only_for_dataset(loaded.profile, key)

    # Résolution par le registre : c'est le seul point du harnais qui connaît
    # une implémentation concrète. Tout le reste — scoring, métriques,
    # comparaison — ne voit qu'un `PipelineResult` estampillé.
    system_cls = resolve_system(system)
    if system_cls.uses_policy and not policy:
        raise PredictError(
            f"Système {system_cls.system_id!r} : --policy est requis "
            f"(ex. --policy P2)."
        )
    if policy and not system_cls.uses_policy:
        # Jamais ignoré en silence : une politique acceptée puis sans effet
        # laisserait croire que le run a été produit sous cette politique.
        raise PredictError(
            f"Système {system_cls.system_id!r} : --policy {policy!r} a été "
            f"fourni alors que ce système ne consomme aucune politique. "
            f"Retirez --policy."
        )
    effective_params = dict(params or {})
    pipe = system_cls(
        SystemConfig(
            params=effective_params,
            policy_id=policy,
            profile=loaded.profile,
            repo_root=REPO_ROOT,
        )
    )
    identity = pipe.identity()

    if out is not None:
        out_dir = Path(out)
    else:
        # Le nom de run porte le système et l'empreinte de ses paramètres :
        # sans eux, deux systèmes partageant un profil écriraient au même
        # endroit et le second écraserait le premier.
        run_id = (
            f"{identity.system_id}-{key}-{split}-"
            f"{policy or 'nopolicy'}-{identity.params_digest[:8]}"
        )
        out_dir = REPO_ROOT / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    strict = loaded.profile.determinism.strict
    counts: dict[str, int] = {"ok": 0, "partial": 0, "error": 0}
    with atomic_write(out_dir / "predictions.jsonl") as predictions, atomic_write(
        out_dir / "traces.jsonl"
    ) as traces:
        for completed, doc in enumerate(docs, start=1):
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
            if completed == 1 or completed % 25 == 0 or completed == len(docs):
                print("PREDICT_PROGRESS", json.dumps({"dataset": key, "split": split,
                    "system": identity.system_id, "completed": completed, "total": len(docs),
                    "counts": counts}, sort_keys=True), flush=True)

    lock = _build_lock(
        key=key,
        split=split,
        profile=loaded.profile,
        policy_id=policy,
        limit=limit,
        documents_total=len(docs),
        counts=counts,
        data_version=data_version,
        system_block=_system_reproducibility(pipe),
    )
    if selection_sha256 is not None:
        lock["run"]["selection_manifest_sha256"] = selection_sha256
        lock["run"]["status"] = "sampled"
    # Empreinte des sorties : `score` refuse un run édité après coup.
    lock["outputs"] = {
        name: sha256_file(out_dir / name) for name in ("predictions.jsonl", "traces.jsonl")
    }
    # Sans cette identité, le scorer ne saurait pas quelles métriques sont
    # applicables et publierait des zéros là où la capacité est absente.
    lock["system"] = pipe.describe().to_dict()
    write_json(out_dir / "manifest.lock.json", lock)

    print(
        f"predict : {len(docs)} document(s) — système {identity.system_id!r}, "
        f"dataset {key!r}, split {split!r}, politique {policy!r}, "
        f"profil {loaded.profile.profile!r}"
    )
    for status in ("ok", "partial", "error"):
        if counts.get(status):
            print(f"  {status} : {counts[status]}")
    print(f"  sortie : {out_dir}")
    return 1 if counts.get("error") else 0

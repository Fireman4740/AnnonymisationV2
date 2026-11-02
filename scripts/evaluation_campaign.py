"""Campagne fonctionnelle sur échantillons relationnellement complets.

Les documents sont choisis avant prédiction et identiques entre systèmes.
Les tables gold ne sont jamais tronquées au nombre de documents. Ce protocole
exerce les métriques disponibles ; il ne produit pas une mesure de performance
représentative ni des chiffres comparables aux publications.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import urllib.request
from collections.abc import Iterable, Iterator
from contextlib import nullcontext
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import quote, urlparse

from anonymisation.datasets import REGISTRY
from anonymisation.datasets.base import DatasetAdapter
from anonymisation.datasets.ingest import ingest
from anonymisation.datasets.manifest import load_manifest
from anonymisation.llm.config import LlmBackendsConfig, load_backends_config
from anonymisation.schema.io import sha256_file, write_json

CONFIG = Path("configs/evaluation/campaign.json")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
SPIA_REVISION = "3fa78a1b3c75788c6294f40024fc79e1ef42923f"
SPIA_FILES = {
    "spia_tab_144.jsonl": "6b76fe4c26ea619a12913aa3601b31c61acef29b99a7293098876f6ec56b03ac",
    "spia_panorama_531.jsonl": "0d94babe7e2ce19c82a7d4eda4f9d169f1797e0ba5170d291bb01ace0fd0d139",
}


def fetch(url: str, path: Path, expected: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        temporary = path.with_suffix(path.suffix + ".download")
        headers = {}
        if url.startswith("https://huggingface.co/") and os.environ.get("HF_TOKEN"):
            headers["Authorization"] = "Bearer " + os.environ["HF_TOKEN"]
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=120) as source, temporary.open("wb") as out:
            for chunk in iter(lambda: source.read(1 << 20), b""):
                out.write(chunk)
        temporary.replace(path)
    actual = sha256_file(path)
    if expected is not None and actual != expected:
        raise ValueError(f"Source divergente : {path.name}")
    print("SOURCE", json.dumps({"url": url, "sha256": actual, "bytes": path.stat().st_size}), flush=True)


def choose(candidates: Iterable[Any], key: str, split: str, count: int,
           max_chars: int, seed: int, *, capped: bool = False) -> tuple[list[Any], dict[str, Any]]:
    """Échantillonne exactement ``count`` lignes, de façon stable et stratifiée.

    Le parcours complet évite le biais de préfixe des anciens ``islice``.
    Seuls les ``count`` meilleurs rangs SHA-256 par strate restent en mémoire.
    """
    if count < 1:
        raise ValueError("la taille d'échantillon doit être positive")
    if key == "ratbench":
        field, groups = "difficulty", (1, 2, 3)
    elif key == "spia":
        field, groups = "source_corpus", ("tab", "panorama")
    else:
        field, groups = None, ("all",)
    quotas = {
        group: count // len(groups) + (i < count % len(groups))
        for i, group in enumerate(groups)
    }
    heaps: dict[Any, list[tuple[int, str, Any]]] = {group: [] for group in groups}
    available = {group: 0 for group in groups}
    unexpected: dict[str, int] = {}
    seen: set[str] = set()

    for doc in candidates:
        if not 0 < len(doc.text) <= max_chars:
            continue
        if capped:
            if doc.doc_id in seen:
                raise ValueError(f"{key}/{split} : doc_id dupliqué : {doc.doc_id}")
            seen.add(doc.doc_id)
        group = doc.meta.get(field) if field else "all"
        if group not in quotas:
            label = repr(group)
            unexpected[label] = unexpected.get(label, 0) + 1
            continue
        available[group] += 1
        capacity = count if capped else quotas[group]
        if capacity == 0:
            continue
        rank = int.from_bytes(hashlib.sha256(
            f"{seed}\0{key}\0{split}\0{doc.doc_id}".encode()
        ).digest(), "big")
        heap = heaps[group]
        item = (-rank, doc.doc_id, doc)
        if len(heap) < capacity:
            heapq.heappush(heap, item)
        elif rank < -heap[0][0]:
            heapq.heapreplace(heap, item)

    if unexpected:
        raise ValueError(f"{key}/{split} : strates inconnues pour {field}: {unexpected}")
    if capped:
        quotas = split_budget(available, min(count, sum(available.values())))
    shortages = {str(group): {"requested": quotas[group], "available": available[group]}
                 for group in groups if available[group] < quotas[group]}
    if shortages:
        raise ValueError(
            f"{key}/{split} : échantillon incomplet ; quotas exacts requis, pénuries={shortages}"
        )

    selected: list[Any] = []
    strata: dict[str, dict[str, int]] = {}
    for group in groups:
        heap = heaps[group]
        ordered = sorted(heap, key=lambda item: (-item[0], item[1]))[:quotas[group]]
        selected.extend(item[2] for item in ordered)
        strata[str(group)] = {
            "requested": quotas[group],
            "available": available[group],
            "selected": len(ordered),
        }
    return selected, {
        "method": "sha256-bottom-k-capped-balanced-v2" if capped else "sha256-bottom-k-v1",
        "seed": seed,
        "requested": count,
        "selected": len(selected),
        "stratified_by": field,
        "strata": strata,
    }


class CompleteSample(DatasetAdapter):
    """Vue des documents sélectionnés et de TOUTES leurs annotations/tâches."""

    def __init__(self, source: DatasetAdapter, documents: dict[str, list[Any]]) -> None:
        super().__init__(source.manifest, source.raw_dir)
        self.key = source.key
        self.source = source
        self.documents = documents
        self.ids = {split: {doc.doc_id for doc in docs} for split, docs in documents.items()}
        self.people = {
            split: ids | {person for doc in documents[split]
                          for person in (*doc.subject_ids, doc.author_id) if person}
            for split, ids in self.ids.items()
        }

    def splits(self) -> tuple[str, ...]:
        return tuple(self.documents)

    def download(self, *, force: bool = False) -> Any:
        return self.source.download(force=force)

    def iter_documents(self, split: str) -> Iterator[Any]:
        yield from self.documents[split]

    def iter_annotations(self, split: str) -> Iterator[Any]:
        for row in self.source.iter_annotations(split):
            if row.doc_id in self.ids[split]:
                yield row

    def iter_profiles(self, split: str) -> Iterator[Any]:
        for row in self.source.iter_profiles(split):
            if row.person_id in self.people[split]:
                yield row

    def iter_tasks(self, split: str) -> Iterator[Any]:
        for row in self.source.iter_tasks(split):
            if row.doc_id in self.ids[split]:
                yield row

    def iter_combinations(self, split: str) -> Iterator[Any]:
        # Une combinaison trans-document n'est conservée que si tous ses
        # documents et donc leurs annotations font partie du pivot échantillonné.
        for row in self.source.iter_combinations(split):
            if row.doc_ids and set(row.doc_ids) <= self.ids[split]:
                yield row


def split_budget(available: dict[str, int], count: int) -> dict[str, int]:
    """Répartit exactement le budget dataset en conservant les splits source.

    Les splits courts contribuent à hauteur de leur capacité ; les places
    restantes sont distribuées aux autres splits, jamais par duplication.
    """
    if count < 1 or sum(available.values()) < count:
        raise ValueError(f"budget dataset incomplet : demandé={count}, disponibles={available}")
    quotas = {split: 0 for split in available}
    remaining = count
    while remaining:
        for split, capacity in available.items():
            if remaining and quotas[split] < capacity:
                quotas[split] += 1
                remaining -= 1
    return quotas


#: Codes de sortie de ``score`` : 0 publiable, 1 publication bloquée (C4,
#: arbre modifié — la scorecard existe et est un résultat), 2 erreur d'usage.
SCORE_RESULT_CODES = (0, 1)


def stage_failures(stages: dict[str, int], replay_identical: bool) -> list[str]:
    """Étapes en échec d'une entrée de campagne, dans l'ordre d'exécution.

    ``score`` n'échoue qu'avec un code hors de :data:`SCORE_RESULT_CODES` ;
    le replay doit rendre le même code et la même scorecard au bit près.
    """
    failed = [name for name in ("predict", "attack") if stages.get(name, 0)]
    if stages.get("score") not in SCORE_RESULT_CODES:
        failed.append("score")
    replay = stages.get("replay")
    if replay not in SCORE_RESULT_CODES or replay != stages.get("score") or not replay_identical:
        failed.append("replay")
    return failed


def disjoint_training_documents(candidates: Iterable[Any], held_out: Iterable[Any],
                                excluded: dict[str, int]) -> Iterator[Any]:
    """Retire les chevauchements avant l'échantillonnage du train auxiliaire.

    Ne consulte aucun label du test. L'évaluateur garde son propre contrôle
    train/test après ingestion : ce filtrage ne remplace pas cette vérification.
    """
    documents = tuple(held_out)
    ids = {d.doc_id for d in documents}
    texts = {d.text for d in documents}
    people = {p for d in documents for p in (*d.subject_ids, d.author_id) if p}
    threads = {d.thread_id for d in documents if d.thread_id}
    for document in candidates:
        if (document.doc_id in ids or document.text in texts
                or people.intersection((*document.subject_ids, document.author_id))
                or document.thread_id and document.thread_id in threads):
            excluded["overlap"] = excluded.get("overlap", 0) + 1
            continue
        yield document


def prepare(key: str, splits: list[str], cfg: dict[str, Any], cache: Path,
            official_rat_root: Path) -> dict[str, Any]:
    os.environ["ANONV2_V1_DATASETS"] = str(official_rat_root if key == "ratbench"
                                             else Path(cfg["legacy_root"]))
    raw = Path("data/raw") / key
    if key == "spia":
        raw = cache / "SPIA"
        for name, digest in SPIA_FILES.items():
            fetch(f"https://raw.githubusercontent.com/maisonOP/spia/{SPIA_REVISION}/data/spia/{name}",
                  raw / name, digest)
        os.environ["ANONV2_SPIA_ROOT"] = str(raw.resolve())
    elif key == "panorama":
        raw = Path(cfg.get("source_overrides", {}).get(key,
                   os.environ.get("ANONV2_PANORAMA_ROOT", str(cache / "PANORAMA"))))
        os.environ["ANONV2_PANORAMA_ROOT"] = str(raw.resolve())
        fetch("https://huggingface.co/datasets/srirxml/PANORAMA/resolve/"
              "f0037fdba4d2f2be771079c3388d48a1242af3e0/data/train-00000-of-00001.parquet",
              raw / "train.parquet")
    elif key == "openpii":
        raw = cache / "OpenPII"
    loaded = load_manifest(Path("configs/datasets") / f"{key}.yaml")
    adapter = REGISTRY[key](loaded.manifest, raw)
    if key == "openpii":
        adapter.download()  # vérifie le SHA-256 agrégé de la release figée
    selected = {}
    sampling = {}
    target_splits = list(dict.fromkeys(splits))
    budget = {split: cfg["documents_per_split"] for split in splits}
    capped = cfg.get("cap_documents", False)
    if capped:
        available = {part: sum(0 < len(doc.text) <= cfg["max_document_chars"]
                              for doc in adapter.iter_documents(part)) for part in splits}
        budget = split_budget(available, min(cfg["documents_per_dataset"], sum(available.values())))
    elif "documents_per_dataset" in cfg:
        if len(splits) == 1:
            budget = {splits[0]: cfg["documents_per_dataset"]}
        else:
            available = {split: sum(0 < len(doc.text) <= cfg["max_document_chars"]
                                    for doc in adapter.iter_documents(split)) for split in splits}
            budget = split_budget(available, cfg["documents_per_dataset"])
    conditional = cfg.get("conditional_evaluations", {}).get(key, {})
    auxiliary_train = None
    if conditional.get("task"):
        auxiliary_train = conditional.get("train_split", "train")
        if auxiliary_train in splits or any(part not in {"test", "eval"} for part in splits):
            raise ValueError("évaluation conditionnelle : splits évalués test/eval et train auxiliaire distinct requis")
        target_splits.append(auxiliary_train)
        budget[auxiliary_train] = conditional.get("training_documents", 2000)
    for split in target_splits:
        count = budget[split]
        if count == 0:
            continue
        candidates = adapter.iter_documents(split)
        excluded_overlap: dict[str, int] = {}
        if split == auxiliary_train:
            candidates = disjoint_training_documents(
                candidates, (d for part in splits for d in selected[part]), excluded_overlap)
        selected[split], sampling[split] = choose(
            candidates, key, split, count,
            cfg["max_document_chars"], cfg["sampling_seed"], capped=capped and split != auxiliary_train)
        if split == auxiliary_train:
            sampling[split]["train_test_disjointness"] = {
                "excluded_overlap": excluded_overlap.get("overlap", 0),
                "fields": ["doc_id", "text", "author_id", "subject_ids", "thread_id"],
            }
    sampled = CompleteSample(adapter, selected)
    result = ingest(sampled, loaded.manifest, split="all", output_root=Path("data/processed"),
                    resolution=loaded.resolution)
    info = {"dataset": key, "status": result.status, "counts": result.counts,
            "synthetic": loaded.manifest.structure.synthetic,
            "evaluation_splits": [split for split in splits if budget[split] > 0],
            "evaluation_documents": sum(budget[part] for part in splits),
            "split_budget": budget,
            "sampling": sampling,
            "selection": {split: [{"doc_id": doc.doc_id, "chars": len(doc.text),
                                      "language": doc.language, "meta": doc.meta}
                                    for doc in docs] for split, docs in selected.items()},
            "files": result.files, "protocol": loaded.manifest.evaluation.protocol}
    write_json(Path("runs/campaign/selection") / f"{key}.json", info)
    print("INGEST_RESULT", json.dumps({k: v for k, v in info.items() if k != "selection"},
                                      ensure_ascii=False, sort_keys=True), flush=True)
    return info


def conditional_evaluation_args(cfg: dict[str, Any], key: str, directory: Path) -> list[str] | None:
    """Étape optionnelle avant score ; juge local uniquement si configuré."""
    spec = cfg.get("conditional_evaluations", {}).get(key) or {}
    local = cfg.get("local_quality") or {}
    use_local = key in local.get("datasets", [])
    detailed = cfg.get('detailed_quality') or {}
    use_detailed = key in detailed.get('datasets', [])
    if not spec and not use_local and not use_detailed:
        return None
    args = ["evaluate", "--run", str(directory)]
    if spec.get("task"):
        args += ["--task", spec["task"], "--train-split", spec.get("train_split", "train")]
    if spec.get("population"):
        args += ["--population", spec["population"], "--k-threshold", str(spec.get("k_threshold", 10))]
    if use_local:
        args += ["--local-quality-backend", local["backend"], "--local-quality-workers", str(local["workers"])]
    if use_detailed:
        args += ['--detailed-quality-backend', detailed['backend']]
        if not use_local:
            args += ['--local-quality-workers', str(detailed['workers'])]
        elif detailed['workers'] != local['workers']:
            raise ValueError('les deux juges doivent utiliser le même nombre de workers')
        if (detailed.get('facts') or {}).get(key):
            args += ['--quality-facts', detailed['facts'][key]]
    if not spec.get("task") and not spec.get("population") and not use_local and not use_detailed:
        raise ValueError("évaluation conditionnelle : task, population ou qualité locale requis")
    return args


def remote_authorized(cfg: dict[str, Any], key: str, synthetic: bool) -> bool:
    """Envoi externe (OpenRouter) autorisé pour ce corpus ?

    Corpus synthétique : oui. Corpus réel : seulement s'il est nommé dans
    ``remote_authorized_datasets`` (autorisation explicite de l'utilisateur,
    corpus par corpus) ou si l'autorisation globale est donnée. Les deux clés
    sont obligatoires : leur absence n'est jamais lue comme un refus implicite.
    """
    listed = cfg["remote_authorized_datasets"]
    if not isinstance(listed, list):
        raise ValueError("campaign.json : `remote_authorized_datasets` doit être une liste")
    return bool(synthetic or cfg["remote_real_corpora_authorized"] or key in listed)


def system_variants(cfg: dict[str, Any], remote_allowed: bool) -> list[dict[str, Any]]:
    """Toutes les politiques ; attaque SPIA sur les variantes de référence."""
    variants = []
    for spec in cfg["systems"]:
        if spec.get("remote_only") and not remote_allowed:
            continue
        policies = spec.get("policies") or [None]
        for policy in policies:
            name = spec["system"] + (f"-{policy}" if policy else "")
            spia_attack = spec.get("spia_attack", False) or policy in spec.get("spia_attack_policies", ())
            disclosure = spec.get("disclosure_policy")
            if disclosure is not None:
                name += "+disclosure"
            variants.append({"name": name, "system": spec["system"], "policy": policy,
                             "params": dict(spec.get("params") or {}), "spia_attack": spia_attack,
                             "disclosure_policy": disclosure})
    return variants


def disclosure_for(setting: str | dict[str, Any] | None, key: str) -> str | None:
    """Politique HIDE/KEEP d'un dataset : chaîne commune, ou table par dataset.

    Une table doit nommer le dataset ou porter une clé `default` explicite
    (valeur `null` permise) : un dataset oublié n'hérite de rien en silence.
    """
    if setting is None or isinstance(setting, str):
        return setting
    if key in setting:
        return setting[key]
    if "default" not in setting:
        raise ValueError(f"campaign.json : disclosure_policy sans entrée pour {key!r} ni `default`")
    return setting["default"]


def predict_args(cfg: dict[str, Any], key: str, split: str, variant: dict[str, Any],
                 directory: Path) -> list[str]:
    profile = {"llm-full": "llm_full", "llm-windowed": "llm_windowed", "llm-contextual": "llm_contextual", "llm-anchored": "llm_anchored",
               "hybrid-qi": "hybrid_qi"}.get(variant["system"], "deterministic")
    args = ["predict", "--dataset", key, "--split", split, "--system", variant["system"],
            "--profile", profile, "--out", str(directory)]
    limits = cfg.get("_evaluation_subset_limits")
    if cfg.get("evaluation_subset") is not None:
        # run_campaign valide l'appartenance et les empreintes avant les modèles.
        # Le constructeur d'arguments reste utilisable isolément, sans import du runner.
        count = (limits[key][split] if limits is not None else len(json.loads(
            Path(cfg["evaluation_subset"]["manifest"]).read_text())["datasets"][key][split]))
        args += ["--limit", str(count),
                 "--selection-manifest", cfg["evaluation_subset"]["manifest"]]
    if variant["policy"]:
        args += ["--policy", variant["policy"]]
    disclosure = disclosure_for(variant.get("disclosure_policy"), key)
    if disclosure:
        args += ["--disclosure-policy", disclosure]
    params = dict(variant["params"])
    if variant["system"] == "llm-full":
        params.update(backend=cfg["anonymizer_backend"],
                      max_output_tokens=cfg["llm_full_max_output_tokens"],
                      max_entities=cfg["llm_full_max_entities"])
    elif variant["system"] == "llm-windowed":
        params.setdefault("backend", cfg["anonymizer_backend"])
    for name, value in sorted(params.items()):
        args += ["--param", f"{name}={value}"]
    return args


def _subprocess(args: list[str]) -> tuple[int, str]:
    import subprocess

    print("COMMAND", " ".join(args), flush=True)
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    tail = (proc.stdout + proc.stderr)[-4000:]
    print(tail, flush=True)
    return proc.returncode, tail


def provider_price_caps(cfg: dict[str, Any]) -> dict[str, Any]:
    """Plafonds explicites en dollars par million de tokens ; zéro par défaut."""
    caps = cfg.get("provider_max_price", {"prompt": 0, "completion": 0})
    if not isinstance(caps, dict) or set(caps) != {"prompt", "completion"}:
        raise ValueError("provider_max_price : plafonds prompt/completion requis")
    for value in caps.values():
        try:
            price = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("provider_max_price : prix invalide") from exc
        if not price.is_finite() or price < 0:
            raise ValueError("provider_max_price : prix positif ou nul requis")
    return caps


def _is_local_base_url(base_url: str | None) -> bool:
    """Vrai seulement pour une boucle locale : aucun envoi hors de la machine."""
    host = urlparse(base_url).hostname if base_url else None
    return host in {"127.0.0.1", "localhost", "::1"}


def campaign_models(cfg: dict[str, Any], llm_cfg: LlmBackendsConfig) -> dict[str, Any]:
    """Décrit le routage des deux rôles et verrouille les seuls appels distants.

    Un backend local (serveur vLLM de la box) n'a ni tarif OpenRouter ni
    autorisation d'envoi externe à vérifier : le plafond de prix ne s'applique
    qu'aux backends dont l'URL n'est pas une boucle locale. Une URL distante
    inattendue reste traitée comme distante et doit donc respecter le plafond.
    """
    caps = provider_price_caps(cfg)
    models = {}
    for role in ("anonymizer_backend", "attacker_backend"):
        backend = llm_cfg.resolve(name=cfg[role])
        if not backend.model:
            raise ValueError(f"Backend sans modèle déclaré : {role}")
        remote = backend.kind in {"openai_compatible", "anthropic"} and not _is_local_base_url(
            backend.base_url
        )
        if remote and backend.extra_body.get("provider", {}).get("max_price") != caps:
            raise ValueError(f"Backend incompatible avec le plafond tarifaire : {role}")
        models[role] = {"backend": backend.name, "model": backend.model,
                        "extra_body": backend.extra_body, "remote": remote,
                        "default_max_output_tokens": backend.max_output_tokens}
    return models


def validate_provider_routes(cfg: dict[str, Any], models: dict[str, Any]) -> list[dict[str, Any]]:
    """Échoue avant les appels si aucune route ne respecte les prix déclarés.

    L'API publique expose des prix par token, mais ``max_price`` utilise des
    dollars par million de tokens. Le plafond reste aussi envoyé à chaque
    requête : un changement de prix après ce préflight ne permet aucun repli
    plus cher.
    """
    caps = provider_price_caps(cfg)
    reports = []
    for model in sorted({spec["model"] for spec in models.values() if spec.get("remote")}):
        url = f"{OPENROUTER_BASE}/models/{quote(model, safe='/')}/endpoints"
        with urllib.request.urlopen(url, timeout=30) as response:
            endpoints = json.load(response)["data"]["endpoints"]
        allowed = []
        for endpoint in endpoints:
            pricing = endpoint.get("pricing") or {}
            prices = {}
            try:
                for key in ("prompt", "completion"):
                    price = Decimal(str(pricing[key])) * 1_000_000
                    if not price.is_finite() or price < 0:
                        break
                    prices[key] = price
            except (KeyError, InvalidOperation):
                continue
            if len(prices) == 2 and all(prices[key] <= Decimal(str(caps[key])) for key in prices):
                allowed.append({"provider": endpoint.get("provider_name"),
                                "prices_per_million": {key: str(value) for key, value in prices.items()}})
        if not allowed:
            raise ValueError(f"Aucune route {model} sous le plafond tarifaire {caps} ; campagne non lancée")
        reports.append({"model": model, "allowed_routes": allowed})
    return reports


def run_campaign() -> int:
    import sys

    from evaluation_smoke import command, load_key

    cfg = json.loads(CONFIG.read_text())
    run_only = cfg.get("run_only")
    if run_only is not None:
        if (not isinstance(run_only, list) or not run_only
                or not all(isinstance(key, str) for key in run_only)):
            raise ValueError(
                "campaign.json : `run_only` doit être une liste non vide de clés de datasets"
            )
        unknown = sorted(set(run_only) - set(cfg["datasets"]))
        if unknown:
            raise ValueError(
                f"campaign.json : `run_only` contient des datasets absents de `datasets` : {unknown}"
            )
        # Le manifeste de cohorte reste celui de la sélection complète : on ne
        # restreint que l'exécution, jamais l'identité des données figées.
    run_systems = cfg.get("run_systems")
    if run_systems is not None:
        if (not isinstance(run_systems, list) or not run_systems
                or not all(isinstance(name, str) for name in run_systems)):
            raise ValueError(
                "campaign.json : `run_systems` doit être une liste non vide de systèmes"
            )
        unknown = sorted(set(run_systems) - {spec["system"] for spec in cfg["systems"]})
        if unknown:
            raise ValueError(
                f"campaign.json : `run_systems` contient des systèmes absents de `systems` : {unknown}"
            )
    baseline = cfg.get("baseline")
    frozen = None
    if baseline:
        from baseline_cohort import freeze_cohort, restore_cohort

        if baseline["phase"] == "freeze":
            freeze_cohort(cfg, prepare, Path.home() / ".cache/anonymisation-v2/datasets",
                          Path(os.environ["ANONV2_V1_DATASETS"]))
            return 0
        if baseline["phase"] != "evaluate":
            raise ValueError("baseline.phase : freeze ou evaluate requis")
        frozen = restore_cohort(cfg)
    from baseline_cohort import evaluation_subset_limits

    subset_limits = evaluation_subset_limits(cfg)
    if subset_limits is not None:
        cfg["_evaluation_subset_limits"] = subset_limits
        print("EVALUATION_SUBSET", json.dumps({
            "source_cohort": cfg["baseline"]["id"],
            "manifest": cfg["evaluation_subset"]["manifest"],
            "sha256": cfg["evaluation_subset"]["sha256"],
            "documents_per_dataset": cfg["evaluation_subset"]["documents_per_dataset"],
            "documents_evaluated": sum(sum(parts.values()) for parts in subset_limits.values()),
            "limits": subset_limits,
        }, sort_keys=True), flush=True)
    llm_cfg = load_backends_config()
    models = campaign_models(cfg, llm_cfg)
    uses_remote = any(spec.get("remote") for spec in models.values())
    if uses_remote:
        load_key()
    routes = validate_provider_routes(cfg, models)
    print("PROVIDER_PREFLIGHT", json.dumps(routes, sort_keys=True), flush=True)
    print("CAMPAIGN_CONFIG", json.dumps({**cfg, "models": models}, sort_keys=True), flush=True)
    official_rat_root = Path(os.environ["ANONV2_V1_DATASETS"])
    cache = Path.home() / ".cache/anonymisation-v2/datasets"
    # Clé de pseudonymisation réservée à ce test public, jamais une clé réelle.
    os.environ["ANONV2_PSEUDO_SECRET"] = "functional-evaluation-public-not-for-production"
    summary: dict[str, Any] = {"purpose": cfg["purpose"], "models": models,
                              "systems": cfg["systems"], "provider_preflight": routes,
                              "run_attacks": cfg.get("run_attacks", True),
                              "run_only": run_only, "run_systems": run_systems,
                              "evaluation_subset": cfg.get("evaluation_subset"),
                              "documents_per_dataset": cfg.get("documents_per_dataset"),
                              "datasets": [], "results": [], "failures": [],
                              "remote_skipped": [], "parity": {}, "audit": [],
                              "excluded_datasets": cfg.get("excluded_datasets", {}),
                              "not_executable_here": cfg["not_executable_here"]}
    if baseline:
        summary["cohort"] = {"id": baseline["id"], "manifest_sha256": sha256_file(Path(baseline["manifest"]))}
    ratbench_runs: list[Path] = []
    for key, splits in cfg["datasets"].items():
        if run_only is not None and key not in run_only:
            continue
        try:
            info = (frozen[key] if frozen is not None
                    else prepare(key, splits, cfg, cache, official_rat_root))
        except (OSError, ValueError, KeyError) as exc:
            failure = {"dataset": key, "stage": "ingest", "error": f"{type(exc).__name__}: {exc}"}
            summary["failures"].append(failure)
            print("CAMPAIGN_ERROR", json.dumps(failure, ensure_ascii=False), flush=True)
            continue
        summary["datasets"].append(info)
        remote_allowed = remote_authorized(cfg, key, info["synthetic"]) if uses_remote else True
        if uses_remote and not remote_allowed:
            summary["remote_skipped"].append({"dataset": key,
                "stages": ["llm-full", "attaque SPIA"],
                "reason": "autorisation explicite d'envoi externe des textes réels en attente"})

        def call(args: list[str], *, allow_api: bool = remote_allowed) -> int:
            guard = nullcontext() if allow_api else patch(
                "anonymisation.llm.client.LlmClient.complete",
                side_effect=RuntimeError("Corpus réel : appels LLM externes non autorisés"))
            with guard:
                return command(args)

        for split in info["evaluation_splits"]:
            if subset_limits is not None and subset_limits[key][split] == 0:
                continue
            for variant in system_variants(cfg, remote_allowed):
                if run_systems is not None and variant["system"] not in run_systems:
                    continue
                name = variant["name"]
                directory = Path("runs/campaign") / key / split / name
                entry: dict[str, Any] = {"dataset": key, "split": split, "system": name,
                                         "stages": {}, "spia_attack": variant["spia_attack"]}
                stages = entry["stages"]
                try:
                    stages["predict"] = call(predict_args(cfg, key, split, variant, directory))
                    if not (directory / "manifest.lock.json").is_file():
                        raise ValueError("prédiction sans lock")
                    score_args = ["score", "--run", str(directory), "--protocol", info["protocol"]]
                    run_attacks = cfg.get("run_attacks", True)
                    if key == "ratbench" and run_attacks:
                        ratbench_runs.append(directory)
                        stages["attack"] = call(["attack", "--run", str(directory), "--attacker",
                            "ratbench", "--backend", cfg["attacker_backend"],
                            "--workers", str(cfg["attack_workers"])])
                    if key == "spia" and run_attacks and remote_allowed and variant["spia_attack"]:
                        stages["attack_spia"] = call(["attack", "--run", str(directory), "--attacker",
                            "spia", "--backend", cfg["attacker_backend"],
                            "--workers", str(cfg["attack_workers"]),
                            "--max-output-tokens", str(cfg["spia_attack_max_output_tokens"])])
                    evaluate_args = conditional_evaluation_args(cfg, key, directory)
                    if evaluate_args is not None:
                        stages["evaluate"] = command(evaluate_args)
                        if stages["evaluate"]:
                            raise ValueError("évaluation conditionnelle échouée : aucune valeur de substitution")
                    with patch("anonymisation.llm.client.LlmClient.complete",
                               side_effect=RuntimeError("Scoring hors ligne : LLM interdit")):
                        stages["score"] = command(score_args)
                        card = json.loads((directory / "scorecard.json").read_text())
                        before = sha256_file(directory / "scorecard.json")
                        stages["replay"] = command(score_args)
                        entry["replay_identical"] = before == sha256_file(directory / "scorecard.json")
                    entry.update({field: card[field] for field in (
                        "primary", "diagnostic", "publishable", "publication_blockers", "status")})
                    entry["scorecard_sha256"] = before
                    entry["prediction_counts"] = card["accounting"]
                    failed = stage_failures(stages, entry["replay_identical"])
                    if stages.get("attack_spia"):
                        failed.append("attack_spia")
                    if failed:
                        summary["failures"].append({"dataset": key, "split": split, "system": name,
                                                    "stage": "pipeline", "failed": failed,
                                                    "stages": stages})
                except (OSError, ValueError, KeyError, RuntimeError) as exc:
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                    summary["failures"].append({"dataset": key, "split": split,
                                                "system": name, "error": entry["error"]})
                summary["results"].append(entry)
                print("CAMPAIGN_RESULT", json.dumps(entry, ensure_ascii=False, sort_keys=True), flush=True)
                write_json(Path("runs/campaign/summary.json"), summary)

    # Contrôles bloquants hors modèle : équivalence avec le code RAT-Bench
    # officiel sur les sorties figées, puis fiches d'audit de chaque run.
    attacked = [run for run in ratbench_runs if (run / "attacks.jsonl").is_file()]
    if attacked:
        lock = json.loads((attacked[0] / "manifest.lock.json").read_text())
        source_dir = Path(lock["data_version"]["source"]["directory"])
        split = lock["run"]["split"]
        code, tail = _subprocess([
            "uv", "run", "--isolated", "--no-project", "--with", "levenshtein==0.27.3", "--with", "rapidfuzz==3.14.3",
            "--with", "numpy", "python", "scripts/parity_ratbench.py",
            "--profiles", f"data/processed/ratbench/{split}/profiles.jsonl",
            "--maps", str(source_dir / "cache" / "maps"),
            "--out", "runs/campaign/parity-ratbench.json", *map(str, attacked)])
        summary["parity"] = {"exit_code": code, "report": "runs/campaign/parity-ratbench.json",
                             "tail": tail[-800:]}
        if code:
            summary["failures"].append({"stage": "parity-ratbench", "exit_code": code})
    for entry in summary["results"]:
        directory = Path("runs/campaign") / entry["dataset"] / entry["split"] / entry["system"]
        if not (directory / "manifest.lock.json").is_file():
            continue
        out = Path("runs/campaign/audit") / entry["dataset"] / entry["split"] / entry["system"]
        code, _ = _subprocess([sys.executable, "scripts/audit_fiches.py", str(directory),
                               "--processed", "data/processed", "--out", str(out)])
        audit = json.loads((out / "audit.json").read_text())["summary"] if (out / "audit.json").is_file() else None
        summary["audit"].append({"run": str(directory), "exit_code": code, "summary": audit})
        if code:
            summary["failures"].append({"stage": "audit", "run": str(directory), "exit_code": code})
    write_json(Path("runs/campaign/summary.json"), summary)
    compact = {"purpose": summary["purpose"], "models": models, "failures": summary["failures"],
               "run_only": summary["run_only"], "run_systems": summary["run_systems"],
               "excluded_datasets": summary["excluded_datasets"],
               "not_executable_here": summary["not_executable_here"],
               "remote_skipped": summary["remote_skipped"], "parity": summary["parity"],
               "results": [{k: r.get(k) for k in ("dataset", "split", "system", "stages",
                   "prediction_counts", "replay_identical", "publishable", "status", "error")}
                   for r in summary["results"]]}
    print("FINAL_CAMPAIGN_SUMMARY", json.dumps(compact, ensure_ascii=False, sort_keys=True), flush=True)
    return 1 if summary["failures"] else 0

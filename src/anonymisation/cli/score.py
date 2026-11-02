"""Commande ``anonv2 score`` (C-4, SPEC-10 §5, audit §12.6).

Le scoring ne charge ni détecteur ni modèle : il relit uniquement les
prédictions, le pivot gold et le lock figé par ``predict``. Une modification
des métriques peut donc être rejouée sans campagne de prédiction.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from anonymisation.metrics.contracts import MetricDirection, MetricStatus, MetricValue
from anonymisation.metrics.scorecard import (
    ScorecardError,
    build_scorecard,
    validate_reproducibility,
)
from anonymisation.schema.integrity import (
    DataIntegrityError,
    locked_files,
    verify_pivot_files,
    verify_run_outputs,
)
from anonymisation.schema.io import read_jsonl, write_json
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import TAXONOMY_VERSION

REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_ROOT = REPO_ROOT / "data" / "processed"
DATASETS_CONFIG = REPO_ROOT / "configs" / "datasets"
DISCLOSURE_FILE = REPO_ROOT / "configs" / "policy" / "disclosure.yaml"
LOCK_NAME = "manifest.lock.json"
PREDICTIONS_NAME = "predictions.jsonl"
SCORECARD_NAME = "scorecard.json"
DOCUMENTS_NAME = "documents.jsonl"


class ScoreError(ValueError):
    """Erreur de run, de protocole ou de pivot gold actionnable."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScoreError(f"Fichier JSON illisible : {path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise ScoreError(f"Fichier JSON invalide : {path} (mapping attendu)")
    return payload


def _read_predictions(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ScoreError(f"Prédictions absentes : {path}")
    records: list[dict[str, Any]] = []
    line_number: int | str = "?"
    try:
        with path.open("r", encoding="utf-8") as handle:
            for _line_number, raw_line in enumerate(handle, start=1):
                line_number = _line_number
                if not raw_line.strip():
                    continue
                payload = json.loads(raw_line)
                if not isinstance(payload, dict):
                    raise ValueError("mapping attendu")
                if not payload.get("doc_id"):
                    raise ValueError("doc_id absent")
                records.append(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ScoreError(f"Prédiction invalide : {path}:{line_number} ({exc})") from exc
    return records


def _gold_exhaustive(dataset: str) -> bool:
    """Exhaustivité du gold de spans déclarée par le manifeste — jamais supposée."""
    from anonymisation.datasets.manifest import GoldScope

    config = DATASETS_CONFIG / f"{dataset}.yaml"
    raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    scope = ((raw or {}).get("evaluation") or {}).get("gold_scope")
    if scope is None:
        raise ScoreError(
            f"{config} : `evaluation.gold_scope` absent. Déclarer `exhaustive` "
            "(le gold annote-t-il tous les identifiants du texte ?) et `reason`."
        )
    try:
        return GoldScope.model_validate(scope).exhaustive
    except ValueError as exc:
        raise ScoreError(f"{config} : `evaluation.gold_scope` invalide : {exc}") from exc


def _protocol_info(dataset: str, requested: str) -> tuple[str, str, MetricStatus]:
    """Résout version/statut depuis le manifeste, sans charger le pipeline.

    Aucun repli : un manifeste absent, une version non déclarée ou un statut
    inconnu font échouer le score. Un statut deviné (``DIAGNOSTIC`` par défaut)
    ou une version supposée (``"1"``) rendraient deux scorecards en apparence
    comparables alors qu'elles relèvent de protocoles différents.
    """
    config = DATASETS_CONFIG / f"{dataset}.yaml"
    if not config.is_file():
        raise ScoreError(
            f"Manifeste absent pour {dataset!r} : {config}. Le protocole "
            "d'évaluation (nom, version, statut par défaut) doit être déclaré "
            "dans `evaluation:` du manifeste."
        )
    try:
        raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ScoreError(f"Manifeste illisible pour {dataset!r} : {config} ({exc})") from exc
    evaluation = raw.get("evaluation") if isinstance(raw, dict) else None
    if not isinstance(evaluation, dict):
        raise ScoreError(f"{config} : bloc `evaluation:` absent ou invalide.")
    declared = evaluation.get("protocol")
    if declared and declared != requested:
        raise ScoreError(
            f"Protocole incompatible : le dataset {dataset!r} déclare {declared!r}, "
            f"pas {requested!r}"
        )
    for field in ("protocol_version", "default_metric_status"):
        if evaluation.get(field) in (None, ""):
            raise ScoreError(f"{config} : `evaluation.{field}` non déclaré.")
    version = str(evaluation["protocol_version"])
    raw_status = str(evaluation["default_metric_status"]).lower()
    try:
        status = MetricStatus(raw_status)
    except ValueError as exc:
        raise ScoreError(
            f"{config} : `evaluation.default_metric_status` = {raw_status!r} "
            f"inconnu ; valeurs admises : {[m.value for m in MetricStatus]}."
        ) from exc
    return requested, version, status


def _verify_inputs(
    run_dir: Path, lock: Mapping[str, Any], dataset: str, split: str
) -> dict[str, Any]:
    """Vérifie seulement le gold et les prédictions effectivement lus."""
    context = f"Run {run_dir}"
    try:
        files = locked_files(lock.get("data_version"), context=context)
        root = PROCESSED_ROOT / dataset
        pivot = verify_pivot_files(
            root,
            split,
            (DOCUMENTS_NAME, "annotations.jsonl"),
            files,
            context=context,
            required=(DOCUMENTS_NAME,),
        )
        outputs = verify_run_outputs(
            run_dir, lock.get("outputs"), (PREDICTIONS_NAME,), context=context
        )
    except DataIntegrityError as exc:
        raise ScoreError(str(exc)) from exc
    return {"pivot": dict(sorted(pivot.items())), "run": outputs}


def _load_gold(
    dataset: str, split: str
) -> tuple[dict[str, Document], dict[str, tuple[Annotation, ...]]]:
    base = PROCESSED_ROOT / dataset / split
    documents_path = base / "documents.jsonl"
    annotations_path = base / "annotations.jsonl"
    if not documents_path.is_file():
        raise ScoreError(
            f"Pivot gold absent pour {dataset!r} / split {split!r} "
            f"(attendu : {documents_path})"
        )
    # Annotations absentes = corpus d'utilité pure. C'est légitime seulement
    # parce que `_verify_inputs` a déjà refusé un fichier annoncé par le lock
    # mais manquant : l'absence ici est déclarée, jamais devinée.
    try:
        documents = {
            document.doc_id: document
            for document in read_jsonl(documents_path, Document)
        }
        grouped: dict[str, list[Annotation]] = {}
        if annotations_path.is_file():
            for annotation in read_jsonl(annotations_path, Annotation):
                grouped.setdefault(annotation.doc_id, []).append(annotation)
    except (OSError, ValueError) as exc:
        raise ScoreError(f"Pivot gold invalide : {base} ({exc})") from exc
    return documents, {doc_id: tuple(values) for doc_id, values in grouped.items()}





#: Versions des étapes figées lisibles par ce scorer. L'attaque RAT-Bench v1
#: lisait la réponse en JSON avant le format ligne à ligne officiel, et
#: comptait un attribut omis comme une erreur : ses sorties ne sont pas
#: comparables et doivent être régénérées.
_FROZEN_VERSIONS = {"ratbench-staab-correctmatch": "2", "mean-utility-spia": "1"}
ATTACK_LOCK_NAME = "attack.lock.json"
ATTACKS_NAME = "attacks.jsonl"


def _load_frozen(
    run_dir: Path, predictions_sha256: str, lock_name: str, rows_name: str,
    *, expected_doc_ids: set[str], expected_protocol: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Sorties figées d'une étape optionnelle (attaque, juge), vérifiées, ou ``None``.

    Refuse une étape menée sur d'AUTRES prédictions que celles du run, ou dont
    le fichier de sortie a été modifié : sinon la métrique décrirait un autre
    texte que celui scoré.
    """
    lock_path = run_dir / lock_name
    if not lock_path.is_file():
        if (run_dir / rows_name).is_file():
            raise ScoreError(f"{run_dir / rows_name} sans {lock_name} : sortie non vérifiable")
        return None
    lock = _read_json(lock_path)
    expected_version = _FROZEN_VERSIONS[expected_protocol]
    if lock.get("protocol") != expected_protocol or str(lock.get("protocol_version")) != expected_version:
        raise ScoreError(
            f"{lock_path} : protocole/version {lock.get('protocol')}/{lock.get('protocol_version')} "
            f"non pris en charge (attendu {expected_protocol}/{expected_version}) — relancer l'étape"
        )
    run_lock = _read_json(run_dir / LOCK_NAME)
    split = str(run_lock["run"]["split"])
    # Lecture historique explicite ; le scorer actif ne charge plus le juge.
    gold_name = "documents.jsonl" if expected_protocol == "mean-utility-spia" else "profiles.jsonl"
    expected_gold = (run_lock.get("data_version", {}).get("files") or {}).get(f"{split}/{gold_name}")
    if not expected_gold or (lock.get("inputs") or {}).get(gold_name) != expected_gold:
        raise ScoreError(f"{lock_path} : empreinte gold `{gold_name}` divergente ou absente")
    attacked = (lock.get("inputs") or {}).get("predictions.jsonl")
    if attacked != predictions_sha256:
        raise ScoreError(
            f"{lock_path} : étape menée sur d'autres prédictions (empreinte "
            f"{str(attacked)[:12]}… ≠ {predictions_sha256[:12]}…) — la relancer"
        )
    try:
        verify_run_outputs(run_dir, lock.get("outputs"), (rows_name,), context=f"{lock_name} {run_dir}")
    except DataIntegrityError as exc:
        raise ScoreError(str(exc)) from exc
    try:
        rows = [json.loads(line) for line in (run_dir / rows_name).read_text(encoding="utf-8").splitlines()
                if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise ScoreError(f"{rows_name} illisible : {exc}") from exc
    if any(not isinstance(row, dict) or not isinstance(row.get("doc_id"), str)
           or row.get("status") not in ("ok", "error") for row in rows):
        raise ScoreError(f"{rows_name} : doc_id ou statut invalide")
    ids = [row["doc_id"] for row in rows]
    if len(set(ids)) != len(ids) or set(ids) != expected_doc_ids:
        raise ScoreError(f"{rows_name} : couverture incomplète, étrangère ou dupliquée des documents")
    errors = sum(row["status"] == "error" for row in rows)
    rate = errors / len(rows) if rows else 1.0
    if (lock.get("documents") != len(rows) or lock.get("documents_error") != errors
            or lock.get("error_rate") != rate or lock.get("publishable") != (rate <= 0.05)):
        raise ScoreError(f"{lock_path} : comptabilité divergente des sorties figées")
    return rows, lock




SPIA_ATTACK_LOCK_NAME = "spia_attack.lock.json"
SPIA_ATTACKS_NAME = "spia_attacks.jsonl"


def _load_spia_attack(
    run_dir: Path, run_lock: Mapping[str, Any], predictions_sha256: str, *,
    expected_doc_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Attaque SPIA figée, vérifiée contre ce run et ce gold source, ou ``None``."""
    lock_path = run_dir / SPIA_ATTACK_LOCK_NAME
    if not lock_path.is_file():
        if (run_dir / SPIA_ATTACKS_NAME).is_file():
            raise ScoreError(f"{run_dir / SPIA_ATTACKS_NAME} sans {SPIA_ATTACK_LOCK_NAME}")
        return None
    lock = _read_json(lock_path)
    if (lock.get("protocol"), str(lock.get("protocol_version"))) != ("spia-original", "1"):
        raise ScoreError(f"{lock_path} : protocole/version non pris en charge")
    inputs = lock.get("inputs") or {}
    if inputs.get("predictions.jsonl") != predictions_sha256:
        raise ScoreError(f"{lock_path} : attaque menée sur d'autres prédictions — la relancer")
    expected_gold = ((run_lock.get("data_version") or {}).get("source") or {}).get("fingerprint")
    if not expected_gold or inputs.get("gold_source_fingerprint") != expected_gold:
        raise ScoreError(f"{lock_path} : gold SPIA source divergent ou absent")
    try:
        verify_run_outputs(run_dir, lock.get("outputs"), (SPIA_ATTACKS_NAME,),
                           context=f"{SPIA_ATTACK_LOCK_NAME} {run_dir}")
    except DataIntegrityError as exc:
        raise ScoreError(str(exc)) from exc
    rows = [json.loads(line) for line in
            (run_dir / SPIA_ATTACKS_NAME).read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [row.get("doc_id") for row in rows]
    if len(set(ids)) != len(ids) or set(ids) != expected_doc_ids:
        raise ScoreError(f"{SPIA_ATTACKS_NAME} : couverture incomplète, étrangère ou dupliquée")
    errors = sum(row.get("status") != "ok" for row in rows)
    rate = errors / len(rows) if rows else 1.0
    if (lock.get("documents") != len(rows) or lock.get("documents_error") != errors
            or lock.get("error_rate") != rate):
        raise ScoreError(f"{lock_path} : comptabilité divergente des sorties figées")
    return rows, lock


def _quasileak_d8(
    lock: Mapping[str, Any],
    run_dir: Path,
    split: str,
    capabilities: frozenset[str],
    protocol_version: str,
) -> dict[str, dict[str, Any]]:
    """P-GF1 officiel et E_R pré-politique via l'adaptateur de l'annexe D.8.

    Les sources brutes sont relues depuis le lock d'ingestion (empreinte
    revérifiée) ; le scorer officiel recopié tourne sans modèle (C5). La table
    d'attributs est celle de la politique de divulgation du run, sinon la table
    par défaut déclarée dans ``configs/policy/disclosure.yaml``.
    """
    from anonymisation.datasets._local import fingerprint
    from anonymisation.metrics import quasileak_official as official
    from anonymisation.metrics.quasileak_export import (
        ER_PROTOCOL,
        EXPORT_PROTOCOL,
        export_run,
        pre_policy_evidence_recall,
    )
    from anonymisation.schema.disclosure import load_config

    def metric(name: str, value: Any, status: MetricStatus, proto: str, details: dict) -> dict[str, Any]:
        return MetricValue(name=name, value=value, protocol=proto, protocol_version=protocol_version,
                           status=status, direction=MetricDirection.MAXIMIZE, details=details).to_dict()

    if "decisions" not in capabilities:
        reason = {"reason": "système sans capacité 'decisions' : aucun span retenu à adapter"}
        return {"quasileak_pgf1_d8": metric("quasileak_pgf1_d8", None, MetricStatus.UNAVAILABLE, EXPORT_PROTOCOL, reason),
                "quasileak_er_pre_policy": metric("quasileak_er_pre_policy", None, MetricStatus.UNAVAILABLE,
                                                  ER_PROTOCOL, reason)}
    source = (lock.get("data_version") or {}).get("source") or {}
    files = {Path(p).name: Path(p) for p in source.get("files") or ()}
    data, manifest = files.get("quasileak_bench_data_full.jsonl"), files.get("split_manifest.json")
    if data is None or manifest is None or not data.is_file() or not manifest.is_file():
        raise ScoreError("QuasiLeak : sources brutes du lock d'ingestion introuvables ; "
                         "relancer scripts/fetch_quasileak.py à l'emplacement verrouillé")
    if fingerprint(list(files.values())) != source.get("fingerprint"):
        raise ScoreError("QuasiLeak : sources modifiées depuis l'ingestion (empreinte divergente)")
    config = load_config(DISCLOSURE_FILE)
    disclosure = lock.get("disclosure") or {}
    table = disclosure.get("attribute_table") if disclosure.get("id") else config.default_adapter_table
    predictions = _read_predictions(run_dir / PREDICTIONS_NAME)
    ids = [str(p["doc_id"]) for p in predictions]
    selection = run_dir / "quasileak_d8_selection.json"
    write_json(selection, ids)
    wanted = set(ids)
    rows = [r for r in official.official.read_jsonl(data) if r["sample_id"] in wanted]
    out = run_dir / "quasileak_d8_groups.jsonl"
    export = export_run(run_dir, selection, out, mapping=config.category_to_attribute(table),
                        dataset_sha256=official.DATA_SHA256, split_sha256=official.SPLIT_SHA256,
                        policies={r["sample_id"]: r["policy"] for r in rows}, table=table)
    common = {"attribute_table": table, "export": export,
              "reference": "Zhu et al., arXiv:2610.21333, §5.3 et annexe D.8 (adaptation des détecteurs à spans)"}
    if export["errors"]:
        reason = {**common, "reason": f"{export['errors']} document(s) en erreur : score officiel refusé (C4)"}
        return {"quasileak_pgf1_d8": metric("quasileak_pgf1_d8", None, MetricStatus.UNAVAILABLE, EXPORT_PROTOCOL, reason),
                "quasileak_er_pre_policy": metric("quasileak_er_pre_policy", None, MetricStatus.UNAVAILABLE,
                                                  ER_PROTOCOL, reason)}
    result = official.score_official(data, manifest, out, split=split, selection=selection)
    status = MetricStatus.SAMPLED if result["status"] == "sampled" else MetricStatus.DIAGNOSTIC
    recall = pre_policy_evidence_recall(run_dir, rows)
    pgf1 = result["scores_0_100"]["P-GF1"]
    return {
        "quasileak_pgf1_d8": metric("quasileak_pgf1_d8", None if pgf1 is None else pgf1 / 100, status,
                                    EXPORT_PROTOCOL, {**common, "official": result,
                                                      "value_is": "P-GF1 / 100 (scorer officiel inchangé)"}),
        "quasileak_er_pre_policy": metric("quasileak_er_pre_policy", recall["value"], status, ER_PROTOCOL,
                                          {**common, **recall}),
    }


def _tab_official(
    lock: Mapping[str, Any],
    split: str,
    predictions: list[dict[str, Any]],
    documents: Mapping[str, Document],
    capabilities: frozenset[str],
    protocol: str,
    protocol_version: str,
) -> dict[str, Any]:
    """Mesures de l'évaluateur TAB ORIGINAL, depuis le gold source verrouillé (H-8).

    Le gold source est relu depuis le répertoire figé par l'ingestion et son
    empreinte revérifiée : un fichier modifié depuis le run fait échouer le
    score plutôt que de mesurer contre une autre vérité terrain.
    """
    from anonymisation.datasets._local import fingerprint
    from anonymisation.datasets.tab import TabAdapter
    from anonymisation.metrics.tab_official import evaluate_tab, masked_spans

    def unavailable(reason: str) -> dict[str, Any]:
        return MetricValue(
            name="tab_official", value=None, protocol=protocol,
            protocol_version=protocol_version, status=MetricStatus.UNAVAILABLE,
            direction=MetricDirection.MAXIMIZE, details={"reason": reason},
        ).to_dict()

    if "decisions" not in capabilities:
        return unavailable("système sans capacité 'decisions' : aucun masque appliqué à évaluer")
    source = (lock.get("data_version") or {}).get("source") or {}
    files = [Path(p) for p in source.get("files") or ()]
    if not files or any(not p.is_file() for p in files):
        raise ScoreError(
            "TAB : fichiers source du lock d'ingestion introuvables — l'évaluateur officiel "
            "lit le gold original ; réacquérir TAB à l'emplacement verrouillé."
        )
    if fingerprint(files) != source.get("fingerprint"):
        raise ScoreError("TAB : sources modifiées depuis l'ingestion (empreinte divergente)")
    split_file = next((p for p in files if p.name == TabAdapter._SPLIT_FILES.get(split)), None)
    if split_file is None:
        raise ScoreError(f"TAB : aucun fichier source verrouillé pour le split {split!r}")
    records = json.loads(split_file.read_text(encoding="utf-8"))
    masks = {}
    for record in predictions:
        if record.get("status") not in ("ok", "partial"):
            continue
        document = documents[str(record["doc_id"])]
        masks[str(document.meta["source_doc_id"])] = masked_spans(record.get("decisions") or ())
    if not masks:
        return unavailable("aucun document scoré")
    result = evaluate_tab(records, masks)
    measures = result["measures"]
    return MetricValue(
        name="tab_official", value=measures["recall_direct_entities"], protocol=protocol,
        protocol_version=protocol_version, status=MetricStatus.DIAGNOSTIC,
        direction=MetricDirection.MAXIMIZE,
        details={**result, "value_is": "recall_direct_entities (ER_di officiel)"},
    ).to_dict()




def cmd_score(run: str | Path, protocol: str) -> int:
    """Calcule ``scorecard.json`` depuis un run figé, sans modèle.

    Retourne 1 si le taux d'erreur dépasse 5 % (avertissement bloquant C-5),
    tout en écrivant la scorecard pour permettre l'audit ; retourne 0 sinon.
    """
    run_dir = Path(run)
    lock_path = run_dir / LOCK_NAME
    if not lock_path.is_file():
        raise ScoreError(f"Lock de run absent : {lock_path} — exécute d'abord predict")
    # La scorecard est dérivée et recalculable : on retire l'ancienne AVANT
    # toute vérification. Un score qui échoue ensuite ne laisse donc aucune
    # carte d'un état antérieur, relue à tort comme décrivant le run actuel.
    (run_dir / SCORECARD_NAME).unlink(missing_ok=True)
    lock = _read_json(lock_path)
    if lock.get("taxonomy_version") != TAXONOMY_VERSION:
        raise ScoreError(
            "taxonomy_version incompatible : "
            f"run={lock.get('taxonomy_version')!r}, code={TAXONOMY_VERSION!r}. "
            "Reprédiction requise (re-predict) avant score."
        )
    try:
        validate_reproducibility(lock)
        run_info = lock["run"]
        dataset = str(run_info["dataset"])
        split = str(run_info["split"])
    except (KeyError, TypeError, ScorecardError) as exc:
        raise ScoreError(f"Lock de run invalide : {exc}") from exc
    protocol_name, protocol_version, default_status = _protocol_info(dataset, protocol)
    # Un sous-ensemble du pivot reste un échantillon même si predict a
    # parcouru ce pivot entier. Il ne peut hériter du statut OFFICIAL déclaré
    # pour le protocole complet (notamment SPIA/PANORAMA).
    if default_status is MetricStatus.OFFICIAL and (
        lock.get("data_version", {}).get("status") == "sampled"
        or run_info.get("status") == "sampled"
    ):
        default_status = MetricStatus.SAMPLED
    inputs = _verify_inputs(run_dir, lock, dataset, split)
    predictions = _read_predictions(run_dir / PREDICTIONS_NAME)
    expected_doc_ids = {str(p["doc_id"]) for p in predictions if p.get("status") in ("ok", "partial")}
    documents, gold = _load_gold(dataset, split)
    try:
        from anonymisation.cli.evaluate import load_evaluation

        evaluation = load_evaluation(run_dir, lock, inputs, expected_doc_ids)
        # L'identité du système commande quelles métriques sont applicables.
        # On refuse plutôt que de supposer : supposer la détection produirait
        # des zéros sur les boîtes noires, supposer l'inverse ferait
        # disparaître l'axe A des pipelines riches.
        system_block = lock.get("system")
        if not isinstance(system_block, Mapping):
            raise ScoreError(
                "Lock de run sans bloc « system » : run produit avant "
                "l'introduction de l'identité de système. Relancez "
                "« anonv2 predict »."
            )

        scorecard = build_scorecard(
            run_id=run_dir.name,
            dataset=dataset,
            split=split,
            protocol=protocol_name,
            protocol_version=protocol_version,
            predictions=predictions,
            gold_by_doc=gold,
            documents_by_doc=documents,
            reproducibility=lock,
            system=system_block,
            evaluation=evaluation,
            requested_status=default_status,
            span_gold_exhaustive=_gold_exhaustive(dataset),
            attack=_load_frozen(run_dir, inputs["run"]["predictions.jsonl"],
                                ATTACK_LOCK_NAME, ATTACKS_NAME,
                                expected_doc_ids=expected_doc_ids,
                                expected_protocol="ratbench-staab-correctmatch"),
            spia_attack=_load_spia_attack(run_dir, lock, inputs["run"]["predictions.jsonl"],
                                          expected_doc_ids=expected_doc_ids),
            external_diagnostics=(
                {"tab_official": _tab_official(
                    lock, split, predictions, documents,
                    frozenset(str(c) for c in system_block.get("capabilities") or ()),
                    protocol_name, protocol_version,
                )}
                if dataset == "tab"
                else _quasileak_d8(lock, run_dir, split,
                                   frozenset(str(c) for c in system_block.get("capabilities") or ()),
                                   protocol_version)
                if dataset == "quasileak" else None
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ScoreError(f"Scorecard impossible à calculer : {exc}") from exc
    # Empreintes des entrées effectivement scorées : rejouer `score` doit
    # pouvoir prouver qu'il a lu les mêmes octets.
    scorecard["inputs"] = inputs
    write_json(run_dir / SCORECARD_NAME, scorecard)
    accounting = scorecard["accounting"]
    print(
        f"score : {accounting['documents_scored']} document(s) scoré(s), "
        f"taux d'erreur {accounting['error_rate']:.2%} — {run_dir / SCORECARD_NAME}"
    )
    blockers = scorecard.get("publication_blockers") or []
    if blockers:
        print(f"AVERTISSEMENT BLOQUANT : {'; '.join(blockers)}")
        return 1
    return 0

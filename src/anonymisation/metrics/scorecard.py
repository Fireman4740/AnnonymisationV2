"""Scorecards réduites : mesures vérifiables, attaques figées et contrôles d'erreur.

Aucun modèle ni entraînement n'est exécuté. Les évaluations conditionnelles
utilisent des références indépendantes et des prédictions de tâche figées.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from math import ceil
from pathlib import Path
from statistics import median
from typing import Any

from anonymisation.metrics.accounting import RunAccounting, publication_blockers
from anonymisation.metrics.catalog import DIAGNOSTIC_METRICS, PRIMARY_METRICS
from anonymisation.metrics.contracts import MetricDirection, MetricStatus, MetricValue
from anonymisation.metrics.entities import bounds, categories, field_value
from anonymisation.metrics.gating import gate
from anonymisation.metrics.intervals import apply_intervals, scorecard_intervals
from anonymisation.metrics.leakage import aggregate_leak_counts, gold_leak_counts
from anonymisation.metrics.masking import MaskCoverage, decisions_of, document_coverage
from anonymisation.metrics.ner_schemas import SchemaCounts, corpus_counts
from anonymisation.metrics.reidentification import reid_success_metric
from anonymisation.metrics.research import (
    RESEARCH_METRICS,
    event_calibration,
    population_metrics,
    task_utility,
)
from anonymisation.metrics.spia_protection import spia_protection
from anonymisation.metrics.text_quality import human_quality_metrics, local_quality_metrics
from anonymisation.schema.io import sha256_file

#: Catégorie hors périmètre, mappée explicitement par l'adaptateur (action
#: KEEP, SPEC-01) : ni une mention à détecter, ni une fausse détection.
OUT_OF_SCOPE_CATEGORY = "IGNORED"

_NON_EXHAUSTIVE_REASON = (
    "gold non exhaustif (déclaré par evaluation.gold_scope du manifeste) : une "
    "détection absente du gold n'est pas une fausse détection ; seul le rappel est défini"
)


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _detection_scope(
    gold: Sequence[Any], pred: Sequence[Any]
) -> tuple[tuple[Any, ...], tuple[Any, ...], int, int]:
    """Retire le gold hors périmètre et neutralise les prédictions qui le recouvrent.

    Même règle que les mentions « sans besoin de masquage » de TAB : masquer
    une mention IGNORED n'est ni requis ni pénalisé.
    """
    kept_gold, ignored = [], []
    for span in gold:
        labels = categories(span)
        if labels and labels <= {OUT_OF_SCOPE_CATEGORY}:
            span_bounds = bounds(span)
            if span_bounds is not None:
                ignored.append(span_bounds)
            continue
        kept_gold.append(span)
    kept_pred, neutral = [], 0
    for span in pred:
        span_bounds = bounds(span)
        labels = categories(span)
        only_ignored = bool(labels) and labels <= {OUT_OF_SCOPE_CATEGORY}
        overlaps_ignored = span_bounds is not None and any(
            _overlaps(span_bounds, b) for b in ignored
        )
        if only_ignored or overlaps_ignored:
            neutral += 1
            continue
        kept_pred.append(span)
    return tuple(kept_gold), tuple(kept_pred), len(gold) - len(kept_gold), neutral

SCORECARD_SCHEMA_VERSION = "3.1"
_REQUIRED_REPRODUCIBILITY = (
    "data_version",
    "taxonomy_version",
    "code",
    "models",
    "seeds",
    "prompts",
    "policy",
)
_REQUIRED_TOP_LEVEL = (
    "run_id",
    "schema_version",
    "system",
    "dataset",
    "split",
    "primary",
    "diagnostic",
    "by_language",
    "by_domain",
    "by_expression",
    "efficiency",
    "accounting",
)
SPAN_SCHEMA = "partial"
SPAN_MATCH_LABEL = "nervaluate-partial"


class ScorecardError(ValueError):
    """Scorecard incohérente, obsolète ou non vérifiable."""


def _label(value: Any) -> str:
    """Sérialise un enum ou une chaîne en libellé de ventilation."""
    return str(getattr(value, "value", value))


def _status_label(status: Any) -> str:
    """Retourne le statut d'une métrique, enum ou chaîne, en minuscule."""
    return str(getattr(status, "value", status)).lower()


def _has_proxy_risk(record: Mapping[str, Any]) -> bool:
    """Détecte une évaluation de risque proxy dans une prédiction sérialisée."""
    risk = record.get("risk")
    if not isinstance(risk, Mapping):
        return False
    return _status_label(risk.get("status")) == MetricStatus.PROXY.value


def _metric_dict(
    name: str,
    value: float | None,
    *,
    protocol: str,
    protocol_version: str,
    status: MetricStatus,
    direction: MetricDirection,
    unit: str = "ratio",
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if value is None and status not in (MetricStatus.UNAVAILABLE, MetricStatus.FAILED):
        status = MetricStatus.UNAVAILABLE
    return MetricValue(
        name=name,
        value=value,
        protocol=protocol,
        protocol_version=protocol_version,
        status=status,
        direction=direction,
        unit=unit,
        details=dict(details or {}),
    ).to_dict()


def _aggregate_counts(
    records: Iterable[tuple[Sequence[Any], Sequence[Any]]],
) -> dict[str, Any]:
    total, _, _ = corpus_counts(records)
    return _summary(total[SPAN_SCHEMA])


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def _group_metric(
    rows: Sequence[tuple[Sequence[Any], Sequence[Any], str]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[tuple[Sequence[Any], Sequence[Any]]]] = defaultdict(list)
    for gold, pred, group in rows:
        grouped[group].append((gold, pred))
    output: dict[str, dict[str, Any]] = {}
    for group, pairs in sorted(grouped.items()):
        values = _aggregate_counts(pairs)
        values["documents"] = len(pairs)
        output[group] = values
    return output


def _expression_rows(
    rows: Sequence[tuple[Sequence[Any], Sequence[Any], Any]],
) -> list[tuple[Sequence[Any], Sequence[Any], str]]:
    """Ventile gold **et** prédictions par mode d'expression.

    Sans ce filtrage, un document portant deux modes verserait l'intégralité
    de son gold et de ses prédictions dans chacun des deux seaux : les
    effectifs par mode dépasseraient ceux du corpus et chaque mode afficherait
    les erreurs de l'autre.
    """
    output: list[tuple[Sequence[Any], Sequence[Any], str]] = []
    for gold, pred, _ in rows:
        by_mode: dict[str, tuple[list[Any], list[Any]]] = {}
        for span in gold:
            mode = _label(field_value(span, "expression_mode", "unknown"))
            by_mode.setdefault(mode, ([], []))[0].append(span)
        for span in pred:
            mode = _label(field_value(span, "expression_mode", "unknown"))
            by_mode.setdefault(mode, ([], []))[1].append(span)
        for mode in sorted(by_mode):
            gold_spans, pred_spans = by_mode[mode]
            output.append((tuple(gold_spans), tuple(pred_spans), mode))
    return output


def _summary(counts: SchemaCounts) -> dict[str, Any]:
    """Comptes additifs ; un détecteur muet face à du gold a F1=0, pas N/A."""
    tp = counts.credit(SPAN_SCHEMA)
    return {
        "match": SPAN_MATCH_LABEL,
        "tp": tp,
        "fp": counts.actual - tp,
        "fn": counts.possible - tp,
        "gold": counts.possible,
        "pred": counts.actual,
        **counts.scores(SPAN_SCHEMA),
    }


def build_scorecard(
    *,
    run_id: str,
    dataset: str,
    split: str,
    protocol: str,
    protocol_version: str,
    predictions: Sequence[Mapping[str, Any]],
    gold_by_doc: Mapping[str, Sequence[Any]],
    documents_by_doc: Mapping[str, Any],
    reproducibility: Mapping[str, Any],
    system: Mapping[str, Any],
    requested_status: MetricStatus | str = MetricStatus.DIAGNOSTIC,
    attack: tuple[Sequence[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    spia_attack: tuple[Sequence[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    external_diagnostics: Mapping[str, Mapping[str, Any]] | None = None,
    span_gold_available: bool | None = None,
    evaluation: Mapping[str, Any] | None = None,
    span_gold_exhaustive: bool,
) -> dict[str, Any]:
    """Agrège le noyau et les évaluations vérifiées, sans appel de modèle.

    ``span_gold_exhaustive`` est obligatoire : sur un gold partiel par
    construction (attributs ciblés, noms seuls), compter les détections non
    annotées comme fausses rendrait la précision artefactuelle.
    """
    validate_reproducibility(reproducibility)
    rows, scored, runtimes = [], [], []
    out_of_scope_gold = neutral_predictions = 0
    scoped_gold: dict[str, tuple[Any, ...]] = {}
    for record in predictions:
        if str(record.get("status", "error")).lower() not in ("ok", "partial"):
            continue
        doc_id = str(record.get("doc_id", ""))
        document = documents_by_doc.get(doc_id)
        if document is None:
            raise ScorecardError(f"document absent du pivot gold : {doc_id!r}")
        if not isinstance(record.get("anonymized_text"), str):
            raise ScorecardError(f"Prédiction {doc_id!r} sans `anonymized_text` str : run corrompu")
        gold, pred, dropped, neutral = _detection_scope(
            tuple(gold_by_doc.get(doc_id, ())), tuple(record.get("annotations") or ())
        )
        out_of_scope_gold += dropped
        neutral_predictions += neutral
        scoped_gold[doc_id] = gold
        rows.append((gold, pred, document))
        scored.append(record)
        try:
            runtimes.append(float(record.get("runtime_ms", 0.0)))
        except (TypeError, ValueError) as exc:
            raise ScorecardError(f"runtime_ms invalide pour {doc_id!r}") from exc
    accounting = RunAccounting.from_predictions(predictions)
    requested = (
        requested_status
        if isinstance(requested_status, MetricStatus)
        else MetricStatus(str(requested_status).lower())
    )
    status = accounting.status_for(requested)
    if span_gold_available is None:
        span_gold_available = any(
            bounds(span) is not None for spans in gold_by_doc.values() for span in spans
        )
    # L'absence d'annotations n'est pas un gold négatif : les corpus de
    # tâches aval seuls ne permettent pas de compter les fausses détections.
    totals, per_document, unanchored = corpus_counts(
        (gold, pred if span_gold_available else ()) for gold, pred, _ in rows
    )
    overall = _summary(totals[SPAN_SCHEMA])
    masks = [
        document_coverage(
            scoped_gold[str(record["doc_id"])],
            decisions_of(record),
            str(field_value(documents_by_doc[str(record["doc_id"])], "text", "")),
        )
        for record in scored
    ]
    mask_total = sum(masks, MaskCoverage())
    leaks = [
        gold_leak_counts(record["anonymized_text"], scoped_gold[str(record["doc_id"])])
        for record in scored
    ]
    leak_total = aggregate_leak_counts(leaks)
    intervals = scorecard_intervals(
        schema_per_document=per_document if span_gold_available else [],
        mask_coverage=masks,
        leak_counts=leaks,
    )
    capabilities = frozenset(str(c) for c in (system.get("capabilities") or ()))

    def metric(
        name: str, value: float | None, details: Mapping[str, Any], *, minimize: bool = False
    ) -> dict[str, Any]:
        return gate(
            name,
            value,
            capabilities=capabilities,
            protocol=protocol,
            protocol_version=protocol_version,
            status=MetricStatus.DIAGNOSTIC,
            direction=MetricDirection.MINIMIZE if minimize else MetricDirection.MAXIMIZE,
            details=details,
        )

    diagnostic = {
        "span_precision": metric(
            "span_precision", overall["precision"], {"match": SPAN_MATCH_LABEL}
        ),
        "span_recall": metric("span_recall", overall["recall"], {"match": SPAN_MATCH_LABEL}),
        "span_f1": metric("span_f1", overall["f1"], {"match": SPAN_MATCH_LABEL}),
        "span_strict_f1": metric(
            "span_strict_f1",
            totals["strict"].scores("strict")["f1"],
            {"match": "nervaluate-strict"},
        ),
        "mask_coverage": metric(
            "mask_coverage",
            mask_total.char_rate,
            {
                **mask_total.to_dict(),
                "definition": "caractères gold ancrés recouverts par les décisions appliquées (KEEP exclu)",
                **({"reason": "aucune mention gold ancrée"} if not mask_total.gold_chars else {}),
            },
        ),
        "gold_leak_rate": metric(
            "gold_leak_rate",
            leak_total.rate,
            {
                **leak_total.to_dict(),
                "definition_id": "gold-surface-leak-v2",
                "denominator": "testable",
                "limitation": "présence littérale du gold testable ; ne mesure pas l'inférence contextuelle",
                **({"reason": "aucune surface gold testable"} if not leak_total.testable else {}),
            },
            minimize=True,
        ),
        "direct_leak_rate": metric(
            "direct_leak_rate",
            leak_total.direct_rate,
            {
                **leak_total.to_dict(),
                "definition_id": "direct-surface-leak-v1",
                "denominator": "testable_direct",
                "limitation": "présence littérale des identifiants directs gold testables",
                **(
                    {"reason": "aucune surface gold DIRECT testable"}
                    if not leak_total.testable_direct
                    else {}
                ),
            },
            minimize=True,
        ),
        "counts": (
            {
                **(overall if span_gold_exhaustive else {
                    k: v for k, v in overall.items() if k not in ("precision", "f1")
                }),
                "unanchored_gold": unanchored,
                "span_gold_available": True,
                "gold_exhaustive": span_gold_exhaustive,
                "out_of_scope_gold": out_of_scope_gold,
                "neutral_predictions": neutral_predictions,
            }
            if span_gold_available
            else {
                "span_gold_available": False,
                "unanchored_gold": unanchored,
                "predicted_annotations": sum(len(pred) for _, pred, _ in rows),
            }
        ),
    }
    if span_gold_available and not span_gold_exhaustive:
        for name in ("span_precision", "span_f1", "span_strict_f1"):
            diagnostic[name] = metric(name, None, {"reason": _NON_EXHAUSTIVE_REASON})
    if not span_gold_available:
        for name in ("span_precision", "span_recall", "span_f1", "span_strict_f1"):
            diagnostic[name]["details"]["reason"] = (
                "aucun gold de spans déclaré : absence d'annotations, pas des vrais négatifs"
            )
    for name, value in (external_diagnostics or {}).items():
        if name != "tab_official":
            raise ScorecardError(f"diagnostic externe {name!r} retiré ou absent du catalogue actif")
        diagnostic[name] = dict(value)
    if dataset == 'quasileak':
        from anonymisation.metrics.quasileak_masks import group_mask_rate
        from anonymisation.metrics.uncertainty import with_interval

        block = group_mask_rate(scored, gold_by_doc, documents_by_doc)
        masked_metric = gate(
            'quasileak_group_mask_rate', block['value'], capabilities=capabilities,
            protocol=block['protocol'], protocol_version=block['protocol_version'],
            status=MetricStatus(block['status']), direction=MetricDirection.MAXIMIZE,
            details=block['details'])
        diagnostic['quasileak_group_mask_rate'] = with_interval(masked_metric, block['interval'])
    diagnostic = apply_intervals(diagnostic, intervals)
    research = {}
    scored_by_doc = {str(r["doc_id"]): r for r in scored}
    if evaluation and "utility" in evaluation:
        if split not in {"test", "eval"}:
            raise ScorecardError("utilité : split de test indépendant requis")
        frozen_task = evaluation["utility"]
        research.update(task_utility(frozen_task["rows"], frozen_task["metadata"]))
    if evaluation and "local_quality" in evaluation:
        frozen_local = evaluation["local_quality"]
        research.update(local_quality_metrics(frozen_local["rows"], frozen_local["metadata"]))
    if evaluation and "detailed_quality" in evaluation:
        from anonymisation.metrics.detailed_quality import detailed_quality_metrics
        frozen_detailed = evaluation['detailed_quality']
        research.update(detailed_quality_metrics(frozen_detailed['rows'], frozen_detailed['metadata']))
    if evaluation and "text_quality" in evaluation:
        frozen_quality = evaluation["text_quality"]
        research.update(human_quality_metrics(frozen_quality["rows"], frozen_quality["metadata"]))
    if evaluation and "population" in evaluation:
        reference = evaluation["population"]
        research.update(population_metrics(reference["combinations"], gold_by_doc,
                                           scored_by_doc, reference["metadata"], split=split))
    if attack and any((r.get("risk") or {}).get("event_forecast") for r in scored):
        research.update(event_calibration(scored_by_doc, attack, split=split))
    for name, block in research.items():
        # Le protocole de la mesure n'est pas celui du corpus : on le conserve.
        gated = gate(name, block["value"], capabilities=capabilities,
                     protocol=block["protocol"], protocol_version=block["protocol_version"],
                     status=block["status"], direction=block["direction"],
                     unit=block["unit"], details=block["details"])
        diagnostic[name] = gated
    # Une métrique retenue mais inapplicable n'est pas une valeur nulle : sa
    # raison est conservée séparément, sans remplir la scorecard de faux scores.
    not_applicable: dict[str, str] = {}
    for name in sorted(RESEARCH_METRICS - research.keys()):
        not_applicable[name] = (
            "probabilités d'événement explicites et attaque RAT-Bench figée requises"
            if name in {"brier", "ece"} else
            "référence indépendante absente : exécuter l'étape evaluate"
        )
    for name in list(diagnostic):
        value = diagnostic[name]
        if name != "counts" and value["value"] is None and value["status"] == "unavailable":
            not_applicable[name] = value.get("details", {}).get(
                "reason", "dénominateur nul : métrique non définie"
            )
            del diagnostic[name]
    primary: dict[str, Any] = {}
    blockers = publication_blockers(accounting, reproducibility)
    for label, frozen in (("attaque RAT-Bench", attack), ("attaque SPIA", spia_attack)):
        if frozen is not None and not frozen[1].get("publishable"):
            blockers.append(f"{label} : plus de 5 % de documents en erreur (C4)")
    if attack is not None:
        primary["reid_success_rate"] = reid_success_metric(*attack)
    else:
        not_applicable["reid_success_rate"] = "aucune attaque RAT-Bench figée et vérifiée"
    if spia_attack is not None:
        primary["cpr"], primary["ipr"] = spia_protection(*spia_attack)
    else:
        for name in ("cpr", "ipr"):
            not_applicable[name] = "aucune attaque d'inférence SPIA figée et vérifiée"

    if not any(
        value.get("value") is not None
        for name, value in {**diagnostic, **primary}.items()
        if name != "counts"
    ):
        blockers.append(
            "aucune métrique de qualité applicable : gold ou attaque requis par le noyau actif"
        )

    def grouped(getter: Any) -> dict[str, Any]:
        if not span_gold_available:
            return {}
        return _group_metric([(g, p, _label(getter(d))) for g, p, d in rows])

    by_category = {}
    categories = sorted(
        {
            c
            for gold, pred, _ in rows
            for span in (*gold, *pred)
            for c in (field_value(span, "qi_categories", ()) or ())
        }
    )
    for category in categories if span_gold_available else ():
        values = _aggregate_counts(
            [
                (
                    tuple(
                        s for s in gold if category in (field_value(s, "qi_categories", ()) or ())
                    ),
                    tuple(
                        s for s in pred if category in (field_value(s, "qi_categories", ()) or ())
                    ),
                )
                for gold, pred, _ in rows
            ]
        )
        values.update(
            category=category,
            documents=sum(
                any(category in (field_value(s, "qi_categories", ()) or ()) for s in g)
                for g, _, _ in rows
            ),
        )
        by_category[category] = values
    run_info = reproducibility.get("run") or {}
    run_status = (
        "sampled"
        if str(run_info.get("status", "complete")).lower() == "sampled"
        or status is MetricStatus.SAMPLED
        else status.value
    )
    status_reason = None
    if run_status == MetricStatus.OFFICIAL.value and any(_has_proxy_risk(r) for r in predictions):
        run_status = MetricStatus.PROXY.value
        status_reason = "statut OFFICIAL demandé, dégradé : risque PROXY dans les prédictions"
    def recall_only(groups: dict[str, Any]) -> dict[str, Any]:
        # Ventilations soumises à la même règle que le bloc diagnostique.
        if span_gold_exhaustive:
            return groups
        return {name: {k: v for k, v in values.items() if k not in ("precision", "f1")}
                for name, values in groups.items()}

    card = {
        "run_id": run_id,
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "metrics_policy": "reliable-conditional-v2",
        "scoring": {
            "schema_version": SCORECARD_SCHEMA_VERSION,
            "modules_sha256": {
                p.name: sha256_file(p) for p in sorted(Path(__file__).parent.glob("*.py"))
            },
        },
        "system": {
            **{k: v for k, v in system.items() if k != "prompts"},
            "policy": run_info.get("policy"),
            "profile": run_info.get("profile"),
        },
        "dataset": dataset,
        "split": split,
        "protocol": protocol,
        "protocol_version": protocol_version,
        "status": run_status,
        **({"status_reason": status_reason} if status_reason else {}),
        "publishable": not blockers,
        "publication_blockers": blockers,
        "error_rate": accounting.error_rate,
        "accounting": {
            **accounting.to_dict(),
            # Deux systèmes ne se comparent que sur les mêmes documents scorés :
            # des erreurs différentes changent silencieusement le dénominateur.
            "scored_doc_ids_sha256": hashlib.sha256(
                "\n".join(sorted(str(r["doc_id"]) for r in scored)).encode("utf-8")
            ).hexdigest(),
        },
        "primary": primary,
        "diagnostic": diagnostic,
        "not_applicable": not_applicable,
        "by_qi_category": recall_only(by_category),
        "by_language": recall_only(grouped(lambda d: field_value(d, "language", "unknown"))),
        "by_domain": recall_only(grouped(lambda d: field_value(d, "domain", "unknown"))),
        "by_expression": (
            recall_only(_group_metric(_expression_rows(rows))) if span_gold_available else {}
        ),
        "by_difficulty": recall_only(grouped(
            lambda d: (field_value(d, "meta", {}) or {}).get("difficulty", "unknown")
        )),
        "efficiency": {
            "documents_scored": len(scored),
            "latency_p50_ms": median(runtimes) if runtimes else None,
            "latency_p95_ms": _percentile(runtimes, 0.95),
        },
        **{k: reproducibility.get(k) for k in _REQUIRED_REPRODUCIBILITY},
        "reproducibility": dict(reproducibility),
    }
    validate_scorecard(card)
    return card


def validate_reproducibility(lock: Mapping[str, Any]) -> None:
    """Refuse un lock auquel manque ou auquel est invalide un élément requis."""
    missing = [key for key in _REQUIRED_REPRODUCIBILITY if key not in lock]
    if missing:
        raise ScorecardError(
            "Lock de reproductibilité incomplet : éléments manquants : " + ", ".join(missing)
        )
    if lock.get("data_version") is None:
        raise ScorecardError("Lock de reproductibilité sans version des données")
    if not str(lock.get("taxonomy_version", "")).strip():
        raise ScorecardError("Lock de reproductibilité sans taxonomy_version")
    code = lock.get("code")
    if not isinstance(code, Mapping) or not code.get("git_commit"):
        raise ScorecardError("Lock de reproductibilité sans commit git")
    for key in ("models", "seeds", "prompts"):
        if lock.get(key) is None:
            raise ScorecardError(f"Lock de reproductibilité sans élément `{key}`")
    policy = lock.get("policy")
    if not isinstance(policy, Mapping):
        raise ScorecardError("Lock de reproductibilité sans politique")
    # Un système sans politique (boîte noire, passe-plat) est légitime, mais
    # l'absence doit être **déclarée**, jamais déduite du silence : sans
    # `reason`, on ne distingue pas « aucune politique » d'un lock tronqué.
    if not policy.get("id") and not str(policy.get("reason", "")).strip():
        raise ScorecardError(
            "Lock sans politique : un `policy.id` vide exige un "
            "`policy.reason` explicite (ex. « système sans politique »)."
        )


def validate_scorecard(scorecard: Mapping[str, Any]) -> None:
    """Catalogue fermé ; les anciennes cartes doivent être rescorées explicitement."""
    missing = [key for key in _REQUIRED_TOP_LEVEL if key not in scorecard]
    if missing:
        raise ScorecardError("Scorecard incomplète : champs manquants : " + ", ".join(missing))
    if scorecard["schema_version"] != SCORECARD_SCHEMA_VERSION:
        raise ScorecardError("Ancien schéma de scorecard : rescorer avec le noyau 3.1")
    if "error_rate" not in scorecard or "error_rate" not in scorecard["accounting"]:
        raise ScorecardError("Scorecard sans error_rate au premier niveau")
    for section, allowed in (("primary", PRIMARY_METRICS), ("diagnostic", DIAGNOSTIC_METRICS)):
        for name, metric in scorecard[section].items():
            if name == "counts" and section == "diagnostic":
                continue
            if name not in allowed:
                raise ScorecardError(f"Métrique {name!r} retirée ou absente du catalogue actif")
            if _status_label(metric.get("status")) == "proxy":
                raise ScorecardError(f"Métrique PROXY {name!r} interdite dans le noyau actif")
            MetricValue.from_dict(dict(metric))
    if "macro_f1" in scorecard or "downstream_tasks" in scorecard:
        raise ScorecardError("Agrégat de métriques retiré présent dans la scorecard")
    validate_reproducibility(scorecard.get("reproducibility") or scorecard)

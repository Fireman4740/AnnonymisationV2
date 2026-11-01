"""Évaluations conditionnelles, distinctes des anciennes métriques approchées.

F1, Brier et courbe de calibration appellent scikit-learn 1.8.0 directement.
QICR et MALE-k sont des définitions du projet, explicitement versionnées.
Aucun modèle n'est entraîné ou appelé dans ce module.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from anonymisation.metrics.contracts import MetricDirection, MetricStatus, MetricValue
from anonymisation.metrics.detailed_quality import METRICS as DETAILED_QUALITY_METRICS
from anonymisation.metrics.entities import bounds, categories, field_value
from anonymisation.metrics.uncertainty import bootstrap_interval, mean, ratio_of_sums, with_interval

SKLEARN_VERSION = "1.8.0"
RESEARCH_METRICS = DETAILED_QUALITY_METRICS | frozenset({"utility_retention", "task_f1_delta", "qicr", "male_k", "brier", "ece", "human_readability", "human_relevance", "human_faithfulness", "local_readability", "local_relevance", "local_faithfulness"})


def official_library() -> dict[str, str]:
    import sklearn

    if sklearn.__version__ != SKLEARN_VERSION:
        raise ValueError(f"scikit-learn {SKLEARN_VERSION} requis, reçu {sklearn.__version__}")
    return {"package": "scikit-learn", "version": sklearn.__version__,
            "source": f"https://github.com/scikit-learn/scikit-learn/tree/{SKLEARN_VERSION}"}


def _metric(name: str, value: float | None, details: Mapping[str, Any], *,
            protocol: str, minimize: bool = False, unit: str = "ratio") -> dict[str, Any]:
    return MetricValue(
        name=name, value=value, protocol=protocol, protocol_version="1",
        status=MetricStatus.DIAGNOSTIC if value is not None else MetricStatus.UNAVAILABLE,
        direction=MetricDirection.MINIMIZE if minimize else MetricDirection.MAXIMIZE,
        unit=unit, details=dict(details),
    ).to_dict()


def task_utility(rows: Sequence[Mapping[str, Any]], metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Performance d'un même évaluateur figé ; aucune moyenne entre tâches."""
    from sklearn.metrics import accuracy_score, f1_score

    library = official_library()
    if not rows:
        return {}
    labels = list(metadata["labels"])
    if len(labels) < 2 or len(set(labels)) != len(labels):
        raise ValueError("utilité : au moins deux classes distinctes sont requises")
    seen: set[str] = set()
    for row in rows:
        if row["doc_id"] in seen:
            raise ValueError("utilité : document dupliqué")
        seen.add(row["doc_id"])
        if any(row[k] not in labels for k in ("gold", "original", "anonymized", "majority")):
            raise ValueError("utilité : classe absente du vocabulaire verrouillé")

    def scores(sample: Sequence[Mapping[str, Any]]) -> tuple[float, float]:
        y = [r["gold"] for r in sample]
        return tuple(float(f1_score(y, [r[key] for r in sample], labels=labels,
                                    average="macro", zero_division=0))
                     for key in ("original", "anonymized"))

    original, anonymized = scores(rows)
    majority = float(f1_score([r["gold"] for r in rows], [r["majority"] for r in rows],
                             labels=labels, average="macro", zero_division=0))
    informative = original > majority
    details = {
        **metadata, "library": library, "definition_id": "frozen-task-macro-f1-v1",
        "documents": len(rows), "f1_original": original, "f1_anonymized": anonymized,
        "majority_f1": majority, "informative": informative,
        "accuracy_original": float(accuracy_score([r["gold"] for r in rows], [r["original"] for r in rows])),
        "accuracy_anonymized": float(accuracy_score([r["gold"] for r in rows], [r["anonymized"] for r in rows])),
        "limitation": "tâche et évaluateur déclarés ; aucune mesure universelle de conservation du sens",
    }
    output = {}
    for name, value, statistic in (
        ("utility_retention", anonymized / original if informative else None,
         lambda s: scores(s)[1] / scores(s)[0] if scores(s)[0] else None),
        ("task_f1_delta", anonymized - original if informative else None,
         lambda s: scores(s)[1] - scores(s)[0]),
    ):
        payload = {**details}
        if not informative:
            payload["reason"] = "évaluateur non informatif : F1 original ≤ référence majoritaire"
        metric = _metric(name, value, payload, protocol="task-utility-sklearn-frozen")
        output[name] = with_interval(metric, bootstrap_interval(rows, statistic, unit="document")
                                     if informative else None)
    return output


def _fully_detected(annotation: Any, prediction: Mapping[str, Any]) -> bool:
    """Couverture intégrale, catégorie compatible, sans crédit au simple chevauchement."""
    target = bounds(annotation)
    if target is None:
        return False
    left, right = target
    intervals = sorted(
        b for p in prediction.get("annotations", ())
        if (b := bounds(p)) is not None and categories(annotation) & categories(p)
    )
    cursor = left
    for start, end in intervals:
        if start > cursor:
            break
        cursor = max(cursor, end)
        if cursor >= right:
            return True
    return False


def population_metrics(
    combinations: Sequence[Mapping[str, Any]], gold_by_doc: Mapping[str, Sequence[Any]],
    predictions: Mapping[str, Mapping[str, Any]], metadata: Mapping[str, Any], *, split: str,
) -> dict[str, Any]:
    """k gold compté dans une population indépendante, jamais lu dans le moteur évalué.

    Les combinaisons sont rééchantillonnées par cible (tous ses documents et
    combinaisons restent ensemble). Le k prédit exige un identifiant de
    combinaison ET de population explicite, pour éviter un appariement arbitraire.
    """
    gold_index = {}
    for doc_id, spans in gold_by_doc.items():
        for annotation in spans:
            key = str(field_value(annotation, "annotation_id"))
            if key in gold_index:
                raise ValueError(f"annotation gold dupliquée : {key}")
            gold_index[key] = doc_id, annotation
    threshold = metadata.get("k_threshold", 10)
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1:
        raise ValueError("k_threshold doit être un entier positif")
    clusters: dict[str, list[tuple[int, int, float | None]]] = defaultdict(list)
    by_size: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    excluded = unlinked = unanchored = missing_risk = 0
    for combo in combinations:
        docs = set(combo["doc_ids"])
        ids = combo["annotation_ids"]
        if not docs or not docs <= predictions.keys():
            excluded += 1
            continue
        if not ids:
            unlinked += 1
            continue
        if len(set(ids)) != len(ids):
            raise ValueError("combinaison : annotations dupliquées")
        if any(a not in gold_index or gold_index[a][0] not in docs for a in ids):
            raise ValueError("combinaison : annotation absente ou liée à un autre document")
        if any(bounds(gold_index[a][1]) is None for a in ids):
            unanchored += 1
            continue
        at_risk = int(combo["k_true"] <= threshold)
        covered = int(at_risk and all(_fully_detected(gold_index[a][1], predictions[gold_index[a][0]]) for a in ids))
        error = None
        # Un risque documentaire ne décrit pas implicitement chaque combinaison.
        risks = [predictions[d].get("risk") for d in sorted(docs)]
        matching = [r for r in risks if isinstance(r, Mapping)
                    and r.get("combination_id") == combo["combination_id"]
                    and r.get("population_id") == metadata["population_id"]]
        if len(matching) == 1 and split in {"test", "eval"}:
            k_hat = matching[0].get("k_hat")
            if isinstance(k_hat, bool) or not isinstance(k_hat, (float, int)) or not math.isfinite(k_hat) or k_hat < 0:
                raise ValueError("k_hat invalide")
            error = abs(math.log1p(k_hat) - math.log1p(combo["k_true"]))
        else:
            missing_risk += 1
        clusters[str(combo["target_id"])].append((covered, at_risk, error))
        if at_risk:
            size = str(combo["qi_size"])
            by_size[size][0] += covered
            by_size[size][1] += 1
    units = list(clusters.values())

    def qicr(sample: Sequence[Any]) -> float | None:
        return ratio_of_sums(0, 1)([row for cluster in sample for row in cluster])

    def male(sample: Sequence[Any]) -> float | None:
        return mean([r[2] for cluster in sample for r in cluster if r[2] is not None])

    details = {
        **metadata, "definition_id": "project-qicr-full-span-v1",
        "definition": "toutes les mentions liées intégralement détectées, catégories compatibles ; diagnostic de détection",
        "clusters": len(units), "excluded_document_errors": excluded,
        "unlinked": unlinked, "unanchored": unanchored, "missing_matched_risk": missing_risk,
        "at_risk": sum(r[1] for c in units for r in c), "detected": sum(r[0] for c in units for r in c),
        "qicr_at_j": {size: {"detected": d, "total": n, "value": d / n} for size, (d, n) in sorted(by_size.items())},
        "reason": "aucune combinaison à risque liée et évaluable",
        "limitation": "QICR ne mesure ni la suppression effective ni la résistance à l'inférence",
    }
    output = {"qicr": with_interval(_metric("qicr", qicr(units), details, protocol="project-qicr"),
                                    bootstrap_interval(units, qicr, unit="target"))}
    k_details = {**details, "definition_id": "project-male-log1p-v1",
                 "definition": "moyenne |ln(1+k_hat) - ln(1+k_true)| ; exactitude de k, pas calibration d'événements",
                 "pairs": sum(r[2] is not None for c in units for r in c),
                 "reason": "split d'ajustement ou aucune estimation liée explicitement à la même combinaison/population"}
    output["male_k"] = with_interval(_metric("male_k", male(units), k_details, protocol="project-k-estimation", minimize=True, unit="log-error"),
                                     bootstrap_interval(units, male, unit="target"))
    return output


def event_calibration(
    predictions: Mapping[str, Mapping[str, Any]], attack: tuple[Sequence[Mapping[str, Any]], Mapping[str, Any]], *, split: str,
) -> dict[str, Any]:
    """Probabilité explicite AVANT attaque vs succès binaire RAT-Bench après anonymisation.

    Ne transforme jamais le k de l'original ou CorrectMatch en probabilité.
    Le contrat doit déclarer le même attaquant, événement et protocole.
    """
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import brier_score_loss

    library = official_library()
    rows, lock = attack
    expected = {"protocol": lock["protocol"], "protocol_version": str(lock["protocol_version"]),
                "attacker": lock["attacker"], "event": "ratbench_reidentified",
                "text_stage": "anonymized"}
    paired = []
    for row in rows:
        forecast = (predictions.get(str(row["doc_id"]), {}).get("risk") or {}).get("event_forecast")
        if not forecast or row.get("status") != "ok":
            continue
        if forecast.get("contract") != expected:
            raise ValueError("calibration : contrat d'événement/attaquant divergent")
        p = forecast.get("probability")
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("calibration : probabilité hors [0,1]")
        if not isinstance(row["reidentified"], bool):
            raise ValueError("calibration : cible binaire requise")
        paired.append((float(p), int(row["reidentified"])))
    complete = len(paired) == sum(r.get("status") == "ok" for r in rows)
    eligible = split in {"test", "eval"} and lock.get("publishable") and bool(paired) and complete
    details = {"library": library, "event_contract": expected,
               "definition_id": "observed-ratbench-event-v1", "documents": len(paired),
               "documents_without_forecast_or_outcome": len(rows) - len(paired),
               "evaluation_context": {"doc_ids": sorted(str(r["doc_id"]) for r in rows if r.get("status") == "ok")},
               "reason": "test indépendant, attaque exploitable et probabilités d'événement explicites requis",
               "limitation": "Brier mesure la qualité probabiliste globale ; ECE dépend des bacs et de l'échantillon"}

    def bs(sample: Sequence[Any]) -> float:
        return float(brier_score_loss([r[1] for r in sample], [r[0] for r in sample], pos_label=1, scale_by_half=True))

    # Bacs uniformes : pas de séparation des probabilités égales selon le gold.
    def curve(sample: Sequence[Any], n_bins: int = 10) -> dict[str, Any]:
        import numpy as np

        prob = np.asarray([r[0] for r in sample])
        truth = np.asarray([r[1] for r in sample])
        observed, predicted = calibration_curve(truth, prob, pos_label=1, n_bins=n_bins, strategy="uniform")
        bins = np.searchsorted(np.linspace(0, 1, n_bins + 1)[1:-1], prob)
        counts = np.bincount(bins, minlength=n_bins)
        counts = counts[counts > 0]
        return {"n_bins": n_bins, "strategy": "uniform", "counts": counts.tolist(),
                "mean_probability": predicted.tolist(), "observed_frequency": observed.tolist(),
                "ece": float(np.sum(counts * np.abs(observed - predicted)) / len(sample))}

    if eligible:
        details.update(reliability=curve(paired), ece_by_bins={str(b): curve(paired, b)["ece"] for b in (5, 10, 15, 20)})
    return {
        "brier": with_interval(_metric("brier", bs(paired) if eligible else None, details,
                                       protocol="sklearn-observed-event", minimize=True),
                               bootstrap_interval(paired, bs, unit="document") if eligible else None),
        "ece": with_interval(_metric("ece", curve(paired)["ece"] if eligible else None, details,
                                     protocol="sklearn-observed-event", minimize=True),
                             bootstrap_interval(paired, lambda s: curve(s)["ece"], unit="document") if eligible else None),
    }

"""Intervalles de confiance des métriques de la scorecard (EPIC-H H-7).

Séparé de ``scorecard.py`` pour garder ce dernier centré sur l'agrégation :
ce module transforme les mêmes entrées (lignes gold/prédiction par document,
résultats par sujet, cibles TRIR) en unités indépendantes, puis délègue le
rééchantillonnage à :mod:`anonymisation.metrics.uncertainty`.

Chaque intervalle est calculé sur **la même unité** que la valeur ponctuelle
qu'il accompagne ; un écart entre les deux serait un bug, et les tests le
vérifient (la valeur ponctuelle doit tomber dans son intervalle).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from anonymisation.metrics.entities import entity_protection_counts, same_identifier_type
from anonymisation.metrics.leakage import LeakCounts
from anonymisation.metrics.protection import SubjectOutcome
from anonymisation.metrics.spans import span_metrics
from anonymisation.metrics.tria import TRIRResult
from anonymisation.metrics.uncertainty import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    bootstrap_interval,
    complement_ratio_of_sums,
    f1_of_counts,
    mean,
    ratio_of_sums,
    with_interval,
)
from anonymisation.schema.taxonomy import IdentifierType

Rows = Sequence[tuple[Sequence[Any], Sequence[Any], Any]]


def _entity_counts_per_document(
    rows: Rows, identifier_type: IdentifierType
) -> list[tuple[int, int]]:
    """``(entités protégées, entités gold)`` par document ayant du gold de ce type."""
    output: list[tuple[int, int]] = []
    for gold, pred, _ in rows:
        gold_spans = [span for span in gold if same_identifier_type(span, identifier_type)]
        if not gold_spans:
            continue
        pred_spans = [span for span in pred if same_identifier_type(span, identifier_type)]
        output.append(
            entity_protection_counts(gold_spans, pred_spans, identifier_type=identifier_type)
        )
    return output


def scorecard_intervals(
    *,
    rows: Rows,
    match: str,
    token_scores: Sequence[float],
    rouge_scores: Sequence[float],
    leak_counts: Sequence[LeakCounts],
    outcomes: Sequence[SubjectOutcome],
    trir_result: TRIRResult | None,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, dict[str, Any] | None]:
    """Intervalle à 95 % de chaque métrique, indexé par son nom de scorecard."""

    def interval(units: Sequence[Any], statistic: Any, unit: str) -> dict[str, Any] | None:
        return bootstrap_interval(
            units, statistic, unit=unit, replicates=replicates, seed=seed
        )

    spans = [
        (float(r["tp"] or 0), float(r["fp"] or 0), float(r["fn"] or 0))
        for r in (span_metrics(gold, pred, match=match) for gold, pred, _ in rows)
    ]
    direct = _entity_counts_per_document(rows, IdentifierType.DIRECT)
    quasi = _entity_counts_per_document(rows, IdentifierType.QUASI)
    gold_leaks = [
        (float(c.leaked), float(c.testable))
        for c in leak_counts
        if c.testable
    ]
    direct_leaks = [
        (float(c.leaked_direct), float(c.testable_direct))
        for c in leak_counts
        if c.testable_direct
    ]
    subjects = [(float(o.pii_still_inferable), float(o.pii_total)) for o in outcomes]
    ipr_units = [
        1.0 - o.pii_still_inferable / o.pii_total for o in outcomes if o.pii_total
    ]

    result: dict[str, dict[str, Any] | None] = {
        # Précision = tp / (tp + fp) : tuple (tp, tp + fp).
        "span_precision": interval(
            [(tp, tp + fp) for tp, fp, _ in spans], ratio_of_sums(0, 1), "document"
        ),
        "span_recall": interval(
            [(tp, tp + fn) for tp, _, fn in spans], ratio_of_sums(0, 1), "document"
        ),
        "span_f1": interval(spans, f1_of_counts, "document"),
        "weighted_token_precision": interval(list(token_scores), mean, "document"),
        "ER_di": interval(direct, ratio_of_sums(0, 1), "document"),
        "ER_qi": interval(quasi, ratio_of_sums(0, 1), "document"),
        "rouge_l": interval(list(rouge_scores), mean, "document"),
        "gold_leak_rate": interval(gold_leaks, ratio_of_sums(0, 1), "document"),
        "direct_leak_rate": interval(direct_leaks, ratio_of_sums(0, 1), "document"),
        "cpr": interval(subjects, complement_ratio_of_sums(0, 1), "subject"),
        "ipr": interval(ipr_units, mean, "subject"),
    }
    result["entity_recall_direct"] = result["ER_di"]
    result["entity_recall_quasi"] = result["ER_qi"]

    if trir_result is not None and trir_result.outcomes:
        # Grappe = sujet : les cibles d'un même sujet partagent sa connaissance
        # auxiliaire et ne sont pas indépendantes.
        per_subject: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for outcome in trir_result.outcomes:
            per_subject[outcome.subject_id][0] += outcome.top1
            per_subject[outcome.subject_id][1] += 1.0
        result["trir"] = interval(
            [tuple(per_subject[s]) for s in sorted(per_subject)], ratio_of_sums(0, 1), "subject"
        )
    return result


def apply_intervals(
    block: Mapping[str, Any], intervals: Mapping[str, dict[str, Any] | None]
) -> dict[str, Any]:
    """Copie de ``block`` où chaque métrique connue reçoit son ``details.ci95``."""
    return {
        name: (
            with_interval(metric, intervals[name])
            if name in intervals and isinstance(metric, dict)
            else metric
        )
        for name, metric in block.items()
    }


__all__ = ["apply_intervals", "scorecard_intervals"]

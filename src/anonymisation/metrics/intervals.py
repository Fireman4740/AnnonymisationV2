"""Intervalles par document du noyau actif : spans, masques et fuite littérale."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from anonymisation.metrics.leakage import LeakCounts
from anonymisation.metrics.masking import MaskCoverage
from anonymisation.metrics.ner_schemas import SchemaCounts
from anonymisation.metrics.uncertainty import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    bootstrap_interval,
    f1_of_counts,
    ratio_of_sums,
    with_interval,
)


def scorecard_intervals(
    *,
    schema_per_document: Sequence[Mapping[str, SchemaCounts]],
    mask_coverage: Sequence[MaskCoverage],
    leak_counts: Sequence[LeakCounts],
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, dict[str, Any] | None]:
    def interval(units: Sequence[Any], statistic: Any) -> dict[str, Any] | None:
        return bootstrap_interval(
            units, statistic, unit="document", replicates=replicates, seed=seed
        )

    def counts(schema: str) -> list[tuple[float, float, float]]:
        return [
            (row[schema].credit(schema), float(row[schema].actual), float(row[schema].possible))
            for row in schema_per_document
        ]

    partial, strict = counts("partial"), counts("strict")
    return {
        "span_precision": interval([(c, a) for c, a, _ in partial], ratio_of_sums(0, 1)),
        "span_recall": interval([(c, p) for c, _, p in partial], ratio_of_sums(0, 1)),
        "span_f1": interval([(c, a - c, p - c) for c, a, p in partial], f1_of_counts),
        "span_strict_f1": interval([(c, a - c, p - c) for c, a, p in strict], f1_of_counts),
        "mask_coverage": interval(
            [(float(m.covered_chars), float(m.gold_chars)) for m in mask_coverage if m.gold_chars],
            ratio_of_sums(0, 1),
        ),
        "gold_leak_rate": interval(
            [(float(c.leaked), float(c.testable)) for c in leak_counts if c.testable],
            ratio_of_sums(0, 1),
        ),
        "direct_leak_rate": interval(
            [
                (float(c.leaked_direct), float(c.testable_direct))
                for c in leak_counts
                if c.testable_direct
            ],
            ratio_of_sums(0, 1),
        ),
    }


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

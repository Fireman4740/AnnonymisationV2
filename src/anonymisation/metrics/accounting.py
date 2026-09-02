"""Comptabilité des erreurs d'exécution (SPEC-10 §2/§4, ticket C-5).

Un document non ``ok`` n'est jamais transformé en prédiction vide pour les
métriques : il reste dans la comptabilité d'exécution et sort du dénominateur
scoré. Les erreurs sont regroupées par étape et par type pour rendre une
campagne réparable.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from anonymisation.metrics.contracts import MetricStatus

_ERROR_TYPE_MARKERS = (
    ("fuite", "validation_leak"),
    ("placeholder", "malformed_placeholder"),
    ("motif", "residual_pattern"),
    ("budget", "budget"),
    ("timeout", "timeout"),
)


def _value(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _error_list(record: Any) -> tuple[str, ...]:
    errors = _value(record, "error", None)
    if errors is None:
        errors = _value(record, "errors", ())
    if isinstance(errors, str):
        return (errors,)
    if errors is None:
        return ()
    return tuple(str(error) for error in errors if str(error).strip())


def _stage_and_type(error: str) -> tuple[str, str]:
    prefix, separator, detail = error.partition(":")
    stage = prefix.strip().upper() if separator and prefix.strip() else "UNKNOWN"
    lowered = detail.lower() if separator else error.lower()
    if stage == "BUDGET":
        return stage, "budget"
    for marker, error_type in _ERROR_TYPE_MARKERS:
        if marker in lowered:
            return stage, error_type
    if stage != "UNKNOWN":
        return stage, "stage_error"
    return stage, "unknown"


def _trace_errors(record: Any) -> tuple[tuple[str, str], ...]:
    traces = _value(record, "traces", ()) or ()
    result: list[tuple[str, str]] = []
    for trace in traces:
        if isinstance(trace, Mapping):
            status = str(trace.get("status", ""))
            stage = trace.get("stage", "UNKNOWN")
            detail = trace.get("error")
        else:
            status = str(getattr(trace, "status", ""))
            stage = getattr(trace, "stage", "UNKNOWN")
            detail = getattr(trace, "error", None)
        if status.lower() != "error":
            continue
        result.append((str(stage).upper(), str(detail or "stage_error")))
    return tuple(result)


@dataclass(frozen=True)
class RunAccounting:
    """Dénominateurs et ventilation des documents exclus du scoring."""

    documents_total: int
    documents_scored: int
    documents_errored: int
    error_rate: float
    errors_by_stage: dict[str, int]
    errors_by_type: dict[str, int]

    def __post_init__(self) -> None:
        if self.documents_total < 0:
            raise ValueError("documents_total doit être positif ou nul")
        if self.documents_scored < 0 or self.documents_errored < 0:
            raise ValueError("les compteurs de documents ne peuvent pas être négatifs")
        if self.documents_scored + self.documents_errored != self.documents_total:
            raise ValueError("documents_scored + documents_errored doit égaler documents_total")
        expected = self.documents_errored / self.documents_total if self.documents_total else 0.0
        if abs(self.error_rate - expected) > 1e-12:
            raise ValueError("error_rate ne correspond pas aux compteurs de documents")

    @classmethod
    def from_predictions(cls, predictions: Iterable[Any]) -> RunAccounting:
        """Construit la comptabilité depuis des lignes JSON ou des résultats.

        ``status != "ok"`` est la règle d'exclusion normative. Une ligne non-ok
        sans champ d'erreur reçoit une catégorie ``UNKNOWN`` plutôt qu'une
        disparition silencieuse.
        """
        total = scored = errored = 0
        by_stage: Counter[str] = Counter()
        by_type: Counter[str] = Counter()
        for record in predictions:
            total += 1
            status = str(_value(record, "status", "error")).lower()
            if status == "ok":
                scored += 1
                continue
            errored += 1
            errors = _error_list(record)
            parsed = [_stage_and_type(error) for error in errors]
            if not parsed:
                # Repli sur les traces d'étape : un document peut échouer sans
                # message agrégé dans ``error``. Sans ce repli, l'étape fautive
                # serait perdue et le run deviendrait non réparable (C-5).
                parsed = [
                    (stage, _stage_and_type(f"{stage}: {detail}")[1])
                    for stage, detail in _trace_errors(record)
                ]
            if not parsed:
                parsed = [(status.upper(), status or "unknown")]
            # Une erreur document compte une seule fois par groupe, même si
            # l'étape a ajouté plusieurs messages identiques.
            for stage in {stage for stage, _ in parsed}:
                by_stage[stage] += 1
            for error_type in {error_type for _, error_type in parsed}:
                by_type[error_type] += 1
        rate = errored / total if total else 0.0
        return cls(
            documents_total=total,
            documents_scored=scored,
            documents_errored=errored,
            error_rate=rate,
            errors_by_stage=dict(sorted(by_stage.items())),
            errors_by_type=dict(sorted(by_type.items())),
        )

    @classmethod
    def from_records(cls, predictions: Iterable[Any]) -> RunAccounting:
        """Alias explicite pour les appelants qui parlent de records JSON."""
        return cls.from_predictions(predictions)

    @property
    def publishable(self) -> bool:
        """Le seuil C-5.5 autorise-t-il la publication en l'état ?"""
        return self.error_rate <= 0.05

    @property
    def warning(self) -> str | None:
        """Avertissement bloquant au-delà de 5 % d'erreurs."""
        if self.error_rate > 0.05:
            return (
                f"Run non publiable : taux d'erreur {self.error_rate:.2%} "
                "supérieur au seuil de 5 % (C-5)."
            )
        return None

    def status_for(self, requested: MetricStatus | str) -> MetricStatus:
        """Dégrade ``OFFICIAL`` en ``SAMPLED`` dès qu'une erreur existe."""
        status = (
            requested
            if isinstance(requested, MetricStatus)
            else MetricStatus(str(requested).lower())
        )
        if self.error_rate > 0 and status is MetricStatus.OFFICIAL:
            return MetricStatus.SAMPLED
        return status

    def to_dict(self) -> dict[str, Any]:
        """Forme JSON stable incluse au premier niveau de la scorecard."""
        return {
            "documents_total": self.documents_total,
            "documents_scored": self.documents_scored,
            "documents_errored": self.documents_errored,
            "error_rate": self.error_rate,
            "errors_by_stage": dict(self.errors_by_stage),
            "errors_by_type": dict(self.errors_by_type),
            "publishable": self.publishable,
            "warning": self.warning,
        }

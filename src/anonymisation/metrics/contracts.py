"""Contrats typés des métriques (SPEC-07 §9, EPIC-D D-2).

Une valeur métrique transporte toujours son protocole, sa version, sa direction
et son statut. Cette information n'est pas décorative : comparer un proxy ou
une métrique diagnostique à un chiffre officiel est interdit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Any


class MetricStatus(str, Enum):
    """Statut de publication d'une métrique.

    ``str`` est mélangé à ``Enum`` (plutôt que ``enum.StrEnum``) pour rester
    importable sur Python 3.10, la version documentée comme compatible.
    """

    OFFICIAL = "official"
    SAMPLED = "sampled"
    DIAGNOSTIC = "diagnostic"
    PROXY = "proxy"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class MetricDirection(str, Enum):
    """Sens d'amélioration d'une métrique."""

    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"
    INFORMATIONAL = "informational"


class MetricContractError(ValueError):
    """Valeur métrique absente ou incohérente."""


class MetricComparisonError(ValueError):
    """Deux métriques ne sont pas comparables."""


@dataclass(frozen=True)
class MetricValue:
    """Une métrique accompagnée de son contexte de mesure.

    ``value=None`` est réservé aux métriques non calculables : utiliser une
    valeur nulle pour une métrique indisponible confondrait absence de mesure et
    résultat nul.
    """

    name: str
    value: float | None
    protocol: str
    protocol_version: str
    status: MetricStatus
    direction: MetricDirection
    unit: str = "ratio"
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            status = (
                self.status
                if isinstance(self.status, MetricStatus)
                else MetricStatus(str(self.status).lower())
            )
            direction = (
                self.direction
                if isinstance(self.direction, MetricDirection)
                else MetricDirection(str(self.direction).lower())
            )
        except ValueError as exc:
            raise MetricContractError(f"status ou direction invalide : {exc}") from exc
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "direction", direction)
        if not self.name.strip():
            raise MetricContractError("name ne peut pas être vide")
        if not self.protocol.strip():
            raise MetricContractError("protocol est obligatoire")
        if not self.protocol_version.strip():
            raise MetricContractError("protocol_version est obligatoire")
        if not self.unit.strip():
            raise MetricContractError("unit ne peut pas être vide")
        if self.value is None:
            if status not in (MetricStatus.UNAVAILABLE, MetricStatus.FAILED):
                raise MetricContractError(
                    "value=None est autorisé uniquement avec status=UNAVAILABLE ou FAILED"
                )
        elif isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise MetricContractError(
                f"value doit être un nombre fini ou None (reçu : {type(self.value).__name__})"
            )
        elif not isfinite(float(self.value)):
            raise MetricContractError("value doit être un nombre fini ou None")

    def to_dict(self) -> dict[str, Any]:
        """Sérialise sans perdre le contrat de statut et de protocole."""
        return {
            "name": self.name,
            "value": self.value,
            "protocol": self.protocol,
            "protocol_version": self.protocol_version,
            "status": self.status.value,
            "direction": self.direction.value,
            "unit": self.unit,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MetricValue:
        """Reconstruit une valeur depuis une scorecard JSON."""
        try:
            return cls(
                name=str(payload["name"]),
                value=payload.get("value"),
                protocol=str(payload["protocol"]),
                protocol_version=str(payload["protocol_version"]),
                status=MetricStatus(payload["status"]),
                direction=MetricDirection(payload["direction"]),
                unit=str(payload.get("unit", "ratio")),
                details=dict(payload.get("details") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MetricContractError(f"MetricValue invalide : {exc}") from exc


def assert_comparable(a: MetricValue, b: MetricValue) -> None:
    """Refuse une comparaison inter-protocole ou inter-statut.

    Les statuts ``DIAGNOSTIC`` et ``PROXY`` ne sont jamais comparables à un
    chiffre publié, y compris entre eux : ils ne portent pas une garantie de
    comparabilité externe. Les métriques doivent également être de même nom,
    direction, protocole, version et statut.
    """
    if a.name != b.name:
        raise MetricComparisonError(f"métriques différentes : {a.name!r} vs {b.name!r}")
    if a.protocol != b.protocol or a.protocol_version != b.protocol_version:
        raise MetricComparisonError(
            "protocoles incompatibles : "
            f"{a.protocol!r}/{a.protocol_version!r} vs "
            f"{b.protocol!r}/{b.protocol_version!r}"
        )
    if (
        a.status in (MetricStatus.DIAGNOSTIC, MetricStatus.PROXY)
        or b.status in (MetricStatus.DIAGNOSTIC, MetricStatus.PROXY)
    ):
        bad = (
            a.status.value.upper()
            if a.status in (MetricStatus.DIAGNOSTIC, MetricStatus.PROXY)
            else b.status.value.upper()
        )
        raise MetricComparisonError(
            f"une métrique {bad} n'est pas comparable à un chiffre publié"
        )
    if a.status != b.status:
        raise MetricComparisonError(
            f"statuts incompatibles : {a.status.value!r} vs {b.status.value!r}"
        )
    if a.status in (MetricStatus.UNAVAILABLE, MetricStatus.FAILED):
        raise MetricComparisonError(f"métrique non comparable : status={a.status.value!r}")
    if a.direction != b.direction:
        raise MetricComparisonError(
            f"directions incompatibles : {a.direction.value!r} vs {b.direction.value!r}"
        )

"""Portillon de capacités : dégrader en ``UNAVAILABLE``, jamais en ``0.0``.

Le problème que ce module résout : un ``PipelineResult`` sans annotations est
**ambigu**. Boîte noire qui ne prétend pas détecter, ou pipeline riche qui n'a
rien trouvé ? Sans distinction, ``span_recall`` vaudrait ``0.0`` pour une
boîte noire parfaite — un zéro qui la ferait passer pour un détecteur
catastrophique et rendrait toute comparaison inter-systèmes absurde.

La règle, normative : une métrique dont la capacité requise n'est pas déclarée
sort en ``UNAVAILABLE``, avec un ``details.reason`` nommant la capacité
manquante. Le scorer ne devine jamais à partir du contenu ; il lit les
capacités déclarées dans le lock.

Ce module n'importe que ``anonymisation.capabilities`` (qui n'importe rien) et
``anonymisation.metrics.contracts`` : le scoring doit rester hors ligne.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from anonymisation.capabilities import CAP_RISK, CAP_SPANS
from anonymisation.metrics.contracts import MetricDirection, MetricStatus, MetricValue

#: Capacités requises par métrique. Une métrique publiée absente de cette
#: table est un défaut : le test ``test_gate_table_covers_published_metrics``
#: échoue, ce qui force à décider explicitement de son portillon.
METRIC_CAPABILITY_GATE: Final[Mapping[str, frozenset[str]]] = {
    # --- axe A : suppose que le système localise des spans ----------------- #
    "span_precision": frozenset({CAP_SPANS}),
    "span_recall": frozenset({CAP_SPANS}),
    "span_f1": frozenset({CAP_SPANS}),
    "span_f2": frozenset({CAP_SPANS}),
    "macro_f1": frozenset({CAP_SPANS}),
    "weighted_token_precision": frozenset({CAP_SPANS}),
    "ER_di": frozenset({CAP_SPANS}),
    "ER_qi": frozenset({CAP_SPANS}),
    "entity_recall_direct": frozenset({CAP_SPANS}),
    "entity_recall_quasi": frozenset({CAP_SPANS}),
    # --- axes B/C/D : mesurés sur le TEXTE, donc universels ---------------- #
    # C'est le résultat central de cette architecture : une boîte noire reste
    # pleinement évaluable sur la protection et l'utilité.
    "cpr": frozenset(),
    "ipr": frozenset(),
    "trir": frozenset(),
    "rouge_l": frozenset(),
    "mean_utility": frozenset(),
    "gold_leak_rate": frozenset(),
    "reid_success_rate": frozenset(),
    "utility_retention": frozenset(),
    # --- calibration : suppose une estimation de risque -------------------- #
    "male_k": frozenset({CAP_RISK}),
    "ece": frozenset({CAP_RISK}),
    "brier": frozenset({CAP_RISK}),
}


class GateError(ValueError):
    """Métrique publiée sans règle de portillon déclarée."""


def missing_capabilities(name: str, capabilities: frozenset[str]) -> tuple[str, ...]:
    """Capacités manquantes pour publier ``name``, triées."""
    try:
        required = METRIC_CAPABILITY_GATE[name]
    except KeyError as exc:  # pragma: no cover - défendu par un test dédié
        raise GateError(
            f"Métrique {name!r} sans règle de portillon. Ajoutez-la à "
            f"METRIC_CAPABILITY_GATE en décidant explicitement des capacités "
            f"qu'elle exige."
        ) from exc
    return tuple(sorted(required - capabilities))


def gate(
    name: str,
    value: float | None,
    *,
    capabilities: frozenset[str],
    protocol: str,
    protocol_version: str,
    status: MetricStatus,
    direction: MetricDirection,
    unit: str = "ratio",
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Renvoie la métrique, ou ``UNAVAILABLE`` nommant la capacité manquante."""
    payload = dict(details or {})
    absent = missing_capabilities(name, capabilities)
    if absent:
        payload["reason"] = (
            f"système sans capacité {absent[0]!r} — {name} n'est pas défini "
            f"pour ce système ; publier 0.0 serait trompeur"
        )
        payload["missing_capabilities"] = list(absent)
        value = None
        status = MetricStatus.UNAVAILABLE
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
        details=payload,
    ).to_dict()


def capabilities_from_lock(lock: Mapping[str, Any]) -> frozenset[str]:
    """Capacités déclarées par le système d'un run.

    Un lock sans bloc ``system`` vient d'avant l'introduction de l'identité de
    système : on refuse plutôt que de supposer, car supposer ``CAP_SPANS``
    produirait des zéros sur les boîtes noires et supposer l'inverse ferait
    disparaître l'axe A des pipelines riches.
    """
    system = lock.get("system")
    if not isinstance(system, Mapping):
        raise GateError(
            "Lock de run sans bloc « system » : run produit avant "
            "l'introduction de l'identité de système. Relancez "
            "« anonv2 predict »."
        )
    declared = system.get("capabilities")
    if not isinstance(declared, (list, tuple)):
        raise GateError(
            "Lock de run : « system.capabilities » absent ou mal formé — "
            "impossible de savoir quelles métriques sont applicables."
        )
    return frozenset(str(item) for item in declared)

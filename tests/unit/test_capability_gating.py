"""Portillon de capacités : ``UNAVAILABLE``, jamais ``0.0``.

C'est la règle qui rend une boîte noire et un pipeline riche comparables sur
ce qui leur est commun, sans prétendre mesurer ce qui n'existe pas.
"""

from __future__ import annotations

from typing import Any

import pytest

from anonymisation.capabilities import CAP_SPANS
from anonymisation.metrics.contracts import MetricDirection, MetricStatus
from anonymisation.metrics.gating import (
    METRIC_CAPABILITY_GATE,
    GateError,
    capabilities_from_lock,
    gate,
    missing_capabilities,
)

_RICH = frozenset({"spans", "decisions", "traces", "risk", "policy", "gold_aware"})
_BLACKBOX: frozenset[str] = frozenset()


def _gate(name: str, value: float | None, capabilities: frozenset[str]) -> dict[str, Any]:
    return gate(
        name,
        value,
        capabilities=capabilities,
        protocol="test",
        protocol_version="1",
        status=MetricStatus.DIAGNOSTIC,
        direction=MetricDirection.MAXIMIZE,
    )


class TestDegradation:
    def test_blackbox_span_metric_is_unavailable_never_zero(self) -> None:
        """Le cœur de la règle : un zéro ferait passer une boîte noire parfaite
        pour un détecteur catastrophique."""
        metric = _gate("span_f1", 0.87, _BLACKBOX)
        assert metric["value"] is None
        assert metric["value"] != 0.0
        assert metric["status"] == MetricStatus.UNAVAILABLE.value
        assert "spans" in metric["details"]["missing_capabilities"]
        assert "spans" in metric["details"]["reason"]

    def test_rich_system_publishes_span_metrics(self) -> None:
        metric = _gate("span_f1", 0.87, _RICH)
        assert metric["value"] == pytest.approx(0.87)
        assert metric["status"] == MetricStatus.DIAGNOSTIC.value

    @pytest.mark.parametrize("name", ["cpr", "ipr", "trir", "rouge_l", "gold_leak_rate"])
    def test_text_level_metrics_need_no_capability(self, name: str) -> None:
        """Axes B/C/D : mesurés sur le texte, donc applicables à tout système.

        C'est ce qui rend une boîte noire pleinement évaluable sur la
        protection et l'utilité.
        """
        assert missing_capabilities(name, _BLACKBOX) == ()
        assert _gate(name, 0.5, _BLACKBOX)["value"] == pytest.approx(0.5)

    def test_a_real_none_stays_unavailable(self) -> None:
        """Une valeur réellement indéfinie n'est pas maquillée en zéro."""
        metric = _gate("cpr", None, _BLACKBOX)
        assert metric["value"] is None
        assert metric["status"] == MetricStatus.UNAVAILABLE.value


class TestGateTable:
    def test_unknown_metric_is_refused(self) -> None:
        """Publier une métrique sans règle de portillon est un défaut."""
        with pytest.raises(GateError, match="sans règle de portillon"):
            missing_capabilities("metrique_inventee", _RICH)

    def test_axis_a_metrics_all_require_spans(self) -> None:
        for name in ("span_f1", "macro_f1", "ER_di", "ER_qi", "weighted_token_precision"):
            assert METRIC_CAPABILITY_GATE[name] == frozenset({CAP_SPANS}), name


class TestCapabilitiesFromLock:
    def test_lock_without_system_is_refused(self) -> None:
        """On refuse plutôt que de supposer : supposer la détection produirait
        des zéros sur les boîtes noires, supposer l'inverse ferait disparaître
        l'axe A des pipelines riches."""
        with pytest.raises(GateError, match="sans bloc"):
            capabilities_from_lock({"run": {}})

    def test_malformed_capabilities_are_refused(self) -> None:
        with pytest.raises(GateError, match="capabilities"):
            capabilities_from_lock({"system": {"system_id": "x"}})

    def test_capabilities_are_read_from_the_lock(self) -> None:
        caps = capabilities_from_lock({"system": {"capabilities": ["spans", "risk"]}})
        assert caps == frozenset({"spans", "risk"})

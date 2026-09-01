"""Tests du moteur de politique (lot L5).

Couvre : chargement/validation de configs/policy/policies.yaml, et le
comportement du moteur sur les cinq points de fonctionnement P0..P4
(SPEC-06 §9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from anonymisation.policy.engine import NaiveRiskEstimator, PolicyEngine
from anonymisation.policy.models import PolicyConfigError, load_policy_set
from anonymisation.transform.decisions import Action

POLICIES_PATH = Path(__file__).resolve().parents[2] / "configs" / "policy" / "policies.yaml"


# --------------------------------------------------------------------------- #
# Fixture : annotation minimale conforme à AnnotationLike
# --------------------------------------------------------------------------- #
@dataclass
class FakeAnnotation:
    annotation_id: str
    start: int | None
    end: int | None
    identifier_type: str
    qi_categories: tuple[str, ...]
    granularity: str | None
    value_normalized: dict[str, Any] | None = field(default=None)


TEXT = "Jean Dupont a 28 ans et habite a Lille, il gagne un bon salaire."
#       0         1         2         3         4         5         6


def _direct(annotation_id="a-direct", start=0, end=11):
    return FakeAnnotation(
        annotation_id=annotation_id, start=start, end=end,
        identifier_type="DIRECT", qi_categories=("DIR_NAME",), granularity=None,
    )


def _quasi_age(annotation_id="a-age", start=14, end=16, level=0):
    return FakeAnnotation(
        annotation_id=annotation_id, start=start, end=end,
        identifier_type="QUASI", qi_categories=("GEN_AGE",), granularity="EXACT",
        value_normalized={"range": [28, 28], "level": level},
    )


def _quasi_geo(annotation_id="a-geo", start=33, end=38):
    return FakeAnnotation(
        annotation_id=annotation_id, start=start, end=end,
        identifier_type="QUASI", qi_categories=("GEN_GEO",), granularity="EXACT",
        value_normalized={"geo": "FR-59350", "level": 0},
    )


def _sensitive(annotation_id="a-sens", start=44, end=64):
    return FakeAnnotation(
        annotation_id=annotation_id, start=start, end=end,
        identifier_type="SENSITIVE_ONLY", qi_categories=("GEN_SOCIOECON",), granularity=None,
    )


def _quasi_seniority(annotation_id="a-sen", start=44, end=64):
    return FakeAnnotation(
        annotation_id=annotation_id, start=start, end=end,
        identifier_type="QUASI", qi_categories=("HR_SENIORITY",), granularity="EXACT",
    )


def _quasi_age_malformed(annotation_id="a-age-bad", start=14, end=16):
    return FakeAnnotation(
        annotation_id=annotation_id, start=start, end=end,
        identifier_type="QUASI", qi_categories=("GEN_AGE",), granularity="EXACT",
        value_normalized={"level": 0},
    )


# --------------------------------------------------------------------------- #
# models.py — chargement et validation
# --------------------------------------------------------------------------- #
def test_load_real_policy_set():
    policy_set = load_policy_set(POLICIES_PATH)
    for name in ("P0", "P1", "P2", "P3", "P4"):
        assert name in policy_set.policies


def test_policy_thresholds_must_be_monotone(tmp_path):
    bad = {
        "defaults": {
            "risk_model": "copula", "scope": "document", "use_upper_bound": True,
            "k_seuil_at_risk": 10, "sensitive_hardening": True,
            "action_selection": "max_risk_reduction_per_utility_loss",
        },
        "policies": {
            "PX": {
                "label": "cassée",
                "thresholds": {"keep_below": 0.5, "generalize_below": 0.1},
                "actions": {"DIRECT": "SUPPRESS", "QUASI": "GENERALIZE", "SENSITIVE_ONLY": "KEEP"},
            }
        },
    }
    path = tmp_path / "bad_policy.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(PolicyConfigError):
        load_policy_set(path)


def test_policy_unknown_action_rejected(tmp_path):
    bad = {
        "defaults": {
            "risk_model": "copula", "scope": "document", "use_upper_bound": True,
            "k_seuil_at_risk": 10, "sensitive_hardening": True,
            "action_selection": "max_risk_reduction_per_utility_loss",
        },
        "policies": {
            "PX": {
                "label": "cassée",
                "thresholds": {"keep_below": 0.2},
                "actions": {"DIRECT": "SUPPRESS", "QUASI": "TELEPORT", "SENSITIVE_ONLY": "KEEP"},
            }
        },
    }
    path = tmp_path / "bad_action.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(PolicyConfigError):
        load_policy_set(path)


def test_policy_malformed_yaml_rejected(tmp_path):
    path = tmp_path / "not_a_mapping.yaml"
    path.write_text("- juste une liste\n- pas un mapping\n", encoding="utf-8")
    with pytest.raises(PolicyConfigError):
        load_policy_set(path)


# --------------------------------------------------------------------------- #
# engine.py — comportement par politique
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def policy_set():
    return load_policy_set(POLICIES_PATH)


def test_p0_does_not_touch_quasi(policy_set):
    policy = policy_set.get("P0")
    engine = PolicyEngine(policy)
    annotations = [_direct(), _quasi_age(), _quasi_geo()]
    decisions = engine.plan(annotations, text=TEXT)

    quasi_decisions = [d for d in decisions if d.qi_category in ("GEN_AGE", "GEN_GEO")]
    assert quasi_decisions, "les décisions QUASI doivent exister"
    assert all(d.action is Action.KEEP for d in quasi_decisions)

    direct_decisions = [d for d in decisions if d.qi_category == "DIR_NAME"]
    assert all(d.action is Action.SUPPRESS for d in direct_decisions)


def test_p4_suppresses_all_quasi(policy_set):
    policy = policy_set.get("P4")
    engine = PolicyEngine(policy)
    annotations = [_direct(), _quasi_age(), _quasi_geo(), _sensitive()]
    decisions = engine.plan(annotations, text=TEXT)

    quasi_decisions = [d for d in decisions if d.qi_category in ("GEN_AGE", "GEN_GEO")]
    assert quasi_decisions
    assert all(d.action is Action.SUPPRESS for d in quasi_decisions)

    sensitive_decisions = [d for d in decisions if d.qi_category == "GEN_SOCIOECON"]
    assert all(d.action is Action.SUPPRESS for d in sensitive_decisions)


def test_direct_is_always_suppressed_regardless_of_policy(policy_set):
    for name in ("P1", "P2", "P3"):
        engine = PolicyEngine(policy_set.get(name))
        decisions = engine.plan([_direct()], text=TEXT)
        assert decisions[0].action is Action.SUPPRESS


def test_ignored_is_always_kept():
    policy = load_policy_set(POLICIES_PATH).get("P4")
    engine = PolicyEngine(policy)
    ann = FakeAnnotation(
        annotation_id="a-ign", start=0, end=4, identifier_type="IGNORED",
        qi_categories=("IGNORED",), granularity=None,
    )
    decisions = engine.plan([ann], text=TEXT)
    assert decisions[0].action is Action.KEEP


def test_decisions_are_explainable(policy_set):
    engine = PolicyEngine(policy_set.get("P2"))
    decisions = engine.plan([_quasi_age()], text=TEXT)
    for decision in decisions:
        assert decision.reason.strip() != ""
        assert decision.meta.get("risk_status") == "PROXY"


def test_monotonic_suppression_count_across_policies(policy_set):
    """P0 -> P4 doit produire un nombre de suppressions QUASI croissant (ou égal)."""
    annotations_factory = lambda: [_quasi_age(), _quasi_geo()]
    counts = []
    for name in ("P0", "P1", "P2", "P3", "P4"):
        engine = PolicyEngine(policy_set.get(name))
        decisions = engine.plan(annotations_factory(), text=TEXT)
        suppressed = sum(1 for d in decisions if d.action is Action.SUPPRESS)
        counts.append(suppressed)

    assert counts == sorted(counts), f"suppressions non monotones : {counts}"
    assert counts[0] == 0  # P0 ne supprime rien
    assert counts[-1] == 2  # P4 supprime tout


def test_generalize_reduces_risk_via_naive_estimator():
    estimator = NaiveRiskEstimator()
    from anonymisation.policy.engine import _QiState

    exact = [_QiState("a", "GEN_AGE", 0)]
    generalized = [_QiState("a", "GEN_AGE", 2)]
    assert estimator(generalized) < estimator(exact)


def test_custom_risk_fn_is_used_instead_of_naive(policy_set):
    calls = []

    def always_safe(states):
        calls.append(list(states))
        return 0.0  # toujours en dessous de tous les seuils

    engine = PolicyEngine(policy_set.get("P2"), risk_fn=always_safe)
    decisions = engine.plan([_quasi_age()], text=TEXT)
    assert calls  # le risk_fn injecté a bien été appelé
    assert decisions[0].action is Action.KEEP
    assert "risk_status" not in decisions[0].meta


# --------------------------------------------------------------------------- #
# Repli SUPPRESS (SPEC-06 §9) : hiérarchie absente ou état inutilisable
# --------------------------------------------------------------------------- #
def _seniority_drives_risk(states):
    """Risque piloté par le QI SANS hiérarchie : seule sa suppression le
    ramène sous le seuil — le repli SUPPRESS est la seule issue jouable."""
    return 0.6 if any(s.qi_category == "HR_SENIORITY" for s in states) else 0.01


def _malformed_age_drives_risk(states):
    """Risque piloté par le QI dont ``value_normalized`` est inutilisable."""
    return 0.6 if any(s.qi_category == "GEN_AGE" for s in states) else 0.01


def test_qi_without_hierarchy_falls_back_to_suppress(policy_set):
    """Un QI sans hiérarchie de généralisation (HR_SENIORITY) ne doit pas
    faire planter le moteur : le repli SPEC-06 §9 (SUPPRESS) s'applique dès
    que le seuil de risque n'est pas atteint, sans toucher les autres QI."""
    engine = PolicyEngine(policy_set.get("P2"), risk_fn=_seniority_drives_risk)
    decisions = engine.plan([_quasi_age(), _quasi_seniority()], text=TEXT)

    by_cat = {d.qi_category: d for d in decisions}
    assert set(by_cat) == {"GEN_AGE", "HR_SENIORITY"}
    suppressed = by_cat["HR_SENIORITY"]
    assert suppressed.action is Action.SUPPRESS
    assert suppressed.replacement == "[HR_SENIORITY_SUPPRIME]"
    assert suppressed.risk_before == pytest.approx(0.6)
    assert suppressed.risk_after == pytest.approx(0.01)
    assert "hiérarchie" in suppressed.reason
    # Le QI doté d'une hiérarchie reste intact : le seuil est atteint sans lui.
    assert by_cat["GEN_AGE"].action is Action.KEEP


def test_malformed_value_normalized_falls_back_to_suppress(policy_set):
    """``value_normalized`` hors du format de la hiérarchie (GEN_AGE sans
    ``range``) : le QI est réputé épuisé au niveau 0 — le repli SUPPRESS
    s'applique au lieu d'une erreur d'exécution."""
    engine = PolicyEngine(policy_set.get("P2"), risk_fn=_malformed_age_drives_risk)
    decisions = engine.plan([_quasi_age_malformed(), _quasi_seniority()], text=TEXT)

    by_cat = {d.qi_category: d for d in decisions}
    malformed = by_cat["GEN_AGE"]
    assert malformed.action is Action.SUPPRESS
    assert malformed.replacement == "[GEN_AGE_SUPPRIME]"
    assert malformed.risk_before == pytest.approx(0.6)
    assert malformed.risk_after == pytest.approx(0.01)
    assert "hiérarchie" in malformed.reason
    # Le QI sans hiérarchie survit ici : la suppression du QI malformé
    # ramène déjà le risque sous le seuil.
    assert by_cat["HR_SENIORITY"].action is Action.KEEP

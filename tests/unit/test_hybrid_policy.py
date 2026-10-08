"""Le noyau hybrid-qi exécute ses politiques hors réseau, sans erreurs cachées."""

from dataclasses import replace
from pathlib import Path

import pytest

from anonymisation.pipeline.traces import serialize_pipeline_result
from anonymisation.pipelines.hybrid_qi.policy import plan_hybrid_policy
from anonymisation.pipelines.hybrid_qi.risk import HybridRiskEstimate, QiAttribute
from anonymisation.policy.models import load_policy_set
from anonymisation.schema.io import read_jsonl
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import ExpressionMode, Granularity, IdentifierType, Stability
from anonymisation.systems import resolve_system
from anonymisation.transform.decisions import Action, ActionNotAllowedError, check_action_allowed


def _document(text):
    return Document(doc_id="d", dataset="mini", split="test", domain="hr", language="fr", text=text)


@pytest.mark.parametrize("policy", ["P0", "P1", "P2", "P3", "P4"])
@pytest.mark.parametrize("text", [
    "Contactez jean.dupont@example.com.", "J'ai 28 ans.", "Je suis doctorant.",
])
def test_fixed_and_quasi_decisions_complete_under_each_policy(policy, text, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("socket créé par le noyau hors ligne")

    monkeypatch.setattr("socket.socket", forbidden)
    cls = resolve_system("hybrid-qi")
    system = cls(replace(cls.contract_config(), policy_id=policy))
    first, second = system.run(_document(text), ()), system.run(_document(text), ())
    assert first.status in ("ok", "partial"), first.errors
    assert first.annotations and first.decisions
    assert serialize_pipeline_result(first, strict=True) == serialize_pipeline_result(second, strict=True)
    for decision in first.decisions:
        assert text[decision.start:decision.end] == decision.original
        assert decision.reason
        if decision.action is Action.KEEP:
            assert decision.replacement == decision.original
    if "@" in text:
        assert all(d.action is Action.SUPPRESS for d in first.decisions)
        assert "jean.dupont@example.com" not in first.anonymized_text
    elif policy == "P0":
        assert first.anonymized_text == text
        assert all(d.action is Action.KEEP for d in first.decisions)
    elif policy == "P4":
        assert all(d.action is Action.SUPPRESS for d in first.decisions)
        assert "28" not in first.anonymized_text and "doctorant" not in first.anonymized_text
        assert first.status == "ok", first.errors


def test_hybrid_micro_completes_offline_deterministically(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("socket créé par le noyau hors ligne")

    monkeypatch.setattr("socket.socket", forbidden)
    cls = resolve_system("hybrid-qi")
    system = cls(cls.contract_config())
    path = Path(__file__).resolve().parents[1] / "fixtures/micro/documents.jsonl"
    docs = list(read_jsonl(path, Document))
    assert docs
    for doc in docs:
        first, second = system.run(doc, ()), system.run(doc, ())
        assert first.status in ("ok", "partial"), first.errors
        assert serialize_pipeline_result(first, strict=True) == serialize_pipeline_result(second, strict=True)


def test_transform_action_table_remains_strict():
    with pytest.raises(ActionNotAllowedError):
        check_action_allowed(IdentifierType.DIRECT, None, Action.KEEP)
    with pytest.raises(ActionNotAllowedError):
        check_action_allowed(IdentifierType.QUASI, Granularity.COARSE, Action.GENERALIZE)


def _estimate(risk):
    return HybridRiskEstimate(population_id="fixture", k_hat=1000, k_interval=(100, 1000),
                              risk=risk, risk_point=risk)


def _policy(policy_id):
    from anonymisation.pipelines.hybrid_qi import policy

    return load_policy_set(Path(policy.__file__).with_name("policy.yaml")).get(policy_id)


def _annotation(word, start, category, identifier_type=IdentifierType.QUASI):
    return Annotation(annotation_id=word, doc_id="d", start=start, end=start + len(word),
                      span_text=word, qi_categories=(category,), identifier_type=identifier_type,
                      granularity=Granularity.COARSE, expression_mode=ExpressionMode.EXPLICIT,
                      stability=Stability.STABLE)


@pytest.mark.parametrize(("identifier_type", "category", "policy", "action"), [
    (IdentifierType.DIRECT, "DIR_NAME", "P2", Action.SUPPRESS),
    (IdentifierType.SENSITIVE_ONLY, "GEN_SOCIOECON", "P2", Action.KEEP),
    (IdentifierType.SENSITIVE_ONLY, "GEN_SOCIOECON", "P4", Action.SUPPRESS),
    (IdentifierType.IGNORED, "GEN_GEO", "P4", Action.KEEP),
])
def test_fixed_types_ignore_quasi_granularity(identifier_type, category, policy, action):
    decisions, _ = plan_hybrid_policy(
        doc=_document("Alice"), annotations=[_annotation("Alice", 0, category, identifier_type)],
        attributes=[], claims=[], estimator=None, policy=_policy(policy), risk_base=_estimate(0.001),
    )
    assert decisions[0].action is action
    assert decisions[0].replacement == ("Alice" if action is Action.KEEP else f"[{category}_SUPPRIME]")


@pytest.mark.parametrize("progress", [True, False])
def test_final_keep_and_nonprogress_fallback_have_numeric_residual_risk(progress):
    annotations = [_annotation("doctorant", 0, "GEN_EDUCATION"),
                   _annotation("Lyon", 10, "GEN_GEO")]
    attributes = [QiAttribute(category=a.qi_categories[0], value={}, expression_mode="EXPLICIT",
                              explicit=True, start=a.start, end=a.end) for a in annotations]

    class Estimator:
        def assess(self, active, **kwargs):
            return _estimate(0.001 if progress and len(active) < 2 else 0.2)

    decisions, meta = plan_hybrid_policy(
        doc=_document("doctorant Lyon"), annotations=annotations, attributes=attributes,
        claims=[], estimator=Estimator(), policy=_policy("P2"), risk_base=_estimate(0.2),
    )
    assert isinstance(meta["risk_final"], float)
    if progress:
        assert [d.action for d in decisions] == [Action.SUPPRESS, Action.KEEP]
        assert decisions[1].replacement == "Lyon"
        assert meta["risk_final"] == 0.001
    else:
        assert all(d.action is Action.SUPPRESS for d in decisions)
        assert all(d.meta["fallback"] == "seuil_non_atteint" for d in decisions)
        assert meta["risk_final"] == 0.2 and meta["seuil_non_atteint"]

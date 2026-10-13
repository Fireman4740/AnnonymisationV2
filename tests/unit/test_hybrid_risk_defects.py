"""Régressions des défauts hybrid-qi relevés par la campagne 40fc5bb5.

- ``RiskConfigError`` (ratbench:L1:8, dbbio:test:122) : deux attributs de la
  même catégorie corrélée dupliquaient une ligne de Σ → matrice singulière.
- ``MalformedValueNormalizedError`` (quasifr ticket_015, openpii:5336015,
  spia:TAB-32887) : le niveau de généralisation est porté par la catégorie ;
  une mention sans valeur normalisée de cette catégorie faisait échouer
  tout le document au lieu d'être supprimée explicitement.
"""

import math
from pathlib import Path

from anonymisation.pipelines.hybrid_qi.policy import plan_hybrid_policy
from anonymisation.pipelines.hybrid_qi.risk import (
    HybridRiskEstimate,
    HybridRiskEstimator,
    QiAttribute,
    _sigma_for,
    is_positive_definite,
    load_population,
)
from anonymisation.policy.models import load_policy_set
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import ExpressionMode, Granularity, IdentifierType, Stability
from anonymisation.transform.decisions import Action

_PKG = Path(__file__).resolve().parents[2] / "src/anonymisation/pipelines/hybrid_qi"


def _estimator():
    return HybridRiskEstimator(load_population(_PKG / "population.yaml"))


def _attr(category, value):
    return QiAttribute(category=category, value=value, expression_mode="EXPLICIT", explicit=True)


def test_two_attributes_of_one_correlated_category_keep_sigma_positive_definite():
    attrs = [_attr("GEN_GEO", {"geo": "FR-59350"}), _attr("GEN_GEO", {"geo": "FR-75056"}),
             _attr("GEN_AGE", {"range": [30, 34]})]
    estimate = _estimator().assess(attrs)
    assert math.isfinite(estimate.risk) and 0.0 <= estimate.risk <= 1.0


def test_sigma_rows_follow_the_attribute_order():
    parent = [[1.0, 0.2], [0.2, 1.0]]
    sigma = _sigma_for(("GEN_GENDER", "GEN_AGE", "GEN_GEO"), ("GEN_AGE", "GEN_GEO"), 0.0, parent=parent)
    assert sigma == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.2], [0.0, 0.2, 1.0]]
    duplicated = _sigma_for(("GEN_GEO", "GEN_GEO"), ("GEN_AGE", "GEN_GEO"), 0.0, parent=parent)
    assert duplicated == [[1.0, 0.0], [0.0, 1.0]]
    assert is_positive_definite(duplicated)


def _annotation(annotation_id, word, start, value):
    return Annotation(annotation_id=annotation_id, doc_id="d", start=start, end=start + len(word),
                      span_text=word, qi_categories=("GEN_GEO",), identifier_type=IdentifierType.QUASI,
                      granularity=Granularity.EXACT, expression_mode=ExpressionMode.EXPLICIT,
                      stability=Stability.STABLE, value_normalized=value)


def test_mention_without_normalized_value_is_suppressed_when_its_category_is_generalized():
    from anonymisation.pipelines.hybrid_qi import policy as policy_module

    text = "Lille Roubaix"
    annotations = [_annotation("a", "Lille", 0, {"geo": "FR-59350"}), _annotation("b", "Roubaix", 6, None)]
    attributes = [_attr("GEN_GEO", {"geo": "FR-59350"}), _attr("GEN_GEO", {})]

    def estimate(risk):
        return HybridRiskEstimate(population_id="fixture", k_hat=1000, k_interval=(100, 1000),
                                  risk=risk, risk_point=risk)

    class Estimator:
        def assess(self, active, levels=None, **kwargs):
            return estimate(0.001 if (levels or {}).get("GEN_GEO", 0) >= 1 else 0.2)

    policy = load_policy_set(Path(policy_module.__file__).with_name("policy.yaml")).get("P2")
    decisions, _ = plan_hybrid_policy(
        doc=Document(doc_id="d", dataset="mini", split="test", domain="hr", language="fr", text=text),
        annotations=annotations, attributes=attributes, claims=[], estimator=Estimator(),
        policy=policy, risk_base=estimate(0.2),
    )
    by_id = {d.original: d for d in decisions}
    assert by_id["Lille"].action is Action.GENERALIZE
    assert by_id["Roubaix"].action is Action.SUPPRESS
    assert by_id["Roubaix"].meta["fallback"] == "valeur_non_generalisable"

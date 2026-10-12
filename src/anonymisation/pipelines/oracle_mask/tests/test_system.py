"""Ancre oracle : masque exact des mentions gold ancrées."""

from __future__ import annotations

from anonymisation.pipelines.oracle_mask.system import OracleMaskSystem
from anonymisation.schema.models import Annotation, Document, Domain
from anonymisation.schema.taxonomy import ExpressionMode, Granularity, IdentifierType, Stability


def _annotation(start, end, text, category="DIR_NAME", ident=IdentifierType.DIRECT, **kw):
    return Annotation(annotation_id=f"a{start}", doc_id="d", start=start, end=end,
                      span_text=text, identifier_type=ident, qi_categories=(category,),
                      expression_mode=kw.get("mode", ExpressionMode.EXPLICIT),
                      granularity=Granularity.EXACT, stability=Stability.STABLE)


def test_oracle_suppresses_every_anchored_gold_mention_and_nothing_else():
    doc = Document(doc_id="d", dataset="x", split="test", domain=Domain.GENERIC, language="fr",
                   text="Alice, 34 ans, vit à Lyon.")
    gold = (_annotation(0, 5, "Alice"),
            _annotation(7, 13, "34 ans", "GEN_AGE", IdentifierType.QUASI),
            Annotation(annotation_id="implicit", doc_id="d", start=None, end=None, span_text=None,
                       identifier_type=IdentifierType.QUASI, qi_categories=("GEN_GEO",),
                       expression_mode=ExpressionMode.IMPLICIT, granularity=Granularity.EXACT,
                       stability=Stability.STABLE))
    result = OracleMaskSystem().run(doc, gold)
    assert result.status == "ok"
    assert result.anonymized_text == "[DIR_NAME], [GEN_AGE], vit à Lyon."
    assert len(result.annotations) == 2
    assert OracleMaskSystem.oracle is True

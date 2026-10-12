"""Ancre oracle : masque exactement les mentions gold ancrées.

Borne de référence du **masquage parfait de ce qui est annoté** : chaque
annotation gold à offsets reçoit une décision ``SUPPRESS`` (placeholder
nommant la catégorie), appliquée par la même chaîne que tous les systèmes
(fusion des chevauchements, ``apply_decisions``). Ce qui fuit encore après
l'oracle — attributs inférés sans span, indices contextuels — mesure ce que
les métriques de spans ne voient pas : c'est la comparaison que RAT-Bench
demande entre ``llm-full`` et ses ancres (EPIC-H H-3).

Système **oracle** (``oracle = True``, capacité ``gold_aware``) : il lit le gold
et ne doit jamais être classé parmi les systèmes évalués.
"""

from __future__ import annotations

from typing import ClassVar

from anonymisation.capabilities import CAP_DECISIONS, CAP_GOLD_AWARE, CAP_SPANS
from anonymisation.pipeline.orchestrator import _merge_overlapping
from anonymisation.pipeline.traces import PipelineResult
from anonymisation.schema.models import Annotation, Document
from anonymisation.systems.base import SystemBase
from anonymisation.systems.registry import register_system
from anonymisation.transform.apply import apply_decisions
from anonymisation.transform.decisions import Action, AnonymizationDecision


@register_system
class OracleMaskSystem(SystemBase):
    """Supprime chaque mention gold ancrée — ancre oracle, lit le gold."""

    system_id: ClassVar[str] = "oracle-mask-v1"
    system_version: ClassVar[str] = "1"
    aliases: ClassVar[tuple[str, ...]] = ("oracle-mask", "oracle")
    capabilities: ClassVar[frozenset[str]] = frozenset({CAP_SPANS, CAP_DECISIONS, CAP_GOLD_AWARE})
    oracle: ClassVar[bool] = True
    summary: ClassVar[str] = (
        "Oracle : supprime exactement les mentions gold ancrées. Ancre de référence, "
        "jamais un système évalué."
    )

    def _execute(self, doc: Document, gold: tuple[Annotation, ...]) -> PipelineResult:
        anchored = tuple(a for a in gold if a.start is not None and a.end is not None)
        decisions = []
        for annotation in anchored:
            if doc.text[annotation.start : annotation.end] != annotation.span_text:
                raise ValueError(
                    f"gold {annotation.annotation_id} : offsets [{annotation.start}:{annotation.end}] "
                    "hors du texte — pivot corrompu"
                )
            category = annotation.qi_categories[0]
            decisions.append(AnonymizationDecision(
                start=annotation.start, end=annotation.end, original=annotation.span_text,
                action=Action.SUPPRESS, replacement=f"[{category}]", qi_category=category,
                reason=f"Oracle : mention gold {annotation.annotation_id} supprimée",
            ))
        merged = _merge_overlapping(decisions, doc.text)
        transformed = apply_decisions(doc.text, merged)
        return PipelineResult(
            doc_id=doc.doc_id, original_text=doc.text,
            anonymized_text=transformed.anonymized_text, annotations=anchored,
            decisions=tuple(decisions), risk=None, policy_id="", traces=(), status="ok",
            errors=(), runtime_ms=0.0, identity=self.identity(),
        )


__all__ = ["OracleMaskSystem"]

"""Baseline regex-only : détection par motifs déclaratifs seuls et suppression.

Système d'évaluation de référence (quatrième système du lot L0/L3) :
- Utilise ``PatternDetector`` (aucun lexique contextuel, aucune règle QI) ;
- Produit des annotations localisées et des décisions SUPPRESS déterministes ;
- Déclare exactement ``spans | decisions`` (sans traces, sans risque, sans politique) ;
- N'accepte aucune politique (uses_policy = False) ;
- Ne lit jamais le gold (pas CAP_GOLD_AWARE).
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from anonymisation.capabilities import (
    CAP_DECISIONS,
    CAP_SPANS,
)
from anonymisation.detect import PatternDetector
from anonymisation.detect.base import candidates_to_annotations
from anonymisation.pipeline.orchestrator import _merge_overlapping
from anonymisation.pipeline.traces import PipelineResult
from anonymisation.schema.models import Annotation, Document
from anonymisation.systems.base import SystemBase, SystemConfig, SystemContractError
from anonymisation.systems.registry import register_system
from anonymisation.transform.apply import apply_decisions
from anonymisation.transform.decisions import Action, AnonymizationDecision


class _RegexOnlyParams(BaseModel):
    """Paramètres du système regex-only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: str = "priority_longest"


@register_system
class RegexOnlySystem(SystemBase):
    """Détection par expressions régulières déclaratives et suppression SUPPRESS."""

    system_id: ClassVar[str] = "regex-only-v1"
    system_version: ClassVar[str] = "1"
    aliases: ClassVar[tuple[str, ...]] = ("regex-only", "regex")
    capabilities: ClassVar[frozenset[str]] = frozenset({CAP_SPANS, CAP_DECISIONS})
    uses_policy: ClassVar[bool] = False
    offline_only: ClassVar[bool] = True
    summary: ClassVar[str] = (
        "Baseline regex pure : motifs déclaratifs sans règles contextuelles, "
        "décisions SUPPRESS directes. Pas de politique, pas d'estimation de risque."
    )
    Params: ClassVar[type[BaseModel] | None] = _RegexOnlyParams

    def __init__(self, config: SystemConfig | None = None) -> None:
        super().__init__(config)
        if self.config.policy_id:
            raise SystemContractError(
                f"Système {self.system_id!r} n'accepte aucune politique (fourni: {self.config.policy_id!r})."
            )
        strategy = str(self._params.get("strategy", "priority_longest"))
        self._detector = PatternDetector(
            config_path=self.config.config_path,
            strategy=strategy,
        )

    def _execute(
        self,
        doc: Document,
        gold: tuple[Annotation, ...],
    ) -> PipelineResult:
        # Ne lit jamais gold
        candidates = self._detector.detect(doc.text, doc.language)
        annotations = tuple(candidates_to_annotations(candidates, doc.doc_id, doc.text))

        decisions_list: list[AnonymizationDecision] = []
        for cand in candidates:
            decisions_list.append(
                AnonymizationDecision(
                    start=cand.start,
                    end=cand.end,
                    original=doc.text[cand.start : cand.end],
                    action=Action.SUPPRESS,
                    replacement=f"[{cand.qi_category}_SUPPRIME]",
                    qi_category=cand.qi_category,
                    reason=f"Regex-only: détection directe par motif ({cand.source}) -> SUPPRESS",
                )
            )

        decisions = tuple(decisions_list)
        merged = _merge_overlapping(decisions_list, doc.text)
        transform_res = apply_decisions(doc.text, merged)
        return PipelineResult(
            doc_id=doc.doc_id,
            original_text=doc.text,
            anonymized_text=transform_res.anonymized_text,
            annotations=annotations,
            decisions=decisions,
            risk=None,
            policy_id="",
            traces=(),
            status="ok",
            errors=(),
            runtime_ms=0.0,
            identity=self.identity(),
        )

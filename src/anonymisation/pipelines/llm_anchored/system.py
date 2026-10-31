"""Baseline fenêtrée + critique aveugle avec projection non ambiguë.

Hypothèse expérimentale : préserver les décisions de la baseline tout en
ajoutant des fuites résiduelles ancrées peut améliorer le compromis. Ni une
critique LLM ni des ancres exactes ne garantissent l'absence de fuite.
"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from anonymisation.capabilities import CAP_DECISIONS, CAP_SPANS
from anonymisation.detect.base import Candidate, candidates_to_annotations
from anonymisation.llm.client import LlmBackendUnavailableError, LlmClient, LlmEmptyResponseError
from anonymisation.llm.config import load_backends_config
from anonymisation.pipeline.orchestrator import _merge_overlapping
from anonymisation.pipeline.traces import PipelineResult
from anonymisation.pipelines.llm_anchored.prompts import SYSTEM, Finding, Findings, critic_prompt
from anonymisation.pipelines.llm_contextual.prompts import StructuredResponseError, parse_response
from anonymisation.pipelines.llm_contextual.system import (
    assert_local_backend,
    project_span,
    render_with_provenance,
)
from anonymisation.pipelines.llm_windowed.system import (
    LlmWindowedSystem,
    _identifier_type_for,
    _on_word_boundaries,
    split_windows,
)
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import ExpressionMode, Granularity, Stability
from anonymisation.systems.base import ModelRef, SystemBase, SystemConfig
from anonymisation.systems.registry import register_system
from anonymisation.transform.apply import apply_decisions
from anonymisation.transform.decisions import Action, AnonymizationDecision


class Params(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    backend: str = "qwen_local_box"
    window_chars: int = Field(default=6000, ge=500, le=12000)
    overlap_chars: int = Field(default=240, ge=0)
    max_output_tokens: int = Field(default=8192, ge=512, le=32768)
    max_entities: int = Field(default=256, ge=1)
    max_windows: int = Field(default=64, ge=1)
    temperature: float = Field(default=0.1, ge=0, le=1)
    critique: bool = True

    @model_validator(mode="after")
    def valid_window(self):
        if self.overlap_chars >= self.window_chars:
            raise ValueError("overlap_chars doit être inférieur à window_chars")
        return self


def locate_unique(text: str, finding: Finding) -> tuple[int, int] | None:
    """Localise uniquement une occurrence exacte et univoque avec son contexte."""
    matches = []
    start = text.find(finding.span)
    while start != -1:
        end = start + len(finding.span)
        if (_on_word_boundaries(text, start, end) and text[:start].endswith(finding.left)
                and text[end:].startswith(finding.right)):
            matches.append((start, end))
        start = text.find(finding.span, start + 1)
    return matches[0] if len(matches) == 1 else None


@register_system
class LlmAnchoredSystem(SystemBase):
    system_id: ClassVar[str] = "llm-anchored-v1"
    system_version: ClassVar[str] = "1"
    aliases: ClassVar[tuple[str, ...]] = ("llm-anchored",)
    capabilities: ClassVar[frozenset[str]] = frozenset({CAP_SPANS, CAP_DECISIONS})
    uses_policy: ClassVar[bool] = False
    offline_only: ClassVar[bool] = False
    summary: ClassVar[str] = "Qwen fenêtré suivi d'une critique aveugle ancrée sur les offsets originaux."
    Params: ClassVar[type[BaseModel]] = Params

    @classmethod
    def contract_config(cls) -> SystemConfig:
        return SystemConfig(params={"backend": "stub"})

    def __init__(self, config: SystemConfig | None = None) -> None:
        super().__init__(config)
        path = None if self.config.repo_root is None else self.config.repo_root / "configs/llm/backends.yaml"
        cfg = load_backends_config(path)
        backend = cfg.resolve(str(self._params["backend"]))
        assert_local_backend(backend)
        base_params = {k: self._params[k] for k in ("backend", "window_chars", "overlap_chars",
                       "max_output_tokens", "max_entities", "max_windows", "temperature")}
        self._baseline = LlmWindowedSystem(SystemConfig(params=base_params, repo_root=self.config.repo_root))
        extra = {**backend.extra_body, "chat_template_kwargs": {"enable_thinking": False}}
        if backend.kind == "stub":
            extra["stub_response"] = json.dumps({"entities": []})
        else:
            extra["structured_outputs"] = {"json": Findings.model_json_schema()}
        spec = replace(backend, extra_body=extra)
        self._critic = LlmClient.for_backend(backend.name, config=replace(cfg, backends={**cfg.backends, backend.name: spec}))

    def models(self) -> tuple[ModelRef, ...]:
        return self._baseline.models()

    def prompts(self) -> tuple[str, ...]:
        return (*self._baseline.prompts(), "anonymisation.pipelines.llm_anchored.prompts:critic_prompt")

    def _inspect(self, text: str) -> tuple[Findings, float]:
        last = None
        for _ in range(3):
            try:
                result = self._critic.complete(
                    critic_prompt(text), system=SYSTEM, temperature=self._params["temperature"],
                    max_tokens=self._params["max_output_tokens"],
                    validate=lambda s: parse_response(s, Findings),
                )
                return parse_response(result.content, Findings), result.latency_ms
            except (StructuredResponseError, LlmEmptyResponseError, LlmBackendUnavailableError) as exc:
                if isinstance(exc, LlmBackendUnavailableError) and not exc.retryable:
                    raise
                last = exc
        assert last is not None
        raise last

    def _execute(self, doc: Document, gold: tuple[Annotation, ...]) -> PipelineResult:
        # La baseline n'accède pas au gold ; elle conserve son prompt et son cache.
        baseline = self._baseline._execute(doc, ())
        if not self._params["critique"]:
            return replace(baseline, identity=self.identity())
        anonymized, segments, decisions = render_with_provenance(doc.text, list(baseline.decisions))
        windows = split_windows(anonymized, max_chars=self._params["window_chars"],
                                overlap_chars=self._params["overlap_chars"])
        if len(windows) > self._params["max_windows"]:
            raise ValueError("critique refusée : nombre de fenêtres supérieur à max_windows")
        warnings = list(baseline.errors)
        additions: list[Candidate] = []
        extra_decisions: list[AnonymizationDecision] = []
        seen: set[tuple[int, int, str]] = set()
        runtime = baseline.runtime_ms
        for window in windows:
            chunk = anonymized[window.prompt_start:window.prompt_end]
            findings, elapsed = self._inspect(chunk)
            runtime += elapsed
            for finding in findings.entities:
                local = locate_unique(chunk, finding)
                if local is None:
                    warnings.append("critique : ancre absente ou ambiguë")
                    continue
                output_start, output_end = window.prompt_start + local[0], window.prompt_start + local[1]
                # Une correction ne remplace jamais une décision de la baseline,
                # même si le critique cite un placeholder entier.
                unchanged = any(not s.replacement and s.start <= output_start < output_end <= s.end for s in segments)
                projected = project_span(segments, output_start, output_end) if unchanged else None
                if projected is None:
                    warnings.append("critique : span déjà transformé ou projection ambiguë")
                    continue
                a, b = projected
                key = (a, b, finding.category)
                if key in seen:
                    continue
                seen.add(key)
                text = doc.text[a:b]
                kind = _identifier_type_for(finding.category)
                additions.append(Candidate(start=a, end=b, text=text, qi_category=finding.category,
                    identifier_type=kind, source="llm-anchored:blind-critic", confidence=0.75,
                    granularity=Granularity.EXACT, stability=Stability.VOLATILE,
                    expression_mode=ExpressionMode.EXPLICIT))
                extra_decisions.append(AnonymizationDecision(start=a, end=b, original=text,
                    action=Action.SUPPRESS, replacement=f"[{finding.category}_SUPPRIME]",
                    qi_category=finding.category, reason="Critique aveugle : indice résiduel ancré"))
        merged = _merge_overlapping([*decisions, *extra_decisions], doc.text)
        extra_annotations = candidates_to_annotations(additions, doc.doc_id, doc.text)
        return PipelineResult(doc_id=doc.doc_id, original_text=doc.text,
            anonymized_text=apply_decisions(doc.text, merged).anonymized_text,
            annotations=(*baseline.annotations, *extra_annotations), decisions=tuple(merged), risk=None,
            policy_id="", traces=(), status="partial" if warnings else "ok", errors=tuple(warnings),
            runtime_ms=runtime, identity=self.identity())

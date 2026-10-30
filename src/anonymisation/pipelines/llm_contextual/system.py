"""Qwen local : plan global → éditions minimales → critique aveugle des fuites.

Les éditions gardent leurs offsets d'origine, même après la critique du texte
transformé. Le décodage JSON contraint évite les sorties malformées ; si une
fenêtre échoue ou est tronquée, elle seule est redécoupée. Aucune sortie
incomplète n'est acceptée. Un critique n'est pas une preuve de confidentialité.
"""

from __future__ import annotations

import ipaddress
import json
import time
from dataclasses import dataclass, replace
from typing import ClassVar
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from anonymisation.capabilities import CAP_DECISIONS, CAP_SPANS
from anonymisation.detect.base import Candidate, candidates_to_annotations
from anonymisation.llm.client import LlmBackendUnavailableError, LlmClient, LlmEmptyResponseError
from anonymisation.llm.config import BackendSpec, load_backends_config
from anonymisation.pipeline.orchestrator import _merge_overlapping
from anonymisation.pipeline.traces import PipelineResult
from anonymisation.pipelines.llm_contextual.prompts import (
    SYSTEM,
    ContextPlan,
    Edit,
    Edits,
    StrictModel,
    StructuredResponseError,
    critic_prompt,
    edit_prompt,
    parse_response,
    plan_prompt,
)
from anonymisation.pipelines.llm_windowed.system import (
    _identifier_type_for,
    _locate_nth,
    _resolve_action,
    split_windows,
)
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import ExpressionMode, Granularity, IdentifierType, Stability
from anonymisation.systems.base import ModelRef, SystemBase, SystemConfig
from anonymisation.systems.registry import register_system
from anonymisation.transform.apply import apply_decisions
from anonymisation.transform.decisions import Action, AnonymizationDecision


class Params(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    backend: str = "qwen_local_box"
    window_chars: int = Field(default=3000, ge=500, le=6000)
    min_window_chars: int = Field(default=500, ge=100)
    overlap_chars: int = Field(default=240, ge=0)
    max_output_tokens: int = Field(default=8192, ge=512, le=32768)
    max_document_chars: int = Field(default=16000, ge=1000)
    max_windows: int = Field(default=128, ge=1)
    critique_rounds: int = Field(default=1, ge=0, le=2)
    temperature: float = Field(default=0.1, ge=0, le=1)

    @model_validator(mode="after")
    def valid_window_sizes(self):
        if self.overlap_chars >= self.min_window_chars or self.min_window_chars > self.window_chars:
            raise ValueError("overlap_chars < min_window_chars <= window_chars requis")
        return self


def assert_local_backend(backend: BackendSpec) -> None:
    if backend.kind == "stub":
        return
    host = urlparse(backend.base_url or "").hostname
    try:
        local = host == "localhost" or ipaddress.ip_address(host or "").is_private
    except ValueError:
        local = False
    if backend.kind != "openai_compatible" or not local:
        raise ValueError("llm-contextual exige une API locale (localhost ou adresse IP privée)")


@dataclass(frozen=True)
class SourceSegment:
    start: int
    end: int
    original_start: int
    original_end: int
    replacement: bool = False


def render_with_provenance(text: str, decisions: list[AnonymizationDecision]):
    """Texte appliqué + projection des morceaux vers les offsets originaux."""
    merged = sorted(_merge_overlapping(decisions, text), key=lambda d: d.start)
    chunks, segments = [], []
    cursor, output_cursor = 0, 0
    for d in merged:
        unchanged = text[cursor : d.start]
        if unchanged:
            chunks.append(unchanged)
            segments.append(
                SourceSegment(output_cursor, output_cursor + len(unchanged), cursor, d.start)
            )
            output_cursor += len(unchanged)
        chunks.append(d.replacement)
        if d.replacement:
            segments.append(
                SourceSegment(
                    output_cursor, output_cursor + len(d.replacement), d.start, d.end, True
                )
            )
            output_cursor += len(d.replacement)
        cursor = d.end
    if cursor < len(text):
        chunks.append(text[cursor:])
        segments.append(
            SourceSegment(output_cursor, output_cursor + len(text) - cursor, cursor, len(text))
        )
    rendered = "".join(chunks)
    assert rendered == apply_decisions(text, merged).anonymized_text
    return rendered, segments, merged


def project_span(segments: list[SourceSegment], start: int, end: int):
    for s in segments:
        if s.start <= start < end <= s.end:
            if not s.replacement:
                return s.original_start + start - s.start, s.original_start + end - s.start
            if (start, end) == (s.start, s.end):
                return s.original_start, s.original_end
    return None


@register_system
class LlmContextualSystem(SystemBase):
    system_id: ClassVar[str] = "llm-contextual-v1"
    system_version: ClassVar[str] = "1"
    aliases: ClassVar[tuple[str, ...]] = ("llm-contextual",)
    capabilities: ClassVar[frozenset[str]] = frozenset({CAP_SPANS, CAP_DECISIONS})
    uses_policy: ClassVar[bool] = False
    offline_only: ClassVar[bool] = False
    summary: ClassVar[str] = (
        "Qwen local : intention globale, éditions minimales et critique aveugle des indices personnels résiduels."
    )
    Params: ClassVar[type[BaseModel]] = Params

    @classmethod
    def contract_config(cls) -> SystemConfig:
        return SystemConfig(params={"backend": "stub"})

    def __init__(self, config: SystemConfig | None = None) -> None:
        super().__init__(config)
        path = (
            None
            if self.config.repo_root is None
            else self.config.repo_root / "configs/llm/backends.yaml"
        )
        cfg = load_backends_config(path)
        backend = cfg.resolve(str(self._params["backend"]))
        assert_local_backend(backend)
        self._clients = {}
        for stage, schema in (("plan", ContextPlan), ("edit", Edits), ("critic", Edits)):
            extra = {**backend.extra_body, "chat_template_kwargs": {"enable_thinking": False}}
            if backend.kind == "stub":
                extra["stub_response"] = (
                    json.dumps({"intent": "other", "utility_terms": [], "risks": []})
                    if stage == "plan"
                    else '{"entities": []}'
                )
            else:
                extra["structured_outputs"] = {"json": schema.model_json_schema()}
            spec = replace(backend, extra_body=extra)
            stage_cfg = replace(cfg, backends={**cfg.backends, backend.name: spec})
            self._clients[stage] = LlmClient.for_backend(backend.name, config=stage_cfg)

    def models(self) -> tuple[ModelRef, ...]:
        b = self._clients["edit"].backend
        return (ModelRef(name=str(b.model), revision=b.name),)

    def prompts(self) -> tuple[str, ...]:
        return tuple(
            f"anonymisation.pipelines.llm_contextual.prompts:{s}"
            for s in ("plan_prompt", "edit_prompt", "critic_prompt")
        )

    def _complete(self, stage: str, prompt: str, schema: type[StrictModel], accounting: dict):
        last = None
        for attempt in range(3):
            try:
                result = self._clients[stage].complete(
                    prompt,
                    system=SYSTEM,
                    temperature=self._params["temperature"],
                    max_tokens=min(self._params["max_output_tokens"], 4096)
                    if stage == "plan"
                    else self._params["max_output_tokens"],
                    validate=lambda s: parse_response(s, schema),
                )
                accounting["runtime_ms"] += result.latency_ms
                return parse_response(result.content, schema)
            except LlmBackendUnavailableError as exc:
                if not exc.retryable or attempt == 2:
                    raise
                time.sleep((2, 5)[attempt])
                last = exc
            except (StructuredResponseError, LlmEmptyResponseError) as exc:
                # Retry explicite : une troncature/vide reste une erreur si
                # toutes les tentatives et tous les redécoupages échouent.
                last = exc
        assert last is not None
        raise last

    def _window_edits(
        self,
        text: str,
        base: int,
        size: int,
        plan: ContextPlan,
        warnings: list[str],
        accounting: dict,
        stage: str = "edit",
    ):
        out = []
        overlap = min(self._params["overlap_chars"], size - 1)
        for window in split_windows(text, max_chars=size, overlap_chars=overlap):
            accounting["windows"] += 1
            if accounting["windows"] > self._params["max_windows"]:
                raise ValueError("max_windows atteint : aucun texte partiellement traité accepté")
            chunk = text[window.prompt_start : window.prompt_end]
            try:
                prompt = (
                    edit_prompt(chunk, plan)
                    if stage == "edit"
                    else critic_prompt(chunk, plan.intent)
                )
                edits = self._complete(stage, prompt, Edits, accounting)
                out.extend((base + window.prompt_start, chunk, edit) for edit in edits.entities)
            except (StructuredResponseError, LlmEmptyResponseError):
                minimum = self._params["min_window_chars"]
                if size <= minimum or len(chunk) <= minimum:
                    raise
                smaller = max(minimum, size // 2)
                warnings.append(
                    f"fenêtre redécoupée après réponse invalide : {len(chunk)} caractères"
                )
                out.extend(
                    self._window_edits(
                        chunk,
                        base + window.prompt_start,
                        smaller,
                        plan,
                        warnings,
                        accounting,
                        stage,
                    )
                )
        return out

    def _execute(self, doc: Document, gold: tuple[Annotation, ...]) -> PipelineResult:
        # Seul doc.text est lu. Ni gold, ni doc.dataset/meta, ni label aval.
        if len(doc.text) > self._params["max_document_chars"]:
            raise ValueError(
                "document trop long pour le contexte global : aucune troncature silencieuse"
            )
        warnings: list[str] = []
        accounting = {"runtime_ms": 0.0, "windows": 0}
        plan = self._complete("plan", plan_prompt(doc.text), ContextPlan, accounting)
        # Retire les indices de plan inventés, avant qu'ils puissent guider les éditions.
        risks = []
        for risk in plan.risks:
            spans = [s for s in risk.spans if s and s in doc.text]
            if len(spans) != len(risk.spans):
                warnings.append("indice global sans ancrage écarté")
            if spans:
                risks.append(risk.model_copy(update={"spans": spans}))
        plan = plan.model_copy(update={"risks": risks})
        accepted: dict[tuple[int, int], tuple[Candidate, AnonymizationDecision]] = {}
        pseudonyms: dict[tuple[str, str], str] = {}

        def add(base: int, chunk: str, edit: Edit, segments=None):
            occurrence = 0
            matched = False
            while (located := _locate_nth(chunk, edit.span, occurrence)) is not None:
                matched = True
                occurrence += 1
                a, b = base + located[0], base + located[1]
                if segments is not None:
                    projected = project_span(segments, a, b)
                    if projected is None:
                        warnings.append("édition du critique sans projection univoque écartée")
                        continue
                    a, b = projected
                category = edit.category
                kind = _identifier_type_for(category)
                previous = accepted.get((a, b))
                if (
                    previous
                    and previous[0].identifier_type is IdentifierType.DIRECT
                    and kind is not IdentifierType.DIRECT
                ):
                    warnings.append("édition affaiblissant un identifiant direct écartée")
                    continue
                original = doc.text[a:b]
                action, replacement, coerced = _resolve_action(
                    kind, category, edit.action, edit.replacement
                )
                if kind is IdentifierType.DIRECT:
                    key = (category, original.casefold())
                    if key not in pseudonyms:
                        pseudonyms[key] = f"[ANON_{category}_{len(pseudonyms) + 1}]"
                    replacement = pseudonyms[key]
                elif action is Action.GENERALIZE and original.casefold() in replacement.casefold():
                    action, replacement, coerced = Action.SUPPRESS, f"[ANON_{category}]", True
                if coerced:
                    warnings.append(f"action repliée explicitement : {category}")
                candidate = Candidate(
                    start=a,
                    end=b,
                    text=original,
                    qi_category=category,
                    identifier_type=kind,
                    source=f"llm-contextual:{self._clients['edit'].backend.name}",
                    confidence=0.75,
                    granularity=Granularity.EXACT,
                    stability=Stability.VOLATILE,
                    expression_mode=ExpressionMode.EXPLICIT,
                )
                decision = AnonymizationDecision(
                    start=a,
                    end=b,
                    original=original,
                    action=action,
                    replacement=replacement,
                    qi_category=category,
                    reason="Qwen local : contexte et indices personnels",
                )
                accepted[a, b] = candidate, decision
            if not matched:
                warnings.append(f"entité sans ancrage écartée : {edit.category}")

        for base, chunk, edit in self._window_edits(
            doc.text, 0, self._params["window_chars"], plan, warnings, accounting
        ):
            add(base, chunk, edit)
        for _ in range(self._params["critique_rounds"]):
            anonymized, segments, _merged = render_with_provenance(
                doc.text, [d for c, d in accepted.values()]
            )
            # Essai global, puis redécoupage local seulement en cas d'échec.
            # Le plan original n'entre jamais dans le prompt du critique.
            critique = self._window_edits(
                anonymized, 0, max(1, len(anonymized)), plan, warnings, accounting, "critic"
            )
            if not critique:
                break
            for base, chunk, edit in critique:
                add(base, chunk, edit, segments)
        anonymized, _, merged = render_with_provenance(doc.text, [d for c, d in accepted.values()])
        annotations = tuple(
            candidates_to_annotations([c for c, d in accepted.values()], doc.doc_id, doc.text)
        )
        return PipelineResult(
            doc_id=doc.doc_id,
            original_text=doc.text,
            anonymized_text=anonymized,
            annotations=annotations,
            decisions=tuple(merged),
            risk=None,
            policy_id="",
            traces=(),
            status="partial" if warnings else "ok",
            errors=tuple(warnings),
            runtime_ms=accounting["runtime_ms"],
            identity=self.identity(),
        )

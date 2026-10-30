"""Contrats de confidentialité, ancrage et reprise du pipeline contextuel."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from anonymisation.llm.client import LlmCompletion, LlmEmptyResponseError
from anonymisation.llm.config import BackendSpec
from anonymisation.pipelines.llm_contextual.system import (
    LlmContextualSystem,
    Params,
    SourceSegment,
    assert_local_backend,
    project_span,
)
from anonymisation.schema.models import Document, Domain
from anonymisation.systems.base import SystemConfig


def doc(text):
    return Document(
        doc_id="synthetic-1",
        dataset="synthetic",
        split="test",
        domain=Domain.GENERIC,
        language="fr",
        text=text,
    )


def edit(span, category="DIR_NAME", action="SUPPRESS", replacement=""):
    return {"span": span, "category": category, "action": action, "replacement": replacement}


def setup(monkeypatch, text, editor, critic=(), **params):
    system = LlmContextualSystem(SystemConfig(params={"backend": "stub", **params}))
    seen = {s: [] for s in ("plan", "edit", "critic")}
    for stage, client in system._clients.items():

        def complete(prompt, _stage=stage, **kwargs):
            seen[_stage].append((prompt, kwargs))
            if _stage == "plan":
                payload = {"intent": "biography", "utility_terms": ["profession"], "risks": []}
            elif _stage == "edit":
                chunk = json.loads(prompt.split("DONNEES_JSON:\n")[1])["extrait"]
                payload = {"entities": editor(chunk) if callable(editor) else editor}
            else:
                payload = {"entities": list(critic)}
            content = json.dumps(payload)
            if kwargs.get("validate"):
                kwargs["validate"](content)
            return LlmCompletion(
                content=content,
                backend="stub",
                model="stub",
                cached=False,
                finish_reason="stop",
                latency_ms=1,
            )

        monkeypatch.setattr(client, "complete", complete)
    return system, seen


def test_repeated_names_are_all_masked_and_preserve_coreference(monkeypatch):
    text = "Alice rencontre Alice. Malice reste un autre mot."
    system, seen = setup(monkeypatch, text, [edit("Alice")])
    result = system.run(doc(text))
    assert result.status == "ok"
    assert "Alice" not in result.anonymized_text
    assert "Malice" in result.anonymized_text
    assert len(result.decisions) == 2
    assert result.decisions[0].replacement == result.decisions[1].replacement
    assert all(text[a.start : a.end] == a.span_text for a in result.annotations)
    assert len(seen["critic"]) == 1


def test_critic_is_blind_and_projects_offsets_after_length_changes(monkeypatch):
    text = "Élodie 😃 est née en 1981."
    system, seen = setup(
        monkeypatch,
        text,
        [edit("Élodie")],
        [edit("1981", "GEN_AGE", "GENERALIZE", "une année non précisée")],
    )
    result = system.run(doc(text))
    critic_data = json.loads(seen["critic"][0][0].split("DONNEES_JSON:\n")[1])
    assert "Élodie" not in critic_data["texte_anonymise"]
    assert set(critic_data) == {"texte_anonymise", "intention"}
    assert "1981" not in result.anonymized_text
    a = next(a for a in result.annotations if a.span_text == "1981")
    assert a.start == text.index("1981")
    assert text[a.start : a.end] == a.span_text


def test_critic_can_strengthen_a_whole_generalization(monkeypatch):
    text = "Je vis à Paris."
    system, _ = setup(
        monkeypatch,
        text,
        [edit("Paris", "GEN_GEO", "GENERALIZE", "en France")],
        [edit("en France", "GEN_GEO", "SUPPRESS")],
    )
    result = system.run(doc(text))
    assert "Paris" not in result.anonymized_text and "France" not in result.anonymized_text
    assert len(result.decisions) == 1
    assert result.decisions[0].original == "Paris"


def test_critic_cannot_project_part_of_a_replacement(monkeypatch):
    text = "Je vis à Paris."
    system, _ = setup(
        monkeypatch,
        text,
        [edit("Paris", "GEN_GEO", "GENERALIZE", "en France")],
        [edit("France", "GEN_GEO", "SUPPRESS")],
    )
    result = system.run(doc(text))
    assert result.status == "partial"
    assert "projection" in str(result.errors)
    assert "en France" in result.anonymized_text


def test_partial_word_does_not_mask_another_name(monkeypatch):
    text = "Ann et Anne."
    system, _ = setup(monkeypatch, text, [edit("Ann")])
    result = system.run(doc(text))
    assert "Anne" in result.anonymized_text
    assert len(result.annotations) == 1


def test_non_private_task_terms_remain_unchanged(monkeypatch):
    text = "My refund failed; please cancel the order."
    system, _ = setup(monkeypatch, text, [])
    assert system.run(doc(text)).anonymized_text == text


def test_personal_value_is_never_preserved_by_fake_generalization(monkeypatch):
    system, _ = setup(
        monkeypatch, "Paris", [edit("Paris", "GEN_GEO", "GENERALIZE", "Paris et sa région")]
    )
    result = system.run(doc("Paris"))
    assert result.status == "partial"
    assert "Paris" not in result.anonymized_text


def test_gold_is_not_read(monkeypatch):
    class ForbiddenGold:
        def __iter__(self):
            raise AssertionError("gold lu")

    system, _ = setup(monkeypatch, "Alice", [edit("Alice")])
    assert system._execute(doc("Alice"), ForbiddenGold()).status == "ok"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "{",
        '{"entities":null}',
        '{"entities":[{"span":"Alice","category":"invented","action":"SUPPRESS","replacement":""}]}',
    ],
)
def test_invalid_json_is_never_a_clean_document(monkeypatch, bad):
    system, _ = setup(monkeypatch, "Alice", [])

    def invalid(prompt, **kwargs):
        kwargs["validate"](bad)
        raise AssertionError("validation aurait dû échouer")

    monkeypatch.setattr(system._clients["edit"], "complete", invalid)
    result = system.run(doc("Alice"))
    assert result.status == "error"
    assert "StructuredResponseError" in str(result.errors)


def test_truncated_window_is_retried_then_split_without_losing_coverage(monkeypatch):
    text = " ".join(["Alice"] * 150)
    system, seen = setup(monkeypatch, text, lambda chunk: [edit("Alice")])
    original = system._clients["edit"].complete

    def complete(prompt, **kwargs):
        chunk = json.loads(prompt.split("DONNEES_JSON:\n")[1])["extrait"]
        if len(chunk) > 500:
            raise LlmEmptyResponseError("réponse tronquée : length")
        return original(prompt, **kwargs)

    monkeypatch.setattr(system._clients["edit"], "complete", complete)
    result = system.run(doc(text))
    assert result.status == "partial"
    assert "Alice" not in result.anonymized_text
    assert len(result.decisions) == 150
    assert "redécoupée" in str(result.errors)


def test_unrecoverable_empty_response_is_an_error(monkeypatch):
    system, _ = setup(monkeypatch, "Alice", [])

    def empty(*args, **kwargs):
        raise LlmEmptyResponseError("réponse vide")

    monkeypatch.setattr(system._clients["critic"], "complete", empty)
    assert system.run(doc("Alice")).status == "error"


@pytest.mark.parametrize("url", ["https://openrouter.ai/api/v1", "http://8.8.8.8/v1", ""])
def test_remote_backend_is_rejected_before_any_call(url):
    with pytest.raises(ValueError, match="locale"):
        assert_local_backend(BackendSpec(name="remote", kind="openai_compatible", base_url=url))


def test_stage_schemas_and_disabled_thinking_are_sent_only_by_new_pipeline():
    system = LlmContextualSystem(SystemConfig(params={"backend": "qwen_local_box"}))
    for client in system._clients.values():
        extra = client.backend.extra_body
        assert extra["chat_template_kwargs"]["enable_thinking"] is False
        assert "structured_outputs" in extra
        assert extra["structured_outputs"]["json"]["additionalProperties"] is False
    assert (
        system._clients["plan"].backend.extra_body != system._clients["critic"].backend.extra_body
    )


def test_projection_rejects_spans_crossing_multiple_segments():
    segments = [SourceSegment(0, 3, 0, 3), SourceSegment(3, 6, 3, 7, True)]
    assert project_span(segments, 1, 5) is None
    assert project_span(segments, 3, 6) == (3, 7)


@pytest.mark.parametrize(
    "params",
    [
        {"min_window_chars": 200, "overlap_chars": 240},
        {"min_window_chars": 4000},
        {"critique_rounds": 3},
    ],
)
def test_invalid_budgets_are_rejected(params):
    with pytest.raises(ValidationError):
        Params(**params)


def test_unanchored_model_proposals_are_flagged(monkeypatch):
    system, _ = setup(monkeypatch, "Alice", [edit("Bob")])
    result = system.run(doc("Alice"))
    assert result.status == "partial"
    assert result.anonymized_text == "Alice"
    assert "sans ancrage" in str(result.errors)


def test_critic_cannot_weaken_a_direct_identifier(monkeypatch):
    system, _ = setup(
        monkeypatch,
        "Alice",
        [edit("Alice")],
        [edit("[ANON_DIR_NAME_1]", "GEN_GEO", "GENERALIZE", "Alice")],
    )
    result = system.run(doc("Alice"))
    assert result.status == "partial"
    assert "Alice" not in result.anonymized_text
    assert "affaiblissant" in str(result.errors)


def test_long_critic_response_falls_back_to_smaller_views(monkeypatch):
    text = "contenu public. " * 100
    system, _ = setup(monkeypatch, text, [])
    original = system._clients["critic"].complete
    sizes = []

    def complete(prompt, **kwargs):
        view = json.loads(prompt.split("DONNEES_JSON:\n")[1])["texte_anonymise"]
        sizes.append(len(view))
        if len(view) > 800:
            raise LlmEmptyResponseError("réponse tronquée : length")
        return original(prompt, **kwargs)

    monkeypatch.setattr(system._clients["critic"], "complete", complete)
    result = system.run(doc(text))
    assert result.status == "partial"
    assert result.anonymized_text == text
    assert max(sizes) == len(text)
    assert any(size <= 800 for size in sizes)
    assert "redécoupée" in str(result.errors)

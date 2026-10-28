"""Tests de ``LlmWindowedSystem`` — aucun test ici n'ouvre de socket.

``LlmClient.complete`` est monkeypatché : ce qui est testé, c'est le
découpage, la reconstruction déterministe des offsets, la déduplication des
recouvrements et la gestion des erreurs, pas le modèle lui-même.
"""

from __future__ import annotations

import json
from itertools import pairwise

import pytest

from anonymisation.capabilities import CAP_DECISIONS, CAP_SPANS
from anonymisation.llm.client import LlmCompletion, LlmEmptyResponseError
from anonymisation.pipelines.llm_windowed.system import (
    MALFORMED_RESPONSE_ATTEMPTS,
    LlmWindowedSystem,
    split_windows,
)
from anonymisation.schema.models import Document, Domain
from anonymisation.systems.base import SystemConfig


def _system(**params: object) -> LlmWindowedSystem:
    raw = {"backend": "qwen_local", **params}
    return LlmWindowedSystem(SystemConfig(params=raw))


def _doc(text: str, doc_id: str = "doc-1") -> Document:
    return Document(
        doc_id=doc_id,
        dataset="test_ds",
        split="test",
        domain=Domain.GENERIC,
        language="fr",
        text=text,
    )


def _stub_completion(entities: list[dict]) -> LlmCompletion:
    return LlmCompletion(
        content=json.dumps({"entities": entities}),
        backend="qwen_local",
        model="stub",
        cached=False,
        finish_reason="stop",
        latency_ms=1.0,
    )


def _prompt_chunk(prompt: str) -> str:
    return prompt.split("EXTRAIT:\n", 1)[1]


def _filler(length: int, seed: str = "x") -> str:
    return (seed * length)[:length]


def test_identity_and_capabilities():
    system = _system()
    ident = system.identity()
    assert ident.system_id == "llm-windowed-v1"
    assert system.capabilities == frozenset({CAP_SPANS, CAP_DECISIONS})
    assert system.uses_policy is False
    assert system.offline_only is False


def test_split_windows_covers_every_character_exactly_once():
    text = "".join(f"Paragraphe {index} avec du texte. " * 4 + "\n\n" for index in range(30))
    windows = split_windows(text, max_chars=400, overlap_chars=50)
    assert windows
    assert windows[0].segment_start == 0
    assert windows[-1].segment_end == len(text)
    for previous, current in pairwise(windows):
        assert previous.segment_end == current.segment_start
    for window in windows:
        assert window.segment_start < window.segment_end
        assert window.prompt_start <= window.segment_start
        assert window.prompt_end == window.segment_end


def test_split_windows_short_text_and_empty_text():
    assert split_windows("", max_chars=100, overlap_chars=10) == ()
    windows = split_windows("court", max_chars=100, overlap_chars=10)
    assert len(windows) == 1
    assert (windows[0].prompt_start, windows[0].prompt_end) == (0, 5)


@pytest.mark.parametrize("max_chars,overlap", [(0, 0), (100, -1), (100, 100)])
def test_split_windows_rejects_invalid_parameters(max_chars: int, overlap: int):
    with pytest.raises(ValueError):
        split_windows("texte", max_chars=max_chars, overlap_chars=overlap)


def test_short_document_makes_one_call_and_masks_entities(monkeypatch: pytest.MonkeyPatch):
    system = _system()
    calls: list[str] = []

    def complete(prompt: str, **kwargs: object) -> LlmCompletion:
        calls.append(prompt)
        return _stub_completion(
            [
                {"span": "Jean Dupont", "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""},
                {
                    "span": "28 ans",
                    "category": "GEN_AGE",
                    "action": "GENERALIZE",
                    "replacement": "25-30 ans",
                },
            ]
        )

    monkeypatch.setattr(system._client, "complete", complete)
    doc = _doc("Jean Dupont a 28 ans.")
    result = system.run(doc)

    assert result.status == "ok", result.errors
    assert len(calls) == 1
    assert len(result.annotations) == 2
    for annotation in result.annotations:
        assert doc.text[annotation.start : annotation.end] == annotation.span_text
    assert "Jean Dupont" not in result.anonymized_text
    assert "25-30 ans" in result.anonymized_text


def test_long_document_is_windowed_and_all_entities_are_masked(monkeypatch: pytest.MonkeyPatch):
    names = [f"Personne{index} Unique" for index in range(8)]
    paragraphs = [
        _filler(420, chr(ord("a") + index)) + f" {name} " + _filler(120, "z")
        for index, name in enumerate(names)
    ]
    text = "\n\n".join(paragraphs)
    system = _system(window_chars=900, overlap_chars=120)
    calls: list[str] = []

    def complete(prompt: str, **kwargs: object) -> LlmCompletion:
        calls.append(prompt)
        chunk = _prompt_chunk(prompt)
        return _stub_completion(
            [
                {"span": name, "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""}
                for name in names
                if name in chunk
            ]
        )

    monkeypatch.setattr(system._client, "complete", complete)
    doc = _doc(text)
    result = system.run(doc)

    assert len(calls) > 1
    assert result.status in ("ok", "partial"), result.errors
    assert len(result.annotations) == len(names)
    assert {annotation.span_text for annotation in result.annotations} == set(names)
    for name in names:
        assert name not in result.anonymized_text
    for annotation in result.annotations:
        assert doc.text[annotation.start : annotation.end] == annotation.span_text


def test_overlap_duplicate_is_decided_once(monkeypatch: pytest.MonkeyPatch):
    text = _filler(470) + " Alice " + _filler(300, "b")
    system = _system(window_chars=500, overlap_chars=100)

    def complete(prompt: str, **kwargs: object) -> LlmCompletion:
        chunk = _prompt_chunk(prompt)
        entities = []
        if "Alice" in chunk:
            entities.append(
                {"span": "Alice", "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""}
            )
        return _stub_completion(entities)

    monkeypatch.setattr(system._client, "complete", complete)
    doc = _doc(text)
    result = system.run(doc)

    assert len(result.annotations) == 1
    assert result.annotations[0].span_text == "Alice"
    assert "Alice" not in result.anonymized_text


def test_an_entity_spanning_a_boundary_is_recovered_from_the_overlap(
    monkeypatch: pytest.MonkeyPatch,
):
    name = ("Alexandre-" * 20) + "Martin"
    text = _filler(332) + " " + name + " " + _filler(300, "c")
    system = _system(window_chars=500, overlap_chars=200)

    def complete(prompt: str, **kwargs: object) -> LlmCompletion:
        chunk = _prompt_chunk(prompt)
        entities = []
        if name in chunk:
            entities.append(
                {"span": name, "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""}
            )
        return _stub_completion(entities)

    monkeypatch.setattr(system._client, "complete", complete)
    doc = _doc(text)
    result = system.run(doc)

    assert result.annotations
    assert result.annotations[0].span_text == name
    assert name not in result.anonymized_text


def test_a_failing_window_puts_the_whole_document_in_error(monkeypatch: pytest.MonkeyPatch):
    system = _system(window_chars=700, overlap_chars=50)
    calls = 0

    def complete(prompt: str, **kwargs: object) -> LlmCompletion:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise LlmEmptyResponseError("réponse vide")
        return _stub_completion([])

    monkeypatch.setattr(system._client, "complete", complete)
    doc = _doc(_filler(2000, "d"))
    result = system.run(doc)

    assert calls == 2
    assert result.status == "error"
    assert result.anonymized_text == doc.text
    assert any("réponse vide" in error for error in result.errors)


def test_malformed_response_is_retried_then_succeeds(monkeypatch: pytest.MonkeyPatch):
    system = _system()
    calls: list[dict[str, object]] = []

    def complete(prompt: str, **kwargs: object) -> LlmCompletion:
        calls.append(kwargs)
        if len(calls) == 1:
            return LlmCompletion(
                content="pas du json",
                backend="qwen_local",
                model="stub",
                cached=False,
                finish_reason="stop",
                latency_ms=1.0,
            )
        return _stub_completion(
            [{"span": "Jean Dupont", "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""}]
        )

    monkeypatch.setattr(system._client, "complete", complete)
    doc = _doc("Jean Dupont est ici.")
    result = system.run(doc)

    assert result.status == "ok", result.errors
    assert len(calls) == 2
    assert all(call["validate"] is not None for call in calls)
    assert "Jean Dupont" not in result.anonymized_text


def test_malformed_response_is_an_error_not_an_empty_prediction(
    monkeypatch: pytest.MonkeyPatch,
):
    system = _system()
    calls = 0

    def complete(prompt: str, **kwargs: object) -> LlmCompletion:
        nonlocal calls
        calls += 1
        return LlmCompletion(
            content="pas du json",
            backend="qwen_local",
            model="stub",
            cached=False,
            finish_reason="stop",
            latency_ms=1.0,
        )

    monkeypatch.setattr(system._client, "complete", complete)
    doc = _doc("Jean Dupont est ici.")
    result = system.run(doc)

    assert calls == MALFORMED_RESPONSE_ATTEMPTS
    assert result.status == "error"
    assert result.anonymized_text == doc.text
    assert any("JSON invalide" in error for error in result.errors)
    assert any(
        f"après {MALFORMED_RESPONSE_ATTEMPTS} tentatives" in error
        for error in result.errors
    )


def test_unknown_category_and_missing_span_are_warnings(monkeypatch: pytest.MonkeyPatch):
    system = _system()

    def complete(prompt: str, **kwargs: object) -> LlmCompletion:
        return _stub_completion(
            [
                {"span": "Jean Dupont", "category": "NOT_A_CODE", "action": "SUPPRESS", "replacement": ""},
                {"span": "Inconnu", "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""},
            ]
        )

    monkeypatch.setattr(system._client, "complete", complete)
    doc = _doc("Jean Dupont est ici.")
    result = system.run(doc)

    assert result.status == "partial"
    assert result.annotations == ()
    assert result.anonymized_text == doc.text
    assert len(result.errors) == 2


def test_illegal_action_falls_back_to_suppress(monkeypatch: pytest.MonkeyPatch):
    system = _system()

    def complete(prompt: str, **kwargs: object) -> LlmCompletion:
        return _stub_completion(
            [
                {
                    "span": "Jean Dupont",
                    "category": "DIR_NAME",
                    "action": "GENERALIZE",
                    "replacement": "Une personne",
                }
            ]
        )

    monkeypatch.setattr(system._client, "complete", complete)
    result = system.run(_doc("Jean Dupont est ici."))

    assert result.status == "partial"
    assert result.decisions[0].action.value == "SUPPRESS"
    assert "repliée" in result.errors[0]


def test_entity_limit_is_per_window_and_explicit(monkeypatch: pytest.MonkeyPatch):
    system = _system(max_entities=1)

    def complete(prompt: str, **kwargs: object) -> LlmCompletion:
        return _stub_completion(
            [
                {"span": "Alice", "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""},
                {"span": "Bob", "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""},
            ]
        )

    monkeypatch.setattr(system._client, "complete", complete)
    result = system.run(_doc("Alice et Bob sont ici."))

    assert result.status == "partial"
    assert any("max_entities=1" in error for error in result.errors)
    assert len(result.annotations) == 1
    assert result.anonymized_text.count("SUPPRIME") == 1


def test_output_budget_is_forwarded(monkeypatch: pytest.MonkeyPatch):
    system = _system(max_output_tokens=1234)
    observed: dict[str, object] = {}

    def complete(prompt: str, **kwargs: object) -> LlmCompletion:
        observed.update(kwargs)
        return _stub_completion([])

    monkeypatch.setattr(system._client, "complete", complete)
    system.run(_doc("texte"))

    assert observed["max_tokens"] == 1234


def test_max_windows_guard_refuses_a_pathological_split(monkeypatch: pytest.MonkeyPatch):
    system = _system(window_chars=500, overlap_chars=50, max_windows=1)
    document = _filler(2000, "e")

    result = system.run(_doc(document))

    assert result.status == "error"
    assert result.anonymized_text == document
    assert any("max_windows=1" in error for error in result.errors)

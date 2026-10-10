"""Tests de ``LlmFullSystem`` — aucun test ici n'ouvre de socket.

``LlmClient.complete`` est monkeypatché pour renvoyer une réponse canned : ce
qui est testé, c'est la reconstruction déterministe (localisation des spans,
légalité des actions, application au texte), pas le modèle lui-même.
"""

from __future__ import annotations

import json

import pytest

from anonymisation.capabilities import CAP_DECISIONS, CAP_SPANS
from anonymisation.llm.client import LlmCompletion
from anonymisation.pipelines.llm_full.prompts import LlmMalformedResponseError
from anonymisation.pipelines.llm_full.system import LlmFullSystem
from anonymisation.schema.models import Document, Domain
from anonymisation.systems.base import SystemConfig


def _system() -> LlmFullSystem:
    return LlmFullSystem(SystemConfig(params={"backend": "qwen_local"}))


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


def test_identity_and_capabilities():
    system = _system()
    ident = system.identity()
    assert ident.system_id == "llm-full-v1"
    assert system.capabilities == frozenset({CAP_SPANS, CAP_DECISIONS})
    assert system.uses_policy is False
    assert system.offline_only is False


def test_same_mention_can_have_multiple_categories(monkeypatch):
    system = _system()
    monkeypatch.setattr(system._client, "complete", lambda *a, **k: _stub_completion([
        {"span": "doctorant", "category": category, "action": "SUPPRESS", "replacement": ""}
        for category in ("GEN_EDUCATION", "GEN_OCCUPATION")
    ]))
    result = system.run(_doc("Je suis doctorant."))
    assert result.status == "ok", result.errors
    assert len(result.annotations) == 2
    assert {(a.start, a.end) for a in result.annotations} == {(8, 17)}
    assert "doctorant" not in result.anonymized_text


def test_entity_limit_is_explicit_and_output_budget_forwarded(monkeypatch):
    system = LlmFullSystem(SystemConfig(params={"backend": "stub", "max_entities": 1}))
    observed = {}

    def complete(*args, **kwargs):
        observed.update(kwargs)
        return _stub_completion([
            {"span": name, "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""}
            for name in ("Alice", "Bob")
        ])

    monkeypatch.setattr(system._client, "complete", complete)
    result = system.run(_doc("Alice et Bob"))
    assert observed["max_tokens"] == 4096
    assert result.status == "partial"
    assert any("max_entities=1" in error for error in result.errors)
    assert "Alice" not in result.anonymized_text and "Bob" in result.anonymized_text


def test_happy_path_suppress_and_generalize(monkeypatch: pytest.MonkeyPatch):
    system = _system()
    doc = _doc("Jean Dupont a 28 ans et travaille a Lille.")
    monkeypatch.setattr(
        system._client,
        "complete",
        lambda *a, **k: _stub_completion(
            [
                {"span": "Jean Dupont", "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""},
                {
                    "span": "28 ans",
                    "category": "GEN_AGE",
                    "action": "GENERALIZE",
                    "replacement": "25-30 ans",
                },
            ]
        ),
    )

    result = system.run(doc)

    assert result.status == "ok"
    assert len(result.annotations) == 2
    assert len(result.decisions) == 2
    for ann in result.annotations:
        assert doc.text[ann.start : ann.end] == ann.span_text
    assert "Jean Dupont" not in result.anonymized_text
    assert "[DIR_NAME_SUPPRIME]" in result.anonymized_text
    assert "25-30 ans" in result.anonymized_text
    assert "travaille a Lille" in result.anonymized_text  # non signalé, non touché


def test_unknown_category_is_dropped_not_crashed(monkeypatch: pytest.MonkeyPatch):
    system = _system()
    doc = _doc("Jean Dupont habite ici.")
    monkeypatch.setattr(
        system._client,
        "complete",
        lambda *a, **k: _stub_completion(
            [{"span": "Jean Dupont", "category": "NOT_A_REAL_CODE", "action": "SUPPRESS", "replacement": ""}]
        ),
    )

    result = system.run(doc)

    assert result.status == "partial"
    assert result.annotations == ()
    assert result.decisions == ()
    assert result.anonymized_text == doc.text
    assert any("NOT_A_REAL_CODE" in e for e in result.errors)


def test_span_not_found_is_dropped_not_crashed(monkeypatch: pytest.MonkeyPatch):
    system = _system()
    doc = _doc("Un texte sans le nom recherché.")
    monkeypatch.setattr(
        system._client,
        "complete",
        lambda *a, **k: _stub_completion(
            [{"span": "Jean Dupont", "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""}]
        ),
    )

    result = system.run(doc)

    assert result.status == "partial"
    assert result.annotations == ()
    assert "introuvable" in result.errors[0]


def test_illegal_action_falls_back_to_suppress(monkeypatch: pytest.MonkeyPatch):
    """GENERALIZE n'est pas une action légale pour DIRECT (SPEC-01 §8) : repli SUPPRESS."""
    system = _system()
    doc = _doc("Jean Dupont est ici.")
    monkeypatch.setattr(
        system._client,
        "complete",
        lambda *a, **k: _stub_completion(
            [
                {
                    "span": "Jean Dupont",
                    "category": "DIR_NAME",
                    "action": "GENERALIZE",
                    "replacement": "Une personne",
                }
            ]
        ),
    )

    result = system.run(doc)

    assert result.status == "partial"
    assert result.decisions[0].action.value == "SUPPRESS"
    assert "repliée" in result.errors[0]


def test_empty_replacement_on_non_suppress_falls_back(monkeypatch: pytest.MonkeyPatch):
    system = _system()
    doc = _doc("Il a 28 ans.")
    monkeypatch.setattr(
        system._client,
        "complete",
        lambda *a, **k: _stub_completion(
            [{"span": "28 ans", "category": "GEN_AGE", "action": "GENERALIZE", "replacement": "   "}]
        ),
    )

    result = system.run(doc)

    assert result.decisions[0].action.value == "SUPPRESS"
    assert result.decisions[0].replacement == "[GEN_AGE_SUPPRIME]"


def test_repeated_identical_span_resolves_distinct_occurrences(monkeypatch: pytest.MonkeyPatch):
    system = _system()
    doc = _doc("Jean Dupont a appele. Jean Dupont a rappele plus tard.")
    monkeypatch.setattr(
        system._client,
        "complete",
        lambda *a, **k: _stub_completion(
            [
                {"span": "Jean Dupont", "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""},
                {"span": "Jean Dupont", "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""},
            ]
        ),
    )

    result = system.run(doc)

    assert len(result.annotations) == 2
    starts = sorted(a.start for a in result.annotations)
    assert starts[0] != starts[1]
    assert "Jean Dupont" not in result.anonymized_text


def test_malformed_llm_response_yields_error_status_never_empty_prediction(
    monkeypatch: pytest.MonkeyPatch,
):
    """Contrainte C3/C4 (SPEC-10) : une réponse inexploitable est une erreur, pas 0 entité."""
    system = _system()
    doc = _doc("Jean Dupont a 28 ans.")

    def _raise(*a, **k):
        raise LlmMalformedResponseError("JSON invalide")

    monkeypatch.setattr(system._client, "complete", lambda *a, **k: _stub_completion([]))
    # Simule une réponse non-JSON en montant directement au niveau _execute :
    monkeypatch.setattr("anonymisation.pipelines.llm_full.system.parse_llm_entities", _raise)

    result = system.run(doc)

    assert result.status == "error"
    assert result.anonymized_text == doc.text  # jamais transformé sur une erreur
    assert any("JSON invalide" in e for e in result.errors)


def test_no_entities_found_is_a_valid_ok_result(monkeypatch: pytest.MonkeyPatch):
    system = _system()
    doc = _doc("Un texte parfaitement anodin.")
    monkeypatch.setattr(system._client, "complete", lambda *a, **k: _stub_completion([]))

    result = system.run(doc)

    assert result.status == "ok"
    assert result.annotations == ()
    assert result.anonymized_text == doc.text

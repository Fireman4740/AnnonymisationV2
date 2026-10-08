"""Tests de ``anonymisation.llm.client`` — cache et contrat d'erreur C3.

Aucun test ici n'ouvre de socket : l'appel réseau effectif
(``_call_openai_compatible`` / ``_call_anthropic``) est monkeypatché.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymisation.llm.client import (
    LlmClient,
    LlmEmptyResponseError,
)
from anonymisation.llm.config import BackendSpec


def _backend(name: str = "stub") -> BackendSpec:
    return BackendSpec(
        name=name,
        kind="openai_compatible",
        base_url="http://127.0.0.1:1/v1",
        model="stub-model",
        timeout_s=1.0,
    )


def test_cache_separates_system_prompts_and_generation_parameters(tmp_path, monkeypatch):
    from dataclasses import replace

    first = LlmClient(_backend(), cache_dir=tmp_path, cache_enabled=True)
    calls = []

    def call(prompt, *, temperature, system=None):
        calls.append(system)
        return str(len(calls)), "stop"

    monkeypatch.setattr(first, "_call_openai_compatible", call)
    first.complete("p", system="s1")
    assert first.complete("p", system="s1").cached
    assert not first.complete("p", system="s2").cached
    second = LlmClient(replace(_backend(), extra_body={"seed": 42}), cache_dir=tmp_path)
    monkeypatch.setattr(second, "_call_openai_compatible", call)
    assert not second.complete("p", system="s1").cached
    assert len(calls) == 3


def test_complete_caches_identical_prompts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    client = LlmClient(_backend(), cache_dir=tmp_path / "cache", cache_enabled=True)
    calls = {"n": 0}

    def fake_call(prompt: str, *, temperature):
        calls["n"] += 1
        return f"réponse {calls['n']}", "stop"

    monkeypatch.setattr(client, "_call_openai_compatible", fake_call)

    first = client.complete("bonjour")
    second = client.complete("bonjour")

    assert calls["n"] == 1  # le second appel vient du cache
    assert first.cached is False
    assert second.cached is True
    assert first.content == second.content == "réponse 1"


def test_complete_different_prompts_are_not_conflated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    client = LlmClient(_backend(), cache_dir=tmp_path / "cache", cache_enabled=True)
    calls = {"n": 0}

    def fake_call(prompt: str, *, temperature):
        calls["n"] += 1
        return f"réponse à {prompt!r}", "stop"

    monkeypatch.setattr(client, "_call_openai_compatible", fake_call)

    client.complete("prompt A")
    client.complete("prompt B")
    assert calls["n"] == 2


def test_complete_use_cache_false_bypasses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    client = LlmClient(_backend(), cache_dir=tmp_path / "cache", cache_enabled=True)
    calls = {"n": 0}

    def fake_call(prompt: str, *, temperature):
        calls["n"] += 1
        return "réponse", "stop"

    monkeypatch.setattr(client, "_call_openai_compatible", fake_call)

    client.complete("bonjour", use_cache=False)
    client.complete("bonjour", use_cache=False)
    assert calls["n"] == 2


def test_empty_response_raises_never_treated_as_no_entities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Contrainte C3 (SPEC-10 §2) : une réponse vide DOIT lever, jamais renvoyer ''."""
    client = LlmClient(_backend(), cache_dir=tmp_path / "cache", cache_enabled=True)
    monkeypatch.setattr(client, "_call_openai_compatible", lambda prompt, *, temperature: ("", "stop"))

    with pytest.raises(LlmEmptyResponseError):
        client.complete("bonjour")


def test_truncated_response_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """finish_reason='length' DOIT lever, jamais être exploité tel quel (C3)."""
    client = LlmClient(_backend(), cache_dir=tmp_path / "cache", cache_enabled=True)
    monkeypatch.setattr(
        client, "_call_openai_compatible", lambda prompt, *, temperature: ("tronqué", "length")
    )

    with pytest.raises(LlmEmptyResponseError, match="tronquée"):
        client.complete("bonjour")


def test_empty_response_is_not_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Une erreur ne doit jamais polluer le cache — sinon un échec temporaire deviendrait permanent."""
    client = LlmClient(_backend(), cache_dir=tmp_path / "cache", cache_enabled=True)
    responses = iter([("", "stop"), ("ça marche", "stop")])
    monkeypatch.setattr(
        client, "_call_openai_compatible", lambda prompt, *, temperature: next(responses)
    )

    with pytest.raises(LlmEmptyResponseError):
        client.complete("bonjour")
    result = client.complete("bonjour")
    assert result.content == "ça marche"


def test_cache_disabled_never_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache_dir = tmp_path / "cache"
    client = LlmClient(_backend(), cache_dir=cache_dir, cache_enabled=False)
    monkeypatch.setattr(
        client, "_call_openai_compatible", lambda prompt, *, temperature: ("réponse", "stop")
    )
    client.complete("bonjour")
    assert not cache_dir.exists()

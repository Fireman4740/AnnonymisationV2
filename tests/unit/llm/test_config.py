"""Tests de ``anonymisation.llm.config`` — résolution des backends.

Aucun de ces tests n'ouvre de connexion : ``load_backends_config`` ne fait que
lire et valider du YAML.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymisation.llm.config import BackendSpec, LlmConfigError, load_backends_config


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "backends.yaml"
    path.write_text(content, encoding="utf-8")
    return path


_MINIMAL = """
default: local
backends:
  local:
    kind: openai_compatible
    base_url: "http://127.0.0.1:9/v1"
    model: "test-model"
    timeout_s: 5
    max_concurrency: 1
    temperature: 0.1
  remote:
    kind: anthropic
    model: "claude-test"
    api_key_env: "TEST_KEY_ENV_UNSET"
roles:
  detection: local
cache:
  enabled: true
  dir: "data/interim/llm_cache_test"
"""


def test_load_real_project_config_is_valid():
    """La configuration réelle du dépôt doit toujours se charger."""
    cfg = load_backends_config()
    assert cfg.default in cfg.backends
    for role, backend_key in cfg.roles.items():
        assert backend_key in cfg.backends, role


def test_ling_generation_is_bounded_and_reasoning_is_explicitly_disabled():
    backend = load_backends_config().resolve(name="openrouter_ling_3_0_flash")
    assert backend.max_output_tokens == 8192
    assert backend.extra_body["reasoning"] == {"enabled": False}
    assert backend.max_retries == 0
    with pytest.raises(LlmConfigError, match="max_output_tokens"):
        BackendSpec(name="invalid", kind="stub", max_output_tokens=0)


def test_resolve_by_explicit_name(tmp_path: Path):
    cfg = load_backends_config(_write(tmp_path, _MINIMAL))
    backend = cfg.resolve(name="remote")
    assert backend.kind == "anthropic"
    assert backend.model == "claude-test"


def test_resolve_by_role_falls_back_to_backend(tmp_path: Path):
    cfg = load_backends_config(_write(tmp_path, _MINIMAL))
    backend = cfg.resolve(role="detection")
    assert backend.name == "local"


def test_resolve_unknown_role_falls_back_to_default(tmp_path: Path):
    cfg = load_backends_config(_write(tmp_path, _MINIMAL))
    backend = cfg.resolve(role="unknown_role")
    assert backend.name == cfg.default


def test_resolve_unknown_backend_raises(tmp_path: Path):
    cfg = load_backends_config(_write(tmp_path, _MINIMAL))
    with pytest.raises(LlmConfigError, match="inconnu"):
        cfg.resolve(name="does-not-exist")


def test_missing_default_raises(tmp_path: Path):
    content = """
backends:
  local:
    kind: openai_compatible
"""
    with pytest.raises(LlmConfigError, match="default"):
        load_backends_config(_write(tmp_path, content))


def test_role_referencing_unknown_backend_raises(tmp_path: Path):
    content = """
default: local
backends:
  local:
    kind: openai_compatible
roles:
  detection: ghost
"""
    with pytest.raises(LlmConfigError, match="ghost"):
        load_backends_config(_write(tmp_path, content))


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(LlmConfigError, match="introuvable"):
        load_backends_config(tmp_path / "does-not-exist.yaml")


def test_api_key_env_missing_raises_at_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TEST_KEY_ENV_UNSET", raising=False)
    cfg = load_backends_config(_write(tmp_path, _MINIMAL))
    backend = cfg.resolve(name="remote")
    with pytest.raises(LlmConfigError, match="TEST_KEY_ENV_UNSET"):
        backend.resolve_api_key()


def test_api_key_env_present_is_returned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TEST_KEY_ENV_UNSET", "secret-value")
    cfg = load_backends_config(_write(tmp_path, _MINIMAL))
    backend = cfg.resolve(name="remote")
    assert backend.resolve_api_key() == "secret-value"


def test_api_key_cmd_reads_first_stdout_line(tmp_path: Path):
    content = """
default: local
backends:
  local:
    kind: openai_compatible
    api_key_cmd: "echo secret-from-cmd"
"""
    cfg = load_backends_config(_write(tmp_path, content))
    backend = cfg.resolve(name="local")
    assert backend.resolve_api_key() == "secret-from-cmd"

"""Chargement des backends LLM déclarés dans ``configs/llm/backends.yaml``.

Un seul fichier décrit tous les backends interchangeables (SPEC-10 §6.1) : la
clé d'API n'y est jamais écrite en clair, elle est résolue à l'exécution via
``api_key_cmd`` (commande externe, ex. lecture d'un ``.env`` sous WSL) ou
``api_key_env`` (variable d'environnement).

Ce module ne fait aucun appel réseau : il ne fait que résoudre la
configuration. Le client (``anonymisation.llm.client``) est seul responsable
des appels effectifs.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml

_DEFAULT_CONFIG_PATH: Final[Path] = (
    Path(__file__).resolve().parents[3] / "configs" / "llm" / "backends.yaml"
)


class LlmConfigError(ValueError):
    """Configuration de backend LLM absente, invalide, ou clé introuvable."""


@dataclass(frozen=True)
class HealthCheck:
    url: str | None = None
    hint: str | None = None


@dataclass(frozen=True)
class BackendSpec:
    """Un backend LLM interchangeable, tel que déclaré dans ``backends.yaml``."""

    name: str
    kind: str  # "openai_compatible" | "anthropic" | "null"
    base_url: str | None = None
    model: str | None = None
    api_key_cmd: str | None = None
    api_key_env: str | None = None
    timeout_s: float = 60.0
    max_concurrency: int = 1
    temperature: float = 0.1
    extra_body: dict[str, Any] = field(default_factory=dict)
    health: HealthCheck = field(default_factory=HealthCheck)

    def resolve_api_key(self) -> str | None:
        """Résout la clé d'API à l'exécution. Ne la met jamais en cache disque."""
        if self.api_key_env:
            import os

            value = os.environ.get(self.api_key_env)
            if not value:
                raise LlmConfigError(
                    f"Backend {self.name!r} : variable d'environnement "
                    f"{self.api_key_env!r} absente ou vide."
                )
            return value
        if self.api_key_cmd:
            try:
                proc = subprocess.run(
                    self.api_key_cmd,
                    shell=True,  # nécessaire : la commande contient des guillemets imbriqués
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise LlmConfigError(
                    f"Backend {self.name!r} : échec de api_key_cmd ({exc})."
                ) from exc
            lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
            if not lines:
                raise LlmConfigError(
                    f"Backend {self.name!r} : api_key_cmd n'a rien renvoyé sur stdout "
                    f"(code retour {proc.returncode}, stderr={proc.stderr.strip()!r})."
                )
            return lines[0]
        return None


@dataclass(frozen=True)
class CacheSpec:
    enabled: bool = True
    dir: str = "data/interim/llm_cache"


@dataclass(frozen=True)
class LlmBackendsConfig:
    default: str
    backends: dict[str, BackendSpec]
    roles: dict[str, str]
    cache: CacheSpec

    def resolve(self, name: str | None = None, *, role: str | None = None) -> BackendSpec:
        """Résout un backend par nom explicite, sinon par rôle, sinon le défaut."""
        key = name
        if key is None and role is not None:
            key = self.roles.get(role)
        if key is None:
            key = self.default
        if key not in self.backends:
            known = ", ".join(sorted(self.backends))
            raise LlmConfigError(f"Backend inconnu : {key!r}. Backends connus : {known}.")
        return self.backends[key]


def _backend_from_dict(name: str, raw: dict[str, Any]) -> BackendSpec:
    health_raw = raw.get("health") or {}
    if not isinstance(health_raw, dict):
        raise LlmConfigError(f"Backend {name!r} : 'health' doit être un mapping.")
    return BackendSpec(
        name=name,
        kind=str(raw.get("kind", "")),
        base_url=raw.get("base_url"),
        model=raw.get("model"),
        api_key_cmd=raw.get("api_key_cmd"),
        api_key_env=raw.get("api_key_env"),
        timeout_s=float(raw.get("timeout_s", 60.0)),
        max_concurrency=int(raw.get("max_concurrency", 1)),
        temperature=float(raw.get("temperature", 0.1)),
        extra_body=dict(raw.get("extra_body") or {}),
        health=HealthCheck(url=health_raw.get("url"), hint=health_raw.get("hint")),
    )


def load_backends_config(path: Path | None = None) -> LlmBackendsConfig:
    """Charge et valide ``configs/llm/backends.yaml``.

    Aucune valeur par défaut silencieuse : un champ requis absent (``default``,
    ``kind`` d'un backend référencé) fait échouer le chargement.
    """
    config_path = Path(path) if path is not None else _DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise LlmConfigError(f"Configuration LLM introuvable : {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise LlmConfigError(f"Configuration LLM invalide ({config_path}) : mapping attendu.")

    default = raw.get("default")
    if not default:
        raise LlmConfigError(f"Configuration LLM invalide ({config_path}) : 'default' manquant.")

    backends_raw = raw.get("backends")
    if not isinstance(backends_raw, dict) or not backends_raw:
        raise LlmConfigError(
            f"Configuration LLM invalide ({config_path}) : 'backends' manquant ou vide."
        )
    backends = {
        str(name): _backend_from_dict(str(name), dict(spec))
        for name, spec in backends_raw.items()
    }
    if default not in backends:
        raise LlmConfigError(
            f"Configuration LLM invalide ({config_path}) : default={default!r} "
            f"absent de backends={sorted(backends)}."
        )

    roles = {str(k): str(v) for k, v in dict(raw.get("roles") or {}).items()}
    for role, backend_key in roles.items():
        if backend_key not in backends:
            raise LlmConfigError(
                f"Configuration LLM invalide ({config_path}) : le rôle {role!r} "
                f"référence le backend inconnu {backend_key!r}."
            )

    cache_raw = raw.get("cache") or {}
    if not isinstance(cache_raw, dict):
        raise LlmConfigError(f"Configuration LLM invalide ({config_path}) : 'cache' doit être un mapping.")
    cache = CacheSpec(
        enabled=bool(cache_raw.get("enabled", True)),
        dir=str(cache_raw.get("dir", "data/interim/llm_cache")),
    )

    return LlmBackendsConfig(default=str(default), backends=backends, roles=roles, cache=cache)


__all__ = [
    "BackendSpec",
    "CacheSpec",
    "HealthCheck",
    "LlmBackendsConfig",
    "LlmConfigError",
    "load_backends_config",
]

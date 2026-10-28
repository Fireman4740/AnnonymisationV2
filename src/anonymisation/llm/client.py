"""Client LLM openai-compatible, avec cache disque obligatoire (SPEC-10 §6.2).

Contrainte **C3** (SPEC-10 §2) : une réponse vide, tronquée, ou un backend
injoignable NE DOIVENT JAMAIS être interprétés comme « aucune entité trouvée ».
Ce module ne renvoie donc que deux issues : une complétion valide et non
vide, ou une exception nommée. Rien entre les deux.

Le cache (SPEC-10 §6.2, OBLIGATOIRE) est indexé par
``sha256(backend + model + prompt + params)`` : deux appels identiques ne
recoûtent jamais un aller-retour réseau, ce qui isole les comparaisons de
politiques du bruit du LLM et rend une campagne rejouable sans GPU.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from anonymisation.llm.config import (
    BackendSpec,
    LlmBackendsConfig,
    LlmConfigError,
    load_backends_config,
)
from anonymisation.schema.io import atomic_write

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
#: Fins de génération signalant une sortie coupée par le budget de tokens.
#: OpenAI-compatible écrit ``length`` ; Anthropic écrit ``max_tokens``. N'en
#: reconnaître qu'une laisserait passer un JSON tronqué comme réponse valide (C3).
_TRUNCATION_REASONS: Final[frozenset[str]] = frozenset({"length", "max_tokens"})


class _ProviderDefault:
    """Marqueur : ne PAS envoyer de température (défaut du fournisseur).

    Certains protocoles originaux n'en fixent aucune (attaquant RAT-Bench) ;
    imposer celle du backend changerait l'attaquant. Explicite, jamais implicite.
    """

    def __repr__(self) -> str:
        return "PROVIDER_DEFAULT"


PROVIDER_DEFAULT: Final = _ProviderDefault()


class LlmError(RuntimeError):
    """Racine des erreurs LLM. Ne représente jamais un résultat vide valide."""


class LlmBackendUnavailableError(LlmError):
    """Le backend n'a pas répondu (connexion refusée, timeout, HTTP d'erreur)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        # Un routage absent (404), une clé invalide ou un crédit manquant
        # ne se réparent pas en répétant la même requête.
        self.retryable = (status_code is None or status_code in (408, 409, 429)
                          or 500 <= status_code < 600)


class LlmEmptyResponseError(LlmError):
    """Réponse vide ou tronquée (``finish_reason='length'``) — jamais « aucune entité »."""


@dataclass(frozen=True)
class LlmCompletion:
    content: str
    backend: str
    model: str
    cached: bool
    finish_reason: str | None
    latency_ms: float


def _cache_key(backend: BackendSpec, prompt: str, params: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "backend": backend.name,
            "model": backend.model,
            "prompt": prompt,
            "params": params,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LlmClient:
    """Client synchrone, un backend résolu par instance.

    Instancier via :meth:`for_role` ou :meth:`for_backend` plutôt que
    directement : la résolution de la clé d'API et du SDK sous-jacent
    n'a lieu qu'à la construction, jamais implicitement à chaque appel.
    """

    def __init__(
        self,
        backend: BackendSpec,
        *,
        cache_dir: Path | None = None,
        cache_enabled: bool = True,
    ) -> None:
        if backend.kind == "null":
            raise LlmConfigError(
                f"Backend {backend.name!r} : kind='null' ne peut pas servir de "
                "client (backend de repli pour l'exécution sans LLM, jamais "
                "appelé)."
            )
        if backend.kind not in ("openai_compatible", "anthropic", "stub"):
            raise LlmConfigError(
                f"Backend {backend.name!r} : kind={backend.kind!r} non supporté "
                "(valeurs : 'openai_compatible' | 'anthropic' | 'stub')."
            )
        self._backend = backend
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._cache_enabled = cache_enabled
        self._sdk_client: Any = None  # construit paresseusement, au premier appel réel

    @classmethod
    def for_backend(
        cls,
        name: str,
        *,
        config: LlmBackendsConfig | None = None,
        config_path: Path | None = None,
    ) -> LlmClient:
        cfg = config or load_backends_config(config_path)
        backend = cfg.resolve(name=name)
        return cls(
            backend,
            cache_dir=(Path(os.environ.get("ANONV2_LLM_CACHE_DIR", str(_REPO_ROOT / cfg.cache.dir)))
                       if cfg.cache.enabled else None),
            cache_enabled=cfg.cache.enabled,
        )

    @classmethod
    def for_role(
        cls,
        role: str,
        *,
        config: LlmBackendsConfig | None = None,
        config_path: Path | None = None,
    ) -> LlmClient:
        cfg = config or load_backends_config(config_path)
        backend = cfg.resolve(role=role)
        return cls(
            backend,
            cache_dir=(Path(os.environ.get("ANONV2_LLM_CACHE_DIR", str(_REPO_ROOT / cfg.cache.dir)))
                       if cfg.cache.enabled else None),
            cache_enabled=cfg.cache.enabled,
        )

    @property
    def backend(self) -> BackendSpec:
        return self._backend

    # --- cache ------------------------------------------------------------ #
    def _cache_path(self, key: str) -> Path:
        assert self._cache_dir is not None
        return self._cache_dir / key[:2] / f"{key}.json"

    def _read_cache(self, key: str) -> dict[str, Any] | None:
        if self._cache_dir is None:
            return None
        path = self._cache_path(key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None  # cache corrompu : on retombe sur un appel réel

    def _write_cache(self, key: str, record: dict[str, Any]) -> None:
        if self._cache_dir is None:
            return
        path = self._cache_path(key)
        with atomic_write(path) as fh:
            json.dump(record, fh, ensure_ascii=False, sort_keys=True, indent=2)
            fh.write("\n")

    # --- appel effectif ----------------------------------------------------#
    def _ensure_sdk_client(self) -> Any:
        if self._sdk_client is not None:
            return self._sdk_client
        backend = self._backend
        if backend.kind == "openai_compatible":
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - dépendance optionnelle
                raise LlmConfigError(
                    "Le paquet 'openai' est requis pour les backends "
                    "'openai_compatible' (pip install anonymisation[llm])."
                ) from exc
            api_key = backend.resolve_api_key() or "unused"
            self._sdk_client = OpenAI(
                base_url=backend.base_url,
                api_key=api_key,
                timeout=backend.timeout_s,
                max_retries=backend.max_retries,
            )
            return self._sdk_client
        if backend.kind == "anthropic":
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - dépendance optionnelle
                raise LlmConfigError(
                    "Le paquet 'anthropic' est requis pour les backends "
                    "'anthropic' (pip install anonymisation[llm-anthropic])."
                ) from exc
            api_key = backend.resolve_api_key()
            if not api_key:
                raise LlmConfigError(
                    f"Backend {backend.name!r} : aucune clé d'API résolue."
                )
            self._sdk_client = anthropic.Anthropic(api_key=api_key, timeout=backend.timeout_s)
            return self._sdk_client
        raise LlmConfigError(f"Backend {backend.name!r} : kind={backend.kind!r} non supporté.")

    def _call_openai_compatible(
        self, prompt: str, *, temperature: float | None, system: str | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, str | None]:
        backend = self._backend
        client = self._ensure_sdk_client()
        messages = [{"role": "user", "content": prompt}]
        if system is not None:
            messages.insert(0, {"role": "system", "content": system})
        sampling: dict[str, Any] = {} if temperature is PROVIDER_DEFAULT else {
            "temperature": temperature if temperature is not None else backend.temperature
        }
        try:
            response = client.chat.completions.create(
                model=backend.model,
                messages=messages,
                extra_body=dict(backend.extra_body) or None,
                **sampling,
                **({"max_tokens": max_tokens} if max_tokens is not None else {}),
            )
        except Exception as exc:  # noqa: BLE001 — toute panne réseau devient LlmBackendUnavailableError
            hint = f" {backend.health.hint}" if backend.health.hint else ""
            raise LlmBackendUnavailableError(
                f"Backend {backend.name!r} injoignable : {type(exc).__name__}: {exc}.{hint}",
                status_code=getattr(exc, "status_code", None),
            ) from exc
        if not response.choices:
            raise LlmEmptyResponseError(
                f"Backend {backend.name!r} : aucune complétion renvoyée (choices=[])."
            )
        choice = response.choices[0]
        content = choice.message.content or ""
        return content, choice.finish_reason

    def _call_anthropic(
        self, prompt: str, *, temperature: float | None, system: str | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, str | None]:
        backend = self._backend
        client = self._ensure_sdk_client()
        extra = {"system": system} if system is not None else {}
        if temperature is not PROVIDER_DEFAULT:
            extra["temperature"] = temperature if temperature is not None else backend.temperature
        try:
            response = client.messages.create(
                model=backend.model,
                max_tokens=max_tokens if max_tokens is not None else 4096,
                messages=[{"role": "user", "content": prompt}],
                **extra,
            )
        except Exception as exc:  # noqa: BLE001
            raise LlmBackendUnavailableError(
                f"Backend {backend.name!r} injoignable : {type(exc).__name__}: {exc}.",
                status_code=getattr(exc, "status_code", None),
            ) from exc
        text_blocks = [block.text for block in response.content if getattr(block, "type", None) == "text"]
        content = "".join(text_blocks)
        return content, getattr(response, "stop_reason", None)

    def _call_stub(self, prompt: str, *, temperature: float | None) -> tuple[str, str | None]:
        """Backend factice, sans réseau : réponse canned pour les tests.

        Réservé au contrat de système inter-architectures
        (``tests/unit/test_system_contract.py``) qui exécute TOUT système
        enregistré sur un corpus réel : un système LLM ne peut pas satisfaire
        ce contrat sans backend, et ne doit pas ouvrir de socket en test
        unitaire. Jamais référencé par un profil de production
        (aucun ``pipelines/*/profile.yaml`` n'y pointe).
        """
        content = str(self._backend.extra_body.get("stub_response", '{"entities": []}'))
        return content, "stop"

    def complete(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        use_cache: bool = True,
        system: str | None = None,
        max_tokens: int | None = None,
        validate: Callable[[str], object] | None = None,
    ) -> LlmCompletion:
        """Complète ``prompt``. Lève plutôt que de renvoyer un résultat ambigu.

        Une réponse vide ou tronquée (``finish_reason == 'length'``) lève
        :class:`LlmEmptyResponseError` — jamais interprétée comme « le
        document ne contient aucune entité » (contrainte C3).

        ``validate`` (optionnel) contrôle le contenu avant lecture et écriture
        du cache ; il doit lever ``ValueError`` pour un contenu invalide. Une
        entrée de cache invalide est supprimée puis remplacée par un appel
        réel : un JSON malformé ne devient jamais une réponse cachée permanente.
        """
        backend = self._backend
        if max_tokens is None:
            max_tokens = backend.max_output_tokens
        if max_tokens is not None and max_tokens < 1:
            raise LlmConfigError("max_tokens doit être strictement positif")
        params: dict[str, Any] = {
            "temperature": (
                "provider-default" if temperature is PROVIDER_DEFAULT
                else temperature if temperature is not None else backend.temperature
            )
        }
        if backend.extra_body:
            params["extra_body"] = dict(backend.extra_body)
        # Le message système n'entre dans la clé que s'il est fourni : les
        # entrées de cache existantes (sans système) restent valides.
        if system is not None:
            params["system"] = system
        system_kw: dict[str, Any] = {"system": system} if system is not None else {}
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
            system_kw["max_tokens"] = max_tokens
        key = _cache_key(backend, prompt, params)

        if use_cache and self._cache_enabled:
            cached = self._read_cache(key)
            if cached is not None:
                valid_cached = True
                if validate is not None:
                    try:
                        validate(cached["content"])
                    except ValueError:
                        # Entrée écrite avant l'ajout du validateur, ou
                        # devenue invalide : on la retire et on rappelle le
                        # backend au lieu de la resservir.
                        valid_cached = False
                        self._cache_path(key).unlink(missing_ok=True)
                if valid_cached:
                    return LlmCompletion(
                        content=cached["content"],
                        backend=backend.name,
                        model=str(backend.model),
                        cached=True,
                        finish_reason=cached.get("finish_reason"),
                        latency_ms=0.0,
                    )

        started = time.perf_counter()
        if backend.kind == "openai_compatible":
            content, finish_reason = self._call_openai_compatible(
                prompt, temperature=temperature, **system_kw
            )
        elif backend.kind == "anthropic":
            content, finish_reason = self._call_anthropic(
                prompt, temperature=temperature, **system_kw
            )
        elif backend.kind == "stub":
            content, finish_reason = self._call_stub(prompt, temperature=temperature)
        else:  # pragma: no cover — déjà rejeté à la construction pour 'null'
            raise LlmConfigError(f"Backend {backend.name!r} : kind={backend.kind!r} non supporté.")
        latency_ms = (time.perf_counter() - started) * 1000.0

        if not content.strip():
            raise LlmEmptyResponseError(
                f"Backend {backend.name!r} : réponse vide pour le prompt fourni "
                f"(finish_reason={finish_reason!r}). Ce n'est jamais interprété comme "
                "« aucune entité trouvée » (SPEC-10 C3)."
            )
        if finish_reason in _TRUNCATION_REASONS:
            raise LlmEmptyResponseError(
                f"Backend {backend.name!r} : réponse tronquée (finish_reason={finish_reason!r}). "
                "Augmenter max_tokens ou réduire le document plutôt que d'exploiter "
                "une sortie incomplète."
            )
        if validate is not None:
            validate(content)

        if use_cache and self._cache_enabled:
            self._write_cache(
                key,
                {
                    "backend": backend.name,
                    "model": backend.model,
                    "prompt": prompt,
                    "params": params,
                    "content": content,
                    "finish_reason": finish_reason,
                },
            )

        return LlmCompletion(
            content=content,
            backend=backend.name,
            model=str(backend.model),
            cached=False,
            finish_reason=finish_reason,
            latency_ms=latency_ms,
        )


__all__ = [
    "PROVIDER_DEFAULT",
    "LlmBackendUnavailableError",
    "LlmClient",
    "LlmCompletion",
    "LlmEmptyResponseError",
    "LlmError",
]

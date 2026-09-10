"""Infrastructure LLM **partagée** : client, backends, cache (SPEC-10 §6).

Ce qui est ici est mutualisable entre architectures : la connexion à un
backend, la résolution de la clé d'API, le cache disque obligatoire. Ce qui
est propre à une architecture — son prompt, son parseur de réponse — vit dans
son dossier de pipeline (ex. ``pipelines/llm_full/prompts.py``).

N'est jamais importé par ``metrics`` ni par ``cli/score.py`` (SPEC-10 C5 : le
scoring ne relance aucun modèle).
"""

from anonymisation.llm.client import (
    LlmBackendUnavailableError,
    LlmClient,
    LlmCompletion,
    LlmEmptyResponseError,
    LlmError,
)
from anonymisation.llm.config import (
    BackendSpec,
    LlmBackendsConfig,
    LlmConfigError,
    load_backends_config,
)

__all__ = [
    "BackendSpec",
    "LlmBackendUnavailableError",
    "LlmBackendsConfig",
    "LlmClient",
    "LlmCompletion",
    "LlmConfigError",
    "LlmEmptyResponseError",
    "LlmError",
    "load_backends_config",
]

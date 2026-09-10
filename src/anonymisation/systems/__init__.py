"""Contrat des systèmes d'anonymisation évaluables (SPEC-10).

Ce paquet définit **le contrat** — ``SystemBase``, ``SystemConfig``,
l'identité, le registre — et ne contient **aucune implémentation**. Les
implémentations vivent dans ``anonymisation.pipelines/<nom>/``, un dossier
autonome par architecture (code, profil, tests, notice).

L'import de ``anonymisation.pipelines`` ci-dessous déclenche l'enregistrement
des pipelines livrés. Il est placé **après** les imports du contrat : les
pipelines importent ``systems.base`` et ``systems.registry``, qui doivent donc
être résolus d'abord.

⚠️ Ce paquet importe les pipelines, donc ``detect/`` et ``llm/``. Il ne doit
donc **jamais** être importé par ``metrics/`` ni par ``cli/score.py`` — le
scoring doit rester hors ligne et sans modèle (SPEC-10 C5). Le vocabulaire
partagé avec les métriques vit dans ``anonymisation.capabilities``, qui
n'importe rien.
"""

from anonymisation.systems.base import (
    ModelRef,
    SystemBase,
    SystemConfig,
    SystemContractError,
    SystemDescriptor,
    SystemIdentity,
    TextRewriteSystem,
    params_digest,
)
from anonymisation.systems.registry import (
    ALIASES,
    SYSTEM_REGISTRY,
    UnknownSystemError,
    list_systems,
    register_system,
    resolve_system,
)

# --- Enregistrement des pipelines livrés (import explicite) ----------------- #
from anonymisation import pipelines as _pipelines  # noqa: F401,E402

__all__ = [
    "ALIASES",
    "SYSTEM_REGISTRY",
    "ModelRef",
    "SystemBase",
    "SystemConfig",
    "SystemContractError",
    "SystemDescriptor",
    "SystemIdentity",
    "TextRewriteSystem",
    "UnknownSystemError",
    "list_systems",
    "params_digest",
    "register_system",
    "resolve_system",
]

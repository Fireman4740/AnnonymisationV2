"""Chargement des profils d'exécution (``configs/runtime/*.yaml``, SPEC-10 §8-9).

Un profil est l'unique source de configuration du pipeline : détecteurs
activés, stratégie de fusion, estimateur de risque, politique, pseudonymisation,
contrôles de validation, LLM, budgets et déterminisme. Le chargement est
strict : tout champ inconnu ou toute valeur hors domaine lève
:class:`ProfileError` (pas de dérive silencieuse entre la config et le code).

Le profil ``deterministic`` (SPEC-10 §9) ne doit activer ni NER ni LLM ; si le
fichier le déclare, le chargement échoue. Les références relatives (fichiers
de patterns, de politiques) sont résolues par l'orchestrateur : d'abord
relativement au répertoire du profil, puis relativement à la racine du dépôt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, Field

from anonymisation.detect.fusion import STRATEGIES

logger = logging.getLogger(__name__)

#: Émetteurs LLM non implantés en v1 (audit §12.3) — cités dans les messages
#: d'erreur pour orienter l'utilisateur.
_LLM_STAGES: Final[tuple[str, ...]] = ("detect.llm_reviewer", "audit", "rewrite")

#: Méthodes de fusion autorisées (référencées par ``stages.fuse.strategy``).
FUSE_STRATEGIES: Final[tuple[str, ...]] = STRATEGIES


class ProfileError(ValueError):
    """Profil d'exécution invalide (champs inconnus, valeurs hors domaine)."""


def _base_config() -> ConfigDict:
    return ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- #
# Blocs du profil
# --------------------------------------------------------------------------- #
class DeterministicDetectSpec(BaseModel):
    """Détecteur déterministe : patterns + règles (la seule source v1)."""

    model_config = _base_config()

    enabled: bool
    patterns: str
    min_confidence: float = Field(gt=0.0, le=1.0)


class NneSpec(BaseModel):
    """Détecteur NER — non implémenté en v1 (le profil doit le laisser off)."""

    model_config = _base_config()

    enabled: bool = False


class LlmReviewerSpec(BaseModel):
    """Relecteur LLM de la détection — non implémenté en v1."""

    model_config = _base_config()

    enabled: bool = False


class DetectSpec(BaseModel):
    """Étape 1 — DÉTECT (SPEC-10 §3)."""

    model_config = _base_config()

    enabled: bool = True
    deterministic: DeterministicDetectSpec
    ner: NneSpec = NneSpec()
    llm_reviewer: LlmReviewerSpec = LlmReviewerSpec()


class FuseSpec(BaseModel):
    """Étape 2 — FUSE (SPEC-10 §3)."""

    model_config = _base_config()

    enabled: bool = True
    strategy: str
    keep_multilabel_overlap: bool = True

    @property
    def is_valid(self) -> bool:
        return self.strategy in FUSE_STRATEGIES


class AssessSpec(BaseModel):
    """Étape 3 — ASSESS (SPEC-10 §3)."""

    model_config = _base_config()

    enabled: bool = True
    estimator: str
    risk_model: str = "prosecutor"
    population_id: str | None = None
    use_upper_bound: bool = True


class PlanSpec(BaseModel):
    """Étape 4 — PLAN (SPEC-10 §3)."""

    model_config = _base_config()

    enabled: bool = True
    policy_set: str
    policy: str


class PseudonymizationSpec(BaseModel):
    """Pseudonymisation : le secret est lu dans une variable d'environnement
    et n'est jamais écrit sur disque (SPEC-10 §9)."""

    model_config = _base_config()

    secret_env: str
    scope: str
    length: int = Field(ge=4, le=32)


class MaskingSpec(BaseModel):
    """Mode de masquage : ``full`` (placeholder ``[CAT]``) ou ``partial``
    (le mode partiel laisse des infos résiduelles : choix explicite)."""

    model_config = _base_config()

    mode: str

    @property
    def is_valid(self) -> bool:
        return self.mode in ("full", "partial")


class TransformSpec(BaseModel):
    """Étape 5 — TRANSFORM (SPEC-10 §3)."""

    model_config = _base_config()

    enabled: bool = True
    pseudonymization: PseudonymizationSpec
    masking: MaskingSpec


class ValidateSpec(BaseModel):
    """Étape 6 — VALIDATE (SPEC-10 §3) : contrôles hors-ligne, sans LLM.

    ``fail_on_leak`` : ``true`` interromp le document concerné (statut
    ``error``) ; ``false`` (défaut) le marque (statut ``partial``) sans
    interrompre l'exécution.
    """

    model_config = _base_config()

    enabled: bool = True
    check_placeholders: bool = True
    check_forbidden_patterns: bool = True
    check_gold_leakage: bool = True
    fail_on_leak: bool = False


class AuditSpec(BaseModel):
    """Étape 7 — AUDIT (LLM, non implémentée en v1 : doit rester off)."""

    model_config = _base_config()

    enabled: bool = False


class RewriteSpec(BaseModel):
    """Étape 8 — REWRITE (LLM, non implémentée en v1 : doit rester off)."""

    model_config = _base_config()

    enabled: bool = False


class StagesSpec(BaseModel):
    model_config = _base_config()

    detect: DetectSpec
    fuse: FuseSpec
    assess: AssessSpec
    plan: PlanSpec
    transform: TransformSpec
    validation: ValidateSpec = Field(validation_alias="validate")
    audit: AuditSpec = AuditSpec()
    rewrite: RewriteSpec = RewriteSpec()


class LlmSpec(BaseModel):
    """Politique LLM globale (SPEC-10 §8) : local par défaut, distant interdit."""

    model_config = _base_config()

    mode: str = "local"
    allow_remote: bool = False

    @property
    def is_valid(self) -> bool:
        return self.mode in ("local", "external")


class BudgetsSpec(BaseModel):
    model_config = _base_config()

    per_document_timeout_s: float = Field(default=30.0, gt=0.0)
    max_document_chars: int = Field(default=200_000, gt=0)
    max_calls_per_document: int = Field(default=3, gt=0)


class DeterminismSpec(BaseModel):
    """Bloquage du non-déterminisme (SPEC-10 §9) : seed figé, et en ``strict``
    les champs non déterministes (durées) sont nuls dans les fichiers émis."""

    model_config = _base_config()

    seed: int
    strict: bool = False


class OutputSpec(BaseModel):
    model_config = _base_config()

    root: str = "runs"
    write_traces: bool = True
    write_decisions: bool = True


class RuntimeProfile(BaseModel):
    """Profil d'exécution complet (SPEC-10 §8)."""

    model_config = _base_config()

    profile: str
    schema_version: str
    stages: StagesSpec
    llm: LlmSpec = LlmSpec()
    budgets: BudgetsSpec = Field(default_factory=BudgetsSpec)
    determinism: DeterminismSpec = Field(default_factory=lambda: DeterminismSpec(seed=42))
    output: OutputSpec = OutputSpec()


@dataclass(frozen=True)
class LoadedProfile:
    """Profil chargé + chemin du fichier (pour la résolution des références)."""

    profile: RuntimeProfile
    config_path: Path


def _repo_root(start: Path) -> Path | None:
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


def load_runtime_profile(source: str | Path) -> LoadedProfile:
    """Charge un profil d'exécution.

    ``source`` est soit un chemin vers un fichier YAML, soit le *nom* d'un
    profil livré (``"deterministic"`` → ``configs/runtime/<nom>.yaml`` de la
    racine du dépôt).
    """
    path = Path(source)
    if not path.is_file():
        root = _repo_root(Path.cwd())
        if root is None:
            raise ProfileError(
                f"Profil introuvable : {source!r} — ni fichier existant, ni profil "
                "livré (pas de racine de dépôt détectable non plus)."
            )
        path = root / "configs" / "runtime" / f"{source}.yaml"
        if not path.is_file():
            raise ProfileError(f"Profil introuvable : {source!r} (essayé {path}).")

    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ProfileError(f"Profil invalide ({path}) : attendu un mapping YAML.")

    try:
        profile = RuntimeProfile.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError et consorts
        raise ProfileError(f"Profil invalide ({path}) :\n{exc}") from exc

    stages = profile.stages
    if stages.fuse.strategy not in FUSE_STRATEGIES:
        raise ProfileError(
            f"Profil invalide ({path}) : stages.fuse.strategy={stages.fuse.strategy!r} "
            f"hors des stratégies {FUSE_STRATEGIES}."
        )
    if not stages.transform.masking.is_valid:
        raise ProfileError(
            f"Profil invalide ({path}) : stages.transform.masking.mode="
            f"{stages.transform.masking.mode!r} (valeurs : 'full' | 'partial')."
        )
    if not profile.llm.is_valid:
        raise ProfileError(
            f"Profil invalide ({path}) : llm.mode={profile.llm.mode!r} "
            "(valeurs : 'local' | 'external')."
        )

    # SPEC-10 §9 : le profil « deterministic » ne doit activer ni NER ni LLM.
    if profile.profile == "deterministic":
        forbidden: list[str] = []
        if stages.detect.ner.enabled:
            forbidden.append("stages.detect.ner")
        if stages.detect.llm_reviewer.enabled:
            forbidden.append("stages.detect.llm_reviewer")
        if stages.audit.enabled:
            forbidden.append("stages.audit")
        if stages.rewrite.enabled:
            forbidden.append("stages.rewrite")
        if profile.llm.allow_remote:
            forbidden.append("llm.allow_remote")
        if forbidden:
            raise ProfileError(
                f"Profil « deterministic » invalide ({path}) : activer "
                f"{', '.join(forbidden)} est interdit — le profil déterministe "
                "doit tourner sans NER ni LLM (SPEC-10 §9, audit C1)."
            )
    # Le loader est appelé une fois par run, avant la boucle des documents :
    # l'avertissement ne se répète donc pas pour chaque document.
    if stages.assess.estimator == "naive":
        logger.warning(
            "Profil %r : assess.estimator='naive' produit des risques PROXY "
            "non publiables comme métriques OFFICIAL.",
            profile.profile,
        )

    return LoadedProfile(profile=profile, config_path=path)

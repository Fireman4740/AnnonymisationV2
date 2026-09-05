"""Contrat des systèmes d'anonymisation évaluables (SPEC-10).

Un **système** est l'unité enregistrable et évaluable du projet : tout ce qui
transforme un document du pivot en texte anonymisé et peut passer par
``anonv2 predict`` puis ``anonv2 score``. Le mot reprend celui du champ
``scorecard["system"]``.

Deux niveaux de contrat, et **un seul type de retour** :

* le contrat **minimal** — :class:`SystemBase` — que respecte tout système, y
  compris une boîte noire qui ne fait que réécrire du texte ;
* le contrat **riche**, exprimé non par un type distinct mais par les
  *capacités* déclarées (``anonymisation.capabilities``). Un pipeline qui
  produit des spans déclare ``CAP_SPANS`` et devient évaluable sur l'axe A.

Pourquoi un seul type de retour (``PipelineResult``) plutôt qu'un type
minimal séparé : le harnais ne doit jamais brancher sur le *type* d'un
résultat, uniquement sur les capacités déclarées. ``serialize_pipeline_result``
accepte déjà ``annotations=()``, ``decisions=()``, ``risk=None`` — une boîte
noire produit une ligne de ``predictions.jsonl`` parfaitement valide.
"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, final

from pydantic import BaseModel

from anonymisation.capabilities import (
    CAP_DECISIONS,
    CAP_RISK,
    CAP_SPANS,
    CAP_TRACES,
    assert_known,
    sorted_capabilities,
)
from anonymisation.pipeline.traces import PipelineResult
from anonymisation.schema.models import Annotation, Document


class SystemError_(Exception):
    """Erreur de construction ou de configuration d'un système."""


class SystemContractError(SystemError_):
    """Un système a violé son propre contrat de capacités."""


# --------------------------------------------------------------------------- #
# Identité
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ModelRef:
    """Modèle utilisé par un système, pour le bloc ``models`` du lock."""

    name: str
    revision: str = "unknown"
    quantization: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "revision": self.revision,
            "quantization": self.quantization,
        }


@dataclass(frozen=True)
class SystemIdentity:
    """Identité figée d'un système, écrite dans le lock et chaque prédiction.

    ``params_digest`` distingue deux exécutions du **même** système paramétré
    différemment : sans lui, deux runs incomparables porteraient le même nom.
    """

    system_id: str
    system_version: str
    capabilities: frozenset[str]
    params_digest: str
    oracle: bool = False

    def to_dict(self) -> dict[str, Any]:
        # Les capacités sont TRIÉES : un frozenset n'a pas d'ordre stable entre
        # exécutions, et la sérialisation doit rester bit-à-bit reproductible.
        return {
            "system_id": self.system_id,
            "system_version": self.system_version,
            "capabilities": list(sorted_capabilities(self.capabilities)),
            "params_digest": self.params_digest,
            "oracle": self.oracle,
        }

    def has(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True)
class SystemDescriptor:
    """Ce qu'un système déclare de lui-même, pour le lock et ``systems list``."""

    identity: SystemIdentity
    summary: str
    models: tuple[ModelRef, ...] = ()
    prompts: tuple[str, ...] = ()
    offline_only: bool = True
    uses_policy: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity.to_dict()
        payload.update(
            {
                "summary": self.summary,
                "models": [model.to_dict() for model in self.models],
                "prompts": list(self.prompts),
                "offline_only": self.offline_only,
                "uses_policy": self.uses_policy,
            }
        )
        return payload


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SystemConfig:
    """Tout ce dont un système a besoin pour se construire.

    ``params`` est **opaque ici** : il est validé par la ``Params`` du système
    propriétaire, un modèle Pydantic strict. C'est le patron déjà retenu pour
    les corpus (le manifeste est générique, la résolution vit dans
    l'adaptateur) : la validation est déplacée chez le propriétaire, jamais
    relâchée.
    """

    params: Mapping[str, Any] = field(default_factory=dict)
    policy_id: str | None = None
    profile: Any = None
    config_path: Path | None = None
    repo_root: Path | None = None


def params_digest(params: Mapping[str, Any]) -> str:
    """Empreinte canonique et déterministe d'un jeu de paramètres."""
    payload = json.dumps(dict(params), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Contrat
# --------------------------------------------------------------------------- #
class SystemBase(ABC):
    """Classe de base de tout système évaluable.

    ``run`` est **final** : elle garantit uniformément les invariants qu'on ne
    peut pas déléguer à la bonne volonté de chaque auteur — capture des
    exceptions en ``status="error"`` nommé, estampillage de l'identité, et
    contrôle de cohérence entre ce qui est produit et ce qui est déclaré.

    Une implémentation n'écrit que :func:`_execute`.
    """

    #: Clé de registre. Suffixe de version **obligatoire** : changer
    #: l'algorithme sans changer la clé rendrait deux runs incomparables sous
    #: le même nom.
    system_id: ClassVar[str]
    system_version: ClassVar[str] = "1"
    capabilities: ClassVar[frozenset[str]] = frozenset()
    aliases: ClassVar[tuple[str, ...]] = ()
    offline_only: ClassVar[bool] = True
    uses_policy: ClassVar[bool] = False
    oracle: ClassVar[bool] = False
    summary: ClassVar[str] = ""
    #: Modèle Pydantic strict des paramètres propres au système.
    Params: ClassVar[type[BaseModel] | None] = None

    def __init__(self, config: SystemConfig | None = None) -> None:
        self.config = config or SystemConfig()
        assert_known(self.capabilities, owner=self.system_id)
        self._params = self._validate_params(self.config.params)
        if self.config.policy_id is not None and not self.uses_policy:
            raise SystemError_(
                f"Système {self.system_id!r} : une politique "
                f"({self.config.policy_id!r}) a été fournie alors que ce système "
                f"n'en consomme pas. Retirez --policy, ou choisissez un système "
                f"qui déclare uses_policy."
            )

    # --- construction ----------------------------------------------------- #
    def _validate_params(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        """Valide ``params`` avec le modèle strict du système."""
        if self.Params is None:
            if raw:
                raise SystemError_(
                    f"Système {self.system_id!r} : paramètres fournis {sorted(raw)} "
                    f"alors que ce système n'en accepte aucun."
                )
            return {}
        model = self.Params.model_validate(dict(raw))
        return model.model_dump(mode="json")

    @classmethod
    def from_config(cls, config: SystemConfig) -> SystemBase:
        return cls(config)

    # --- identité --------------------------------------------------------- #
    def identity(self) -> SystemIdentity:
        return SystemIdentity(
            system_id=self.system_id,
            system_version=self.system_version,
            capabilities=self.capabilities,
            params_digest=params_digest(self._params),
            oracle=self.oracle,
        )

    def describe(self) -> SystemDescriptor:
        return SystemDescriptor(
            identity=self.identity(),
            summary=self.summary or self.__doc__ or self.system_id,
            models=self.models(),
            prompts=self.prompts(),
            offline_only=self.offline_only,
            uses_policy=self.uses_policy,
        )

    def models(self) -> tuple[ModelRef, ...]:
        return ()

    def prompts(self) -> tuple[str, ...]:
        return ()

    # --- exécution -------------------------------------------------------- #
    @final
    def run(
        self,
        doc: Document,
        gold_annotations: Sequence[Annotation] | None = None,
    ) -> PipelineResult:
        """Exécute le système sur un document. **Ne lève jamais.**

        Une panne devient ``status="error"`` avec un message préfixé du nom du
        système : un document en erreur est exclu du scoring et compté à part,
        jamais confondu avec une prédiction vide (SPEC-10 §2, contrainte C4).
        """
        started = time.perf_counter()
        try:
            result = self._execute(doc, tuple(gold_annotations or ()))
        except Exception as exc:  # noqa: BLE001 — toute panne devient un statut
            elapsed = (time.perf_counter() - started) * 1000.0
            return PipelineResult(
                doc_id=doc.doc_id,
                original_text=doc.text,
                anonymized_text=doc.text,
                annotations=(),
                decisions=(),
                risk=None,
                policy_id=self.config.policy_id or "",
                traces=(),
                status="error",
                errors=(f"{self.system_id.upper()}: {type(exc).__name__}: {exc}",),
                runtime_ms=elapsed,
                identity=self.identity(),
            )
        self._assert_declares_what_it_produces(result)
        if result.identity is None:
            result = replace_identity(result, self.identity())
        return result

    @abstractmethod
    def _execute(
        self,
        doc: Document,
        gold: tuple[Annotation, ...],
    ) -> PipelineResult:
        """Corps du système. Peut lever : ``run`` convertit en statut d'erreur."""

    # --- garde de cohérence ------------------------------------------------ #
    def _assert_declares_what_it_produces(self, result: PipelineResult) -> None:
        """Un système ne doit pas produire ce qu'il ne déclare pas.

        Sans cette garde, un système pourrait émettre des annotations sans
        déclarer ``CAP_SPANS`` : le scorer les ignorerait silencieusement et
        publierait un ``UNAVAILABLE`` mensonger.
        """
        produced: list[tuple[str, str]] = []
        if result.annotations and CAP_SPANS not in self.capabilities:
            produced.append(("annotations", CAP_SPANS))
        if result.decisions and CAP_DECISIONS not in self.capabilities:
            produced.append(("decisions", CAP_DECISIONS))
        if result.traces and CAP_TRACES not in self.capabilities:
            produced.append(("traces", CAP_TRACES))
        if result.risk is not None and CAP_RISK not in self.capabilities:
            produced.append(("risk", CAP_RISK))
        if produced:
            details = ", ".join(f"{what} sans {cap!r}" for what, cap in produced)
            raise SystemContractError(
                f"Système {self.system_id!r} : produit {details}. "
                f"Déclarez la capacité, ou cessez de produire cette sortie."
            )


def replace_identity(result: PipelineResult, identity: SystemIdentity) -> PipelineResult:
    """Estampille un résultat existant (``PipelineResult`` est immuable)."""
    from dataclasses import replace

    return replace(result, identity=identity)


# --------------------------------------------------------------------------- #
# Ergonomie boîte noire
# --------------------------------------------------------------------------- #
class TextRewriteSystem(SystemBase):
    """Boîte noire : texte entrant → texte anonymisé. Une seule méthode à écrire.

    C'est le point d'accroche prévu pour un réécriveur LLM ou une commande
    externe : le système ne prétend ni détecter, ni expliquer, ni estimer un
    risque. Il reste évaluable sur les axes qui ne dépendent d'aucune capacité
    — fuite gold, TRIR, utilité — et le scorer marque les autres
    ``UNAVAILABLE`` plutôt que zéro.
    """

    capabilities: ClassVar[frozenset[str]] = frozenset()

    @abstractmethod
    def anonymize_text(self, doc: Document) -> str:
        """Renvoie le texte anonymisé. Seule méthode à implémenter."""

    def _execute(
        self,
        doc: Document,
        gold: tuple[Annotation, ...],
    ) -> PipelineResult:
        anonymized = self.anonymize_text(doc)
        if not isinstance(anonymized, str):
            raise SystemContractError(
                f"Système {self.system_id!r} : anonymize_text doit renvoyer une "
                f"chaîne, pas {type(anonymized).__name__}."
            )
        return PipelineResult(
            doc_id=doc.doc_id,
            original_text=doc.text,
            anonymized_text=anonymized,
            annotations=(),
            decisions=(),
            risk=None,
            policy_id=self.config.policy_id or "",
            traces=(),
            status="ok",
            errors=(),
            runtime_ms=0.0,
            identity=self.identity(),
        )

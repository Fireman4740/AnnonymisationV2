"""Le pipeline déterministe de SPEC-10, exposé comme système enregistré.

Ce module **enveloppe** la classe ``Pipeline`` existante (composition, pas
héritage) : l'orchestrateur n'est pas réécrit, ses 8 étapes et ses 24 tests
restent inchangés. Il devient simplement une implémentation parmi d'autres.

``PipelineCapabilityError`` est conservée telle quelle : dans un monde
multi-systèmes, elle exprime « *ce* système ne sait pas faire NER/LLM », ce
qui est la bonne réponse — et non plus un refus global du dépôt.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from anonymisation.capabilities import (
    CAP_DECISIONS,
    CAP_GOLD_AWARE,
    CAP_POLICY,
    CAP_RISK,
    CAP_SPANS,
    CAP_TRACES,
)
from anonymisation.pipeline.orchestrator import Pipeline
from anonymisation.pipeline.traces import PipelineResult
from anonymisation.schema.models import Annotation, Document
from anonymisation.systems.base import SystemBase, SystemConfig
from anonymisation.systems.registry import register_system


class _DeterministicParams(BaseModel):
    """Paramètres propres au système.

    Le profil d'exécution reste la source de configuration des étapes
    (``configs/runtime/*.yaml``) : on ne duplique pas ici ce que
    ``RuntimeProfile`` valide déjà strictement.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime_profile: str = "deterministic"


@register_system
class DeterministicSystem(SystemBase):
    """Détection par motifs et règles, politique par seuils, hors ligne."""

    system_id: ClassVar[str] = "deterministic-v1"
    system_version: ClassVar[str] = "1"
    aliases: ClassVar[tuple[str, ...]] = ("deterministic",)
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {CAP_SPANS, CAP_DECISIONS, CAP_TRACES, CAP_RISK, CAP_POLICY, CAP_GOLD_AWARE}
    )
    uses_policy: ClassVar[bool] = True
    offline_only: ClassVar[bool] = True
    summary: ClassVar[str] = (
        "Pipeline 8 étapes de SPEC-10 : motifs + règles QI, fusion explicable, "
        "politique P0..P4. Aucun LLM, aucun GPU, aucun réseau."
    )
    Params: ClassVar[type[BaseModel] | None] = _DeterministicParams

    def __init__(self, config: SystemConfig | None = None) -> None:
        super().__init__(config)
        profile = self.config.profile or str(self._params["runtime_profile"])
        self._pipeline = Pipeline(
            profile,
            config_path=self.config.config_path,
            policy_id=self.config.policy_id,
        )

    def _execute(
        self,
        doc: Document,
        gold: tuple[Annotation, ...],
    ) -> PipelineResult:
        return self._pipeline.run(doc, gold)

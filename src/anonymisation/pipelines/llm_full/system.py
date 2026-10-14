"""Système ``llm-full-v1`` : le LLM fait toute la tâche d'anonymisation.

Contrairement à ``DeterministicSystem`` (motifs + règles + politique par
seuils, SPEC-10 étapes DETECT→PLAN séparées), ce système délègue au LLM un
appel unique par document qui fait à la fois DETECT et PLAN : trouver chaque
identifiant direct et quasi-identifiant, choisir l'action (SUPPRESS /
PSEUDONYMIZE / GENERALIZE) et proposer un texte de remplacement.

Ce que le code déterministe garde pour lui, volontairement :

- **la localisation des offsets** — on ne fait jamais confiance à un LLM pour
  compter des caractères ; le span renvoyé est recherché tel quel dans le
  texte original, en mots entiers (:func:`_locate_nth`), et une entité dont le span est
  introuvable est écartée plutôt que d'inventer un offset ;
- **la légalité de l'action** — validée contre ``ALLOWED_ACTIONS`` (SPEC-01
  §8, ``transform.decisions.check_action_allowed``) ; une action interdite ou
  un remplacement vide replient sur SUPPRESS plutôt que de produire une
  décision invalide ;
- **l'application au texte** — ``transform.apply.apply_decisions``, la même
  fonction que ``regex-only`` et ``deterministic``, offsets décroissants,
  jamais de chevauchement silencieux.

Limites connues, assumées pour cette première version (documentées plutôt que
masquées, conformément à la règle d'or du projet) :

- ``expression_mode`` est toujours ``EXPLICIT`` : ce système ne détecte que ce
  qui apparaît comme sous-chaîne littérale du texte, jamais une inférence
  purement implicite sans ancrage textuel (ex. un span vide) ;
- ``granularity`` est toujours ``EXACT``, ``stability`` toujours ``VOLATILE`` :
  le LLM n'est pas interrogé sur ces deux axes dans cette version ;
- deux occurrences distinctes d'un même texte identifiant (ex. un nom cité
  deux fois) sont résolues dans l'ordre où le LLM les a listées : si le LLM
  fusionne à tort deux occurrences réelles en une seule entité, la seconde
  occurrence n'est pas anonymisée (limite de la détection, pas du code de
  localisation).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from anonymisation.capabilities import CAP_DECISIONS, CAP_SPANS
from anonymisation.detect.base import Candidate, candidates_to_annotations
from anonymisation.llm.client import LlmBackendUnavailableError, LlmClient, LlmCompletion
from anonymisation.llm.config import load_backends_config
from anonymisation.pipeline.orchestrator import _merge_overlapping
from anonymisation.pipeline.traces import PipelineResult
from anonymisation.pipelines.llm_full.prompts import (
    ParsedEntity,
    build_anonymization_prompt,
    parse_llm_entities,
)
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import (
    DIRECT_CODES,
    QUASI_CODES,
    ExpressionMode,
    Granularity,
    IdentifierType,
    Stability,
    UnknownQiCodeError,
    validate_code,
)
from anonymisation.systems.base import ModelRef, SystemBase, SystemConfig
from anonymisation.systems.registry import register_system
from anonymisation.transform.apply import apply_decisions
from anonymisation.transform.decisions import (
    Action,
    ActionNotAllowedError,
    AnonymizationDecision,
    check_action_allowed,
)

#: Attentes avant chaque nouvelle tentative d'un backend injoignable ; mêmes
#: valeurs que l'attaquant et le juge (``attack/ratbench/runner.py``).
RETRY_DELAYS_S: tuple[int, ...] = (5, 15, 30, 60, 120)

#: Repli par type d'identifiant quand l'action proposée par le LLM est
#: illégale (SPEC-01 §8) ou que son remplacement est vide.
_FALLBACK_ACTION: dict[IdentifierType, Action] = {
    IdentifierType.DIRECT: Action.SUPPRESS,
    IdentifierType.QUASI: Action.SUPPRESS,
}

#: Clé de granularité passée à ``check_action_allowed`` (SPEC-01 §8) : les
#: quasi-identifiants détectés par ce système sont toujours traités comme
#: ``EXACT`` (voir la note de limites en tête de module) ; les identifiants
#: directs n'ont pas de notion de granularité (clé ``None``).
def _granularity_key(identifier_type: IdentifierType) -> str | None:
    return "EXACT" if identifier_type is IdentifierType.QUASI else None


class _LlmFullParams(BaseModel):
    """Paramètres du système ``llm-full-v1``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Clé de backend dans ``configs/llm/backends.yaml`` (ex. "qwen_local").
    backend: str = "qwen_local"
    #: Garde-fou anti-divergence : au-delà, les entités surnuméraires sont
    #: ignorées plutôt que de laisser une réponse aberrante saturer le document.
    max_entities: int = Field(default=60, ge=1)
    max_output_tokens: int = Field(default=4096, ge=1)
    #: Override de la température du backend ; ``None`` = valeur du backend.
    temperature: float | None = None


def _identifier_type_for(category: str) -> IdentifierType:
    if category in DIRECT_CODES:
        return IdentifierType.DIRECT
    if category in QUASI_CODES:
        return IdentifierType.QUASI
    raise UnknownQiCodeError(
        f"Catégorie {category!r} hors du périmètre offert au LLM "
        "(ni DIRECT_CODES, ni QUASI_CODES admis)."
    )


def _on_word_boundaries(text: str, start: int, end: int) -> bool:
    """L'occurrence ``text[start:end]`` n'est-elle pas collée à un autre mot ?

    Même règle que la mesure de fuite (``metrics.leakage.surface_present``) :
    un bord alphanumérique du span ne doit pas toucher un caractère
    alphanumérique du texte. Sans elle, « Ali » se localisait dans « Alice » :
    le mauvais mot était masqué et la vraie mention restait en clair.
    """
    left_ok = not text[start].isalnum() or start == 0 or not text[start - 1].isalnum()
    right_ok = not text[end - 1].isalnum() or end == len(text) or not text[end].isalnum()
    return left_ok and right_ok


def _locate_nth(text: str, span: str, occurrence_index: int) -> tuple[int, int] | None:
    """Trouve la ``occurrence_index``-ième occurrence **en mots entiers** de ``span``.

    Recherche par sous-chaîne exacte, jamais par offset renvoyé par le LLM
    (SPEC-10, invariant des offsets) ; les occurrences internes à un autre
    mot sont ignorées. Renvoie ``None`` si l'occurrence demandée n'existe pas
    plutôt que de deviner.
    """
    if not span:
        return None
    found = 0
    start = text.find(span)
    while start != -1:
        end = start + len(span)
        if _on_word_boundaries(text, start, end):
            if found == occurrence_index:
                return start, end
            found += 1
        start = text.find(span, start + 1)
    return None


def _resolve_action(
    identifier_type: IdentifierType,
    category: str,
    action_str: str,
    replacement: str,
) -> tuple[Action, str, bool]:
    """Choisit l'action effective. Renvoie ``(action, replacement, repliée?)``.

    Replie sur l'action de secours du type d'identifiant si l'action proposée
    est inconnue, interdite par SPEC-01 §8, ou si son remplacement est vide
    alors que l'action n'est pas SUPPRESS — jamais silencieusement, le
    troisième élément du tuple le signale à l'appelant pour journalisation.
    """
    try:
        action = Action(action_str)
    except ValueError:
        return _FALLBACK_ACTION[identifier_type], f"[{category}_SUPPRIME]", True

    try:
        check_action_allowed(identifier_type, _granularity_key(identifier_type), action)
    except ActionNotAllowedError:
        return _FALLBACK_ACTION[identifier_type], f"[{category}_SUPPRIME]", True

    if action is Action.SUPPRESS:
        return action, f"[{category}_SUPPRIME]", False

    cleaned = replacement.strip()
    if not cleaned:
        return _FALLBACK_ACTION[identifier_type], f"[{category}_SUPPRIME]", True

    return action, cleaned, False


@register_system
class LlmFullSystem(SystemBase):
    """Un seul appel LLM par document : détection + décision + remplacement."""

    system_id: ClassVar[str] = "llm-full-v1"
    system_version: ClassVar[str] = "1"
    aliases: ClassVar[tuple[str, ...]] = ("llm-full", "llm")
    capabilities: ClassVar[frozenset[str]] = frozenset({CAP_SPANS, CAP_DECISIONS})
    uses_policy: ClassVar[bool] = False
    offline_only: ClassVar[bool] = False
    summary: ClassVar[str] = (
        "Anonymisation intégrale par LLM : détection des identifiants directs et "
        "quasi-identifiants, choix de l'action et du remplacement en un appel par "
        "document. Aucune politique de seuils : le modèle décide lui-même."
    )
    Params: ClassVar[type[BaseModel] | None] = _LlmFullParams

    @classmethod
    def contract_config(cls) -> SystemConfig:
        # Backend `stub` : réponse canned, aucun socket ouvert. Le contrat de
        # test exécute tout système enregistré sur un corpus réel ; un système
        # LLM doit donc pouvoir tourner hors ligne.
        return SystemConfig(params={"backend": "stub"})

    def __init__(self, config: SystemConfig | None = None) -> None:
        super().__init__(config)
        config_path = None
        if self.config.repo_root is not None:
            candidate = self.config.repo_root / "configs" / "llm" / "backends.yaml"
            if candidate.is_file():
                config_path = candidate
        backends_config = load_backends_config(config_path)
        self._client = LlmClient.for_backend(
            str(self._params["backend"]), config=backends_config
        )
        self._max_entities = int(self._params["max_entities"])
        self._max_output_tokens = int(self._params["max_output_tokens"])
        self._temperature = self._params.get("temperature")

    def models(self) -> tuple[ModelRef, ...]:
        backend = self._client.backend
        return (ModelRef(name=str(backend.model), revision=backend.name),)

    def prompts(self) -> tuple[str, ...]:
        return ("anonymisation.pipelines.llm_full.prompts:build_anonymization_prompt",)

    def _build_candidate(
        self, doc: Document, entity: ParsedEntity, occurrence_index: int
    ) -> tuple[Candidate, str, str] | None:
        """Construit un ``Candidate`` localisé, ou ``None`` si le span est introuvable."""
        try:
            category = validate_code(entity.category)
        except UnknownQiCodeError:
            return None
        try:
            identifier_type = _identifier_type_for(category)
        except UnknownQiCodeError:
            return None

        located = _locate_nth(doc.text, entity.span, occurrence_index)
        if located is None:
            return None
        start, end = located

        candidate = Candidate(
            start=start,
            end=end,
            text=doc.text[start:end],
            qi_category=category,
            identifier_type=identifier_type,
            source=f"llm:{self._client.backend.name}",
            confidence=0.75,
            granularity=Granularity.EXACT,
            stability=Stability.VOLATILE,
            expression_mode=ExpressionMode.EXPLICIT,
        )
        return candidate, entity.action, entity.replacement

    def _complete_with_retries(
        self, prompt: str, sleep: Callable[[float], None] = time.sleep,
    ) -> LlmCompletion:
        """Ré-essaie un backend injoignable (429 du pool partagé OpenRouter)
        avec les mêmes attentes que l'attaquant et le juge. Une panne qui
        persiste après la dernière attente remonte : le document est en
        erreur, jamais vide. Une réponse vide ou tronquée n'est pas
        ré-essayée (C3)."""
        for attempt, delay in enumerate((0, *RETRY_DELAYS_S)):
            if delay:
                sleep(delay)
            try:
                return self._client.complete(prompt, temperature=self._temperature,
                                             max_tokens=self._max_output_tokens)
            except LlmBackendUnavailableError as exc:
                if not exc.retryable or attempt == len(RETRY_DELAYS_S):
                    raise
        raise AssertionError("inatteignable")

    def _execute(
        self,
        doc: Document,
        gold: tuple[Annotation, ...],
    ) -> PipelineResult:
        # Ne lit jamais `gold` : ce système n'est pas gold-aware (contrat CAP_GOLD_AWARE absent).
        #
        # Ni le backend injoignable/vide (LlmBackendUnavailableError,
        # LlmEmptyResponseError) ni une réponse structurellement inexploitable
        # (LlmMalformedResponseError) ne sont interceptés ici : ils remontent
        # tels quels et ``SystemBase.run`` les convertit en status="error"
        # nommé — jamais interprétés comme « aucune entité trouvée » (C3).
        prompt = build_anonymization_prompt(doc.text)
        completion = self._complete_with_retries(prompt)
        parsed = parse_llm_entities(completion.content)

        candidates: list[Candidate] = []
        decisions: list[AnonymizationDecision] = []
        warnings: list[str] = []
        if len(parsed) > self._max_entities:
            warnings.append(f"limite max_entities={self._max_entities} : "
                            f"{len(parsed) - self._max_entities} entité(s) non traitée(s)")
        occurrence_counts: dict[tuple[str, str], int] = {}

        for entity in parsed[: self._max_entities]:
            # Une même mention peut porter plusieurs catégories (I-ANN-5).
            # Chaque catégorie parcourt ses occurrences indépendamment.
            occurrence_key = (entity.span, entity.category)
            occurrence_index = occurrence_counts.get(occurrence_key, 0)
            occurrence_counts[occurrence_key] = occurrence_index + 1

            built = self._build_candidate(doc, entity, occurrence_index)
            if built is None:
                warnings.append(
                    f"entité écartée : span={entity.span!r} catégorie={entity.category!r} "
                    "(catégorie hors périmètre ou occurrence introuvable dans le texte)"
                )
                continue
            candidate, action_str, replacement = built
            candidates.append(candidate)

            action, replacement_text, coerced = _resolve_action(
                candidate.identifier_type, candidate.qi_category, action_str, replacement
            )
            if coerced:
                warnings.append(
                    f"action repliée sur {action.value} pour {candidate.qi_category} "
                    f"(proposition LLM invalide ou remplacement vide : action={action_str!r})"
                )
            decisions.append(
                AnonymizationDecision(
                    start=candidate.start,
                    end=candidate.end,
                    original=candidate.text,
                    action=action,
                    replacement=replacement_text,
                    qi_category=candidate.qi_category,
                    reason=(
                        f"LLM ({self._client.backend.name}) : {candidate.qi_category}, "
                        f"action {action.value}"
                        + (" (repliée, proposition initiale invalide)" if coerced else "")
                    ),
                )
            )

        annotations = tuple(candidates_to_annotations(candidates, doc.doc_id, doc.text))
        non_keep = [d for d in decisions if d.action is not Action.KEEP]
        merged = _merge_overlapping(non_keep, doc.text)
        transform_res = apply_decisions(doc.text, merged)

        status = "partial" if warnings else "ok"
        return PipelineResult(
            doc_id=doc.doc_id,
            original_text=doc.text,
            anonymized_text=transform_res.anonymized_text,
            annotations=annotations,
            decisions=tuple(decisions),
            risk=None,
            policy_id="",
            traces=(),
            status=status,
            errors=tuple(warnings),
            runtime_ms=completion.latency_ms,
            identity=self.identity(),
        )


__all__ = ["LlmFullSystem"]

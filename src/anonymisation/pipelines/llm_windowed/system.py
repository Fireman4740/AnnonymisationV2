"""Système ``llm-windowed-v1`` : anonymisation LLM par fenêtres recouvrantes.

``llm-full-v1`` fait un appel unique par document. Cette architecture-ci
découpe le texte en fenêtres contiguës (frontières de paragraphe, puis de
phrase, puis d'espace), avec un court recouvrement de contexte, et appelle le
LLM une fois par fenêtre. Chaque réponse est parsée avec le même contrat JSON
strict, puis les entités sont localisées sur le **texte original** — jamais
sur un offset renvoyé par le modèle.

Pourquoi cette architecture : la campagne ``llm-full-v1`` a montré qu'un
document long produit une sortie JSON tronquée (1/15 sur TAB, 48 erreurs sur
RAT-Bench dans la campagne max-500), ce qui rend le run non publiable au-delà
de 5 % d'erreurs (SPEC-10 C4). Découper réduit la longueur de sortie par appel
et borne le coût d'une fenêtre aberrante.

Ce que le code garde pour lui, comme ``llm-full`` :

- **la localisation des offsets** — recherche exacte, en mots entiers, dans la
  fenêtre, puis translation vers le texte original ; une entité introuvable
  est écartée et journalisée ;
- **la légalité de l'action** — validée contre ``ALLOWED_ACTIONS`` (SPEC-01
  §8), repli explicite sur ``SUPPRESS`` ;
- **l'application au texte** — ``apply_decisions``, offsets décroissants.

Une réponse vide, tronquée ou non-JSON reste une **erreur nommée** (C3), jamais
« aucune entité trouvée ». Une seule fenêtre en échec met le document entier en
erreur : poursuivre laisserait une portion du texte non anonymisée.

Limites connues de cette version, documentées plutôt que masquées :

- une entité qui chevauche une frontière de fenêtre n'est détectée que si le
  recouvrement suffit à la faire apparaître entière dans la fenêtre suivante ;
  le recouvrement par défaut (240 caractères) couvre les mentions usuelles,
  pas un paragraphe entier ;
- le modèle ne voit pas le document global : une coréférence très lointaine
  (« il », « cette personne ») reste hors de portée, comme pour ``llm-full`` ;
- ``expression_mode`` est toujours ``EXPLICIT``, ``granularity`` toujours
  ``EXACT`` et ``stability`` toujours ``VOLATILE`` : le modèle n'est pas
  interrogé sur ces axes.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from anonymisation.capabilities import CAP_DECISIONS, CAP_SPANS
from anonymisation.detect.base import Candidate, candidates_to_annotations
from anonymisation.llm.client import LlmBackendUnavailableError, LlmClient, LlmCompletion
from anonymisation.llm.config import load_backends_config
from anonymisation.pipeline.orchestrator import _merge_overlapping
from anonymisation.pipeline.traces import PipelineResult
from anonymisation.pipelines.llm_windowed.prompts import (
    ParsedEntity,
    build_window_prompt,
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
#: valeurs que ``llm-full``, l'attaquant et le juge.
RETRY_DELAYS_S: tuple[int, ...] = (5, 15, 30, 60, 120)

#: Repli par type d'identifiant quand l'action proposée par le LLM est
#: illégale (SPEC-01 §8) ou que son remplacement est vide.
_FALLBACK_ACTION: dict[IdentifierType, Action] = {
    IdentifierType.DIRECT: Action.SUPPRESS,
    IdentifierType.QUASI: Action.SUPPRESS,
}


def _granularity_key(identifier_type: IdentifierType) -> str | None:
    return "EXACT" if identifier_type is IdentifierType.QUASI else None


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
    left_ok = not text[start].isalnum() or start == 0 or not text[start - 1].isalnum()
    right_ok = not text[end - 1].isalnum() or end == len(text) or not text[end].isalnum()
    return left_ok and right_ok


def _locate_nth(text: str, span: str, occurrence_index: int) -> tuple[int, int] | None:
    """Trouve la ``occurrence_index``-ième occurrence en mots entiers de ``span``."""
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
    """Choisit l'action effective. Renvoie ``(action, replacement, repliée?)``."""
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


@dataclass(frozen=True)
class Window:
    """Vue d'une fenêtre sur le texte original.

    ``segment_start:segment_end`` est la portion **nouvelle** couverte par
    cette fenêtre ; ``prompt_start:prompt_end`` est le texte effectivement
    envoyé au modèle, qui inclut un recouvrement de contexte à gauche.
    """

    prompt_start: int
    prompt_end: int
    segment_start: int
    segment_end: int


def _context_start(text: str, cursor: int, overlap: int) -> int:
    """Début du contexte, aligné sur un mot quand c'est possible.

    Si aucun espace n'existe dans la zone de recouvrement, on garde le début
    brut plutôt que de supprimer tout le contexte : c'est précisément le cas
    d'une entité longue coupée en plein milieu, qu'il faut retrouver entière
    dans la fenêtre suivante.
    """
    if overlap <= 0 or cursor == 0:
        return cursor
    start = max(0, cursor - overlap)
    if start > 0:
        space = text.find(" ", start, cursor)
        if space != -1:
            start = space + 1
    return min(start, cursor)


def _break_before(text: str, cursor: int, hard_end: int, max_chars: int) -> int:
    """Recule ``hard_end`` vers une frontière lisible sans fenêtre trop courte.

    Priorité : paragraphe, saut de ligne, fin de phrase, espace. Si aucune
    frontière n'existe dans le dernier tiers de la fenêtre, la coupe reste
    dure — le recouvrement suivant permettra de rattraper une entité coupée.
    """
    min_end = cursor + max(1, max_chars // 3)
    if min_end >= hard_end:
        return hard_end
    for separator in ("\n\n", "\n"):
        position = text.rfind(separator, min_end, hard_end)
        if position != -1:
            return position + len(separator)
    for position in range(hard_end - 1, min_end - 1, -1):
        if text[position] in ".!?" and position + 1 < len(text):
            return position + 1
    position = text.rfind(" ", min_end, hard_end)
    if position != -1:
        return position
    return hard_end


def split_windows(text: str, *, max_chars: int, overlap_chars: int) -> tuple[Window, ...]:
    """Découpe ``text`` en fenêtres contiguës couvrant tout le document.

    Les segments ``segment_start:segment_end`` sont contigus et couvrent
    ``[0, len(text))`` exactement une fois : aucun caractère n'est oublié.
    Le recouvrement ne sert qu'au contexte du prompt et ne duplique pas la
    couverture.
    """
    if max_chars < 1:
        raise ValueError("max_chars doit être strictement positif.")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars doit être dans [0, max_chars).")
    length = len(text)
    if length == 0:
        return ()
    if length <= max_chars:
        return (Window(0, length, 0, length),)

    windows: list[Window] = []
    cursor = 0
    while cursor < length:
        segment_end = min(cursor + max_chars, length)
        if segment_end < length:
            segment_end = _break_before(text, cursor, segment_end, max_chars)
        prompt_start = _context_start(text, cursor, overlap_chars)
        windows.append(
            Window(
                prompt_start=prompt_start,
                prompt_end=segment_end,
                segment_start=cursor,
                segment_end=segment_end,
            )
        )
        cursor = segment_end
    return tuple(windows)


class _LlmWindowedParams(BaseModel):
    """Paramètres du système ``llm-windowed-v1``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Clé de backend dans ``configs/llm/backends.yaml``.
    backend: str = "qwen_local_box"
    #: Taille maximale d'une fenêtre, en caractères du texte original.
    window_chars: int = Field(default=6000, ge=500)
    #: Recouvrement de contexte à gauche de chaque fenêtre.
    overlap_chars: int = Field(default=240, ge=0)
    #: Garde-fou : au-delà, une fenêtre est considérée comme aberrante.
    max_entities: int = Field(default=256, ge=1)
    max_output_tokens: int = Field(default=8192, ge=1)
    #: Garde-fou contre un découpage pathologique (texte énorme ou mauvais
    #: paramétrage) : au-delà, le document est en erreur, jamais tronqué.
    max_windows: int = Field(default=64, ge=1)
    #: Override de la température du backend ; ``None`` = valeur du backend.
    temperature: float | None = None


@register_system
class LlmWindowedSystem(SystemBase):
    """Anonymisation LLM par fenêtres recouvrantes, offsets sur le texte original."""

    system_id: ClassVar[str] = "llm-windowed-v1"
    system_version: ClassVar[str] = "1"
    aliases: ClassVar[tuple[str, ...]] = ("llm-windowed", "llm_windowed")
    capabilities: ClassVar[frozenset[str]] = frozenset({CAP_SPANS, CAP_DECISIONS})
    uses_policy: ClassVar[bool] = False
    offline_only: ClassVar[bool] = False
    summary: ClassVar[str] = (
        "Anonymisation par LLM fenêtré : découpe le document en fenêtres "
        "recouvrantes, un appel par fenêtre, puis localise et applique les "
        "décisions sur le texte original. Conçue pour les documents longs."
    )
    Params: ClassVar[type[BaseModel] | None] = _LlmWindowedParams

    @classmethod
    def contract_config(cls) -> SystemConfig:
        # Backend `stub` : réponse canned, aucun socket ouvert. Le contrat de
        # test exécute tout système enregistré sur un corpus réel.
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
        self._window_chars = int(self._params["window_chars"])
        self._overlap_chars = int(self._params["overlap_chars"])
        self._max_entities = int(self._params["max_entities"])
        self._max_output_tokens = int(self._params["max_output_tokens"])
        self._max_windows = int(self._params["max_windows"])
        self._temperature = self._params.get("temperature")

    def models(self) -> tuple[ModelRef, ...]:
        backend = self._client.backend
        return (ModelRef(name=str(backend.model), revision=backend.name),)

    def prompts(self) -> tuple[str, ...]:
        return (
            "anonymisation.pipelines.llm_windowed.prompts:build_window_prompt",
        )

    def _complete_with_retries(
        self, prompt: str, sleep: Callable[[float], None] = time.sleep,
    ) -> LlmCompletion:
        """Ré-essaie un backend injoignable ; ne ré-essaie jamais un vide (C3)."""
        for attempt, delay in enumerate((0, *RETRY_DELAYS_S)):
            if delay:
                sleep(delay)
            try:
                return self._client.complete(
                    prompt,
                    temperature=self._temperature,
                    max_tokens=self._max_output_tokens,
                )
            except LlmBackendUnavailableError as exc:
                if not exc.retryable or attempt == len(RETRY_DELAYS_S):
                    raise
        raise AssertionError("inatteignable")

    def _build_candidate(
        self, doc: Document, window: Window, entity: ParsedEntity, occurrence_index: int
    ) -> tuple[Candidate, str, str] | None:
        """Construit un ``Candidate`` localisé sur le texte original."""
        try:
            category = validate_code(entity.category)
        except UnknownQiCodeError:
            return None
        try:
            identifier_type = _identifier_type_for(category)
        except UnknownQiCodeError:
            return None

        chunk = doc.text[window.prompt_start : window.prompt_end]
        located = _locate_nth(chunk, entity.span, occurrence_index)
        if located is None:
            return None
        start = window.prompt_start + located[0]
        end = window.prompt_start + located[1]
        if doc.text[start:end] != entity.span:
            return None

        candidate = Candidate(
            start=start,
            end=end,
            text=doc.text[start:end],
            qi_category=category,
            identifier_type=identifier_type,
            source=f"llm-windowed:{self._client.backend.name}",
            confidence=0.75,
            granularity=Granularity.EXACT,
            stability=Stability.VOLATILE,
            expression_mode=ExpressionMode.EXPLICIT,
        )
        return candidate, entity.action, entity.replacement

    def _execute(
        self,
        doc: Document,
        gold: tuple[Annotation, ...],
    ) -> PipelineResult:
        # Ne lit jamais `gold` : ce système n'est pas gold-aware.
        #
        # Toute erreur de fenêtre (backend, réponse vide, JSON invalide) remonte
        # telle quelle : `SystemBase.run` la convertit en status="error" nommé,
        # jamais en « aucune entité » (SPEC-10 C3). Un document partiellement
        # traité serait un document non anonymisé : on ne le publie pas.
        windows = split_windows(
            doc.text, max_chars=self._window_chars, overlap_chars=self._overlap_chars
        )
        if len(windows) > self._max_windows:
            raise ValueError(
                f"Découpage refusé : {len(windows)} fenêtres > max_windows="
                f"{self._max_windows} ; augmenter max_windows plutôt que de "
                "tronquer le document."
            )

        candidates: list[Candidate] = []
        decisions: list[AnonymizationDecision] = []
        warnings: list[str] = []
        seen: set[tuple[int, int, str]] = set()
        runtime_ms = 0.0

        for index, window in enumerate(windows, start=1):
            chunk = doc.text[window.prompt_start : window.prompt_end]
            prompt = build_window_prompt(chunk, index=index, total=len(windows))
            completion = self._complete_with_retries(prompt)
            runtime_ms += completion.latency_ms
            parsed = parse_llm_entities(completion.content)
            if len(parsed) > self._max_entities:
                warnings.append(
                    f"fenêtre {index}/{len(windows)} : limite max_entities="
                    f"{self._max_entities} dépassée, {len(parsed) - self._max_entities} "
                    "entité(s) non traitée(s)"
                )

            occurrence_counts: dict[tuple[str, str], int] = {}
            for entity in parsed[: self._max_entities]:
                occurrence_key = (entity.span, entity.category)
                occurrence_index = occurrence_counts.get(occurrence_key, 0)
                occurrence_counts[occurrence_key] = occurrence_index + 1

                built = self._build_candidate(doc, window, entity, occurrence_index)
                if built is None:
                    warnings.append(
                        f"entité écartée : span={entity.span!r} "
                        f"catégorie={entity.category!r} fenêtre={index}/"
                        f"{len(windows)} (catégorie hors périmètre ou occurrence "
                        "introuvable)"
                    )
                    continue
                candidate, action_str, replacement = built

                key = (candidate.start, candidate.end, candidate.qi_category)
                if key in seen:
                    # Recouvrement : la même mention a déjà été décidée.
                    continue
                seen.add(key)
                candidates.append(candidate)

                action, replacement_text, coerced = _resolve_action(
                    candidate.identifier_type,
                    candidate.qi_category,
                    action_str,
                    replacement,
                )
                if coerced:
                    warnings.append(
                        f"action repliée sur {action.value} pour "
                        f"{candidate.qi_category} (proposition LLM invalide ou "
                        f"remplacement vide : action={action_str!r})"
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
                            f"LLM fenêtré ({self._client.backend.name}) : "
                            f"{candidate.qi_category}, action {action.value}"
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
            runtime_ms=runtime_ms,
            identity=self.identity(),
        )


__all__ = ["LlmWindowedSystem", "Window", "split_windows"]

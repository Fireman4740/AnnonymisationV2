"""Politique de divulgation HIDE / KEEP / NEUTRAL, appliquée hors prompt.

Interface : :class:`DisclosurePolicy` évalue un attribut et rend un verdict
(:class:`Verdict`) ; :func:`apply_disclosure` applique ces verdicts aux
décisions d'un :class:`PipelineResult` déjà produit.

Pourquoi une étape séparée plutôt qu'une consigne dans le prompt : la même
politique doit gouverner n'importe quel système (règles, LLM, boîte noire à
décisions) et n'importe quel corpus, sans changer ce que le détecteur voit.
Le détecteur reste identique ; seule la décision finale change, et l'écart
avec/sans politique est mesurable sur les mêmes détections.

Règles :

- une décision dont la catégorie se rattache à un attribut ``KEEP`` (ou
  ``NEUTRAL`` si ``neutral_action == "keep"``) devient une décision ``KEEP`` :
  le passage reste en clair, la détection reste tracée ;
- une catégorie rattachée à aucun attribut n'est gouvernée par aucune
  politique : la décision du système est conservée telle quelle ;
- un attribut de la table absent des trois listes de la politique est une
  erreur : une politique incomplète ne doit pas laisser deviner son intention ;
- source ``document`` : la politique vient de ``Document.meta["policy"]`` ;
  son absence est une erreur, jamais « tout HIDE ».

Limite : le verdict dépend de la catégorie choisie par le système. Un indice
d'éducation étiqueté par erreur ``GEN_OCCUPATION`` suit la règle de
l'occupation. La politique ne corrige pas les erreurs de catégorisation.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from anonymisation.pipeline.orchestrator import _merge_overlapping
from anonymisation.pipeline.traces import PipelineResult
from anonymisation.schema.io import sha256_file
from anonymisation.schema.models import Document
from anonymisation.transform.apply import apply_decisions
from anonymisation.transform.decisions import Action, AnonymizationDecision


class DisclosureError(ValueError):
    """Politique de divulgation absente, incomplète ou inapplicable."""


class Verdict(str, Enum):
    HIDE = "HIDE"
    KEEP = "KEEP"
    NEUTRAL = "NEUTRAL"
    UNGOVERNED = "UNGOVERNED"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PolicySpec(_Strict):
    label: str = Field(min_length=1)
    source: Literal["document", "static"]
    neutral_action: Literal["hide", "keep"]
    hide: tuple[str, ...] | None = None
    keep: tuple[str, ...] | None = None
    neutral: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def lists_match_source(self):
        lists = (self.hide, self.keep, self.neutral)
        if self.source == "static" and any(x is None for x in lists):
            raise ValueError("politique statique : hide, keep et neutral sont requis")
        if self.source == "document" and any(x is not None for x in lists):
            raise ValueError("politique document : les listes viennent du document, pas du YAML")
        return self


class DisclosureConfig(_Strict):
    attributes: dict[str, tuple[str, ...]]
    policies: dict[str, PolicySpec]

    @model_validator(mode="after")
    def injective(self):
        seen: dict[str, str] = {}
        for attribute, codes in self.attributes.items():
            for code in codes:
                if code in seen:
                    raise ValueError(f"{code!r} rattaché à {seen[code]!r} et {attribute!r}")
                seen[code] = attribute
        return self

    def category_to_attribute(self) -> dict[str, str]:
        return {code: a for a, codes in self.attributes.items() for code in codes}


@dataclass(frozen=True)
class DisclosurePolicy:
    """Verdicts d'une politique résolue (pour un document ou pour tout un run)."""

    hide: frozenset[str]
    keep: frozenset[str]
    neutral: frozenset[str]
    neutral_action: str
    category_to_attribute: Mapping[str, str]

    def __post_init__(self) -> None:
        attributes = set(self.category_to_attribute.values())
        listed = self.hide | self.keep | self.neutral
        overlap = (self.hide & self.keep) | (self.hide & self.neutral) | (self.keep & self.neutral)
        if overlap:
            raise DisclosureError(f"attribut(s) dans plusieurs listes : {sorted(overlap)}")
        if listed != attributes:
            raise DisclosureError(
                f"politique incomplète ou inconnue : manquants {sorted(attributes - listed)}, "
                f"inconnus {sorted(listed - attributes)} (table : configs/policy/disclosure.yaml)")

    def evaluate(self, category: str) -> Verdict:
        attribute = self.category_to_attribute.get(category)
        if attribute is None:
            return Verdict.UNGOVERNED
        if attribute in self.hide:
            return Verdict.HIDE
        return Verdict.KEEP if attribute in self.keep else Verdict.NEUTRAL

    def discloses(self, verdict: Verdict) -> bool:
        return verdict is Verdict.KEEP or (verdict is Verdict.NEUTRAL and self.neutral_action == "keep")


@dataclass(frozen=True)
class DisclosureStage:
    """Étape configurée : résout la politique d'un document puis l'applique."""

    policy_id: str
    spec: PolicySpec
    config: DisclosureConfig
    source_path: Path

    def policy_for(self, doc: Document) -> DisclosurePolicy:
        mapping = self.config.category_to_attribute()
        if self.spec.source == "static":
            lists = (self.spec.hide, self.spec.keep, self.spec.neutral)
        else:
            raw = doc.meta.get("policy")
            if not isinstance(raw, Mapping) or not all(isinstance(raw.get(k), list) for k in ("hide", "keep", "neutral")):
                raise DisclosureError(
                    f"{doc.doc_id} : politique {self.policy_id!r} exige Document.meta['policy'] "
                    "avec les listes hide, keep et neutral ; ce corpus n'en fournit pas — "
                    "choisir une politique statique")
            lists = (raw["hide"], raw["keep"], raw["neutral"])
        hide, keep, neutral = (frozenset(x) for x in lists)
        return DisclosurePolicy(hide, keep, neutral, self.spec.neutral_action, mapping)

    def lock_block(self) -> dict[str, Any]:
        return {"id": self.policy_id, "source": self.spec.source, "neutral_action": self.spec.neutral_action,
                "config": str(self.source_path), "sha256": sha256_file(self.source_path)}


def load_stage(policy_id: str, path: Path) -> DisclosureStage:
    try:
        config = DisclosureConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise DisclosureError(f"{path} : configuration de divulgation invalide — {exc}") from exc
    if policy_id not in config.policies:
        raise DisclosureError(f"{path} : politique {policy_id!r} inconnue ; disponibles : {sorted(config.policies)}")
    return DisclosureStage(policy_id, config.policies[policy_id], config, path)


def render(text: str, decisions) -> str:
    """Rendu canonique : fusion des décisions non KEEP chevauchantes, puis application.

    Certains systèmes (llm-windowed) conservent des décisions brutes qui se
    chevauchent et rendent leur texte depuis leur fusion ; d'autres stockent
    des décisions déjà disjointes, pour lesquelles la fusion est neutre.
    """
    non_keep = [d for d in decisions if d.action is not Action.KEEP]
    return apply_decisions(text, _merge_overlapping(non_keep, text)).anonymized_text


def apply_disclosure(result: PipelineResult, doc: Document, stage: DisclosureStage) -> tuple[PipelineResult, Counter]:
    """Rend un nouveau résultat ; un document en erreur reste inchangé."""
    counts: Counter = Counter()
    if result.status == "error":
        return result, counts
    policy = stage.policy_for(doc)
    # Réappliquer les décisions doit redonner le texte du système ; sinon le
    # texte vient d'ailleurs (réécriture libre) et la politique le falsifierait.
    if render(doc.text, result.decisions) != result.anonymized_text:
        raise DisclosureError(f"{doc.doc_id} : texte anonymisé non reproductible depuis les décisions ; "
                              "politique de divulgation inapplicable à ce système")
    decisions = []
    for decision in result.decisions:
        if decision.action is Action.KEEP:
            decisions.append(decision)
            continue
        verdict = policy.evaluate(decision.qi_category)
        counts[verdict.value] += 1
        if policy.discloses(verdict):
            counts["disclosed"] += 1
            decisions.append(AnonymizationDecision(
                start=decision.start, end=decision.end, original=decision.original, action=Action.KEEP,
                replacement=decision.original, qi_category=decision.qi_category,
                reason=f"Politique de divulgation {stage.policy_id} : attribut {verdict.value}, laissé en clair "
                       f"(action initiale {decision.action.value})",
                meta={**decision.meta, "disclosure": {"policy": stage.policy_id, "verdict": verdict.value,
                                                      "initial_action": decision.action.value}}))
        else:
            decisions.append(decision)
    text = render(doc.text, decisions)
    return replace(result, decisions=tuple(decisions), anonymized_text=text), counts

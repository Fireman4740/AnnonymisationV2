"""Modèles de données du format pivot.

Implémentation normative de SPEC-02
(``documentation/specifications/SPEC-02-schema-donnees.md``).

Deux choix imposés sur tous les modèles :

* ``extra="forbid"`` — un champ inattendu est une erreur, pas un champ ignoré ;
  c'est ce qui rattrape les fautes de frappe dans les adaptateurs.
* ``frozen=True`` — les objets sont immuables ; une transformation produit un
  nouvel objet, ce qui rend le pipeline traçable.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Sensitivity,
    Stability,
    Subject,
    check_direct_exclusivity,
    validate_code,
)

SCHEMA_VERSION: Final[str] = "2.1"

_BASE = ConfigDict(frozen=True, extra="forbid")


class Domain(str, Enum):
    HR = "hr"
    SUPPORT = "support"
    FORUM = "forum"
    LEGAL = "legal"
    CLINICAL = "clinical"
    GENERIC = "generic"


class Scope(str, Enum):
    """Portée d'observation des QI (SPEC-06 §7)."""

    DOCUMENT = "document"
    THREAD = "thread"
    AUTHOR = "author"


class TargetType(str, Enum):
    PERSON = "person"
    ORGANIZATION = "organization"


class RiskModel(str, Enum):
    PROSECUTOR = "prosecutor"
    JOURNALIST = "journalist"
    MARKETER = "marketer"
    COPULA = "copula"


class CombinationSource(str, Enum):
    """D'où vient la vérité terrain d'une combinaison.

    ``COMPUTED`` signale une valeur produite par notre propre moteur de risque :
    elle NE DOIT PAS servir à évaluer ce même moteur (invariant I-CMB-3, garde
    de circularité de SPEC-07 §4).
    """

    GENERATED = "generated"
    ANNOTATED = "annotated"
    DATASET = "dataset"
    COMPUTED = "computed"


# --------------------------------------------------------------------------- #
# documents.jsonl
# --------------------------------------------------------------------------- #
class Document(BaseModel):
    model_config = _BASE

    doc_id: str
    dataset: str
    split: str
    domain: Domain
    language: str                       # ISO 639-1
    text: str                           # immuable après calcul des offsets
    author_id: str | None = None
    subject_ids: tuple[str, ...] = ()   # sujets explicitement présents (G-1)
    org_id: str | None = None
    thread_id: str | None = None
    position_in_thread: int | None = None
    timestamp: str | None = None        # ISO 8601 UTC
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_subject_ids(self) -> Document:
        if any(not subject_id for subject_id in self.subject_ids):
            raise ValueError("subject_ids ne peut pas contenir d'identifiant vide")
        if len(set(self.subject_ids)) != len(self.subject_ids):
            raise ValueError("subject_ids doit être sans doublon")
        return self

    @model_serializer(mode="wrap")
    def _serialize_without_empty_subjects(self, handler: Any) -> dict[str, Any]:
        data = cast(dict[str, Any], handler(self))
        if not self.subject_ids:
            data.pop("subject_ids", None)
        return data


# --------------------------------------------------------------------------- #
# annotations.jsonl
# --------------------------------------------------------------------------- #
class Annotation(BaseModel):
    model_config = _BASE

    annotation_id: str
    doc_id: str
    subject_id: str | None = None   # sujet porteur de cette PII (G-1)
    start: int | None = None
    end: int | None = None
    span_text: str | None = None
    identifier_type: IdentifierType
    qi_categories: tuple[str, ...]
    expression_mode: ExpressionMode
    sensitivity: Sensitivity = Sensitivity.NONE
    granularity: Granularity
    stability: Stability
    subject: Subject = Subject.SELF
    value_normalized: dict[str, Any] | None = None
    entity_id: str | None = None
    annotator_id: str | None = None
    confidence: float = 1.0
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def _serialize_without_empty_subject(self, handler: Any) -> dict[str, Any]:
        data = cast(dict[str, Any], handler(self))
        if self.subject_id is None:
            data.pop("subject_id", None)
        return data
    @model_validator(mode="after")
    def _check(self) -> Annotation:
        if not self.qi_categories:
            raise ValueError("qi_categories doit contenir au moins un code")
        for code in self.qi_categories:
            validate_code(code)

        check_direct_exclusivity(self.identifier_type, self.qi_categories)

        # I-ANN-2 : une annotation sans offset n'est admise qu'en mode IMPLICIT
        # (inférence au niveau document — exigence SynthPAI).
        has_offsets = self.start is not None and self.end is not None
        if not has_offsets and self.expression_mode is not ExpressionMode.IMPLICIT:
            raise ValueError(
                "I-ANN-2 violé : annotation sans offsets alors que "
                f"expression_mode={self.expression_mode.value}"
            )
        if has_offsets and self.end <= self.start:  # type: ignore[operator]
            raise ValueError("I-ANN-1 violé : end doit être strictement supérieur à start")

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence doit être dans [0, 1]")
        return self

    def check_against_text(self, text: str) -> None:
        """Invariant I-ANN-1 — à appeler avec le texte du document.

        Violation = échec d'ingestion (E-VAL-101), jamais un avertissement :
        des offsets décalés invalideraient silencieusement toutes les métriques
        de détection.
        """
        if self.start is None or self.end is None:
            return
        if self.end > len(text):
            raise ValueError(f"I-ANN-1 violé : end={self.end} dépasse len(text)={len(text)}")
        if self.span_text is not None and text[self.start : self.end] != self.span_text:
            raise ValueError(
                "I-ANN-1 violé : "
                f"text[{self.start}:{self.end}]={text[self.start:self.end]!r} "
                f"!= span_text={self.span_text!r}"
            )


# --------------------------------------------------------------------------- #
# profiles.jsonl / organizations.jsonl
# --------------------------------------------------------------------------- #
class AttributeValue(BaseModel):
    model_config = _BASE

    value: Any
    normalized: dict[str, Any] | None = None


class Profile(BaseModel):
    model_config = _BASE

    person_id: str
    dataset: str
    population_id: str
    org_id: str | None = None
    pseudonym: str | None = None
    attributes: dict[str, AttributeValue]
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> Profile:
        for code in self.attributes:
            validate_code(code)
        return self


class Organization(BaseModel):
    model_config = _BASE

    org_id: str
    dataset: str
    population_id: str
    attributes: dict[str, AttributeValue]
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> Organization:
        for code in self.attributes:
            validate_code(code)
        return self


# --------------------------------------------------------------------------- #
# combinations.jsonl — la table qui porte la contribution du projet
# --------------------------------------------------------------------------- #
class QiValue(BaseModel):
    model_config = _BASE

    qi_category: str
    normalized: dict[str, Any]

    @model_validator(mode="after")
    def _check(self) -> QiValue:
        validate_code(self.qi_category)
        return self


class Combination(BaseModel):
    model_config = _BASE

    combination_id: str
    dataset: str
    target_type: TargetType
    target_id: str
    scope: Scope
    doc_ids: tuple[str, ...]
    qi_set: tuple[QiValue, ...]
    k_true: int | None = None
    risk_true: float | None = None
    risk_model: RiskModel
    population_id: str
    at_risk: bool
    source: CombinationSource
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> Combination:
        if not self.qi_set:
            raise ValueError("qi_set doit contenir au moins un élément")

        # I-CMB-2 : cohérence risque / k en modèle prosecutor.
        if (
            self.risk_model is RiskModel.PROSECUTOR
            and self.k_true is not None
            and self.risk_true is not None
        ):
            expected = 1.0 / self.k_true
            if abs(self.risk_true - expected) > 1e-6:
                raise ValueError(
                    f"I-CMB-2 violé : risk_true={self.risk_true} != 1/k_true={expected}"
                )
        return self


# --------------------------------------------------------------------------- #
# tasks.jsonl
# --------------------------------------------------------------------------- #
class LabelType(str, Enum):
    SINGLE = "single"
    MULTI = "multi"
    REGRESSION = "regression"


class TaskLabel(BaseModel):
    model_config = _BASE

    doc_id: str
    task: str
    label: str | tuple[str, ...] | float
    label_type: LabelType
    meta: dict[str, Any] = Field(default_factory=dict)

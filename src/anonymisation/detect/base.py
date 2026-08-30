"""Contrat commun des détecteurs déterministes.

Implémentation de la couche de détection décrite dans le cahier des charges de
la Sprint « détection ». Cette couche est **hors ligne, sans LLM et sans
modèle lourd** : c'est la leçon principale de l'audit du dépôt v1, qui a
échoué avec 84 à 100 % de taux d'erreur en s'appuyant sur des LLM (timeouts,
JSON vide, contexte saturé).

Invariant absolu (audit §12.2, repris ici) :

    TOUS LES OFFSETS (``Candidate.start`` / ``Candidate.end``) RÉFÈRENT AU
    TEXTE ORIGINAL tel que reçu par ``Detector.detect``. Aucune étape
    intermédiaire (normalisation, découpage, nettoyage) ne doit décaler ces
    offsets sans les recalculer explicitement sur le texte d'origine. Toute
    violation de cet invariant casse silencieusement I-ANN-1 (SPEC-02 §5) en
    aval, au moment de l'ingestion des annotations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

from anonymisation.schema.models import Annotation
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Sensitivity,
    Stability,
    validate_code,
)


@dataclass(frozen=True)
class Candidate:
    """Détection brute produite par un détecteur, avant fusion.

    Les offsets ``start``/``end`` réfèrent toujours au texte original (voir
    l'invariant documenté en tête de module). ``end`` est exclusif, comme
    pour les slices Python et comme l'exige SPEC-02 §5.
    """

    start: int
    end: int
    text: str
    qi_category: str
    identifier_type: IdentifierType
    source: str                          # ex. "regex:email", "rule:age_fr"
    confidence: float
    granularity: Granularity
    stability: Stability
    expression_mode: ExpressionMode = ExpressionMode.EXPLICIT
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(
                f"Candidate invalide : end={self.end} <= start={self.start} "
                f"(source={self.source!r})"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Candidate invalide : confidence={self.confidence} hors [0,1] "
                f"(source={self.source!r})"
            )
        # Valide le code dès la construction : un code inconnu doit échouer
        # tôt, pas silencieusement plus loin dans le pipeline.
        validate_code(self.qi_category)

    @property
    def length(self) -> int:
        return self.end - self.start


@runtime_checkable
class Detector(Protocol):
    """Contrat minimal qu'implémente tout détecteur déterministe.

    ``language`` est un code ISO 639-1 (« fr », « en », ...). Un détecteur qui
    ne gère pas une langue donnée DOIT retourner une séquence vide plutôt que
    de lever une exception : l'absence de couverture linguistique n'est pas
    une erreur, c'est une limite documentée.
    """

    name: str

    def detect(self, text: str, language: str) -> Sequence[Candidate]:
        ...


def candidates_to_annotations(
    candidates: Sequence[Candidate],
    doc_id: str,
    text: str,
) -> list[Annotation]:
    """Convertit des ``Candidate`` post-fusion en ``Annotation`` SPEC-02.

    Chaque annotation produite est vérifiée avec ``check_against_text`` : si
    les offsets d'un candidat ne correspondent plus au texte fourni (violation
    de l'invariant documenté en tête de module), la conversion échoue plutôt
    que de produire une annotation silencieusement fausse.
    """
    annotations: list[Annotation] = []
    for index, candidate in enumerate(candidates):
        sensitivity_raw = candidate.meta.get("sensitivity")
        sensitivity = Sensitivity(sensitivity_raw) if sensitivity_raw else Sensitivity.NONE
        extra_meta = {
            k: v
            for k, v in candidate.meta.items()
            if k not in ("value_normalized", "sensitivity")
        }
        annotation = Annotation(
            annotation_id=f"{doc_id}:det:{index}",
            doc_id=doc_id,
            start=candidate.start,
            end=candidate.end,
            span_text=candidate.text,
            identifier_type=candidate.identifier_type,
            qi_categories=(candidate.qi_category,),
            expression_mode=candidate.expression_mode,
            sensitivity=sensitivity,
            granularity=candidate.granularity,
            stability=candidate.stability,
            value_normalized=candidate.meta.get("value_normalized"),
            confidence=candidate.confidence,
            meta={"source": candidate.source, **extra_meta},
        )
        annotation.check_against_text(text)
        annotations.append(annotation)
    return annotations

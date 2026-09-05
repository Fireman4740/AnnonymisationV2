"""Contrats d'étape du pipeline d'anonymisation (SPEC-10 §4).

Ce module regroupe les structures immuables qui circulent entre les huit
étapes du pipeline, ainsi que leur sérialisation JSONL :

- :class:`StageTrace` — la trace laissée par une étape sur un document.
  Acquis de la v1 que l'audit §12.3 impose de conserver : chaque étape
  laisse une trace auditable (ajouts, suppressions, décisions) sans
  dépendre d'un moteur de graphe ;
- :class:`RiskAssessment` — la sortie de l'étape ASSESS. Tant que le
  moteur de risque complet de SPEC-06 n'est pas disponible, la valeur est
  marquée ``status="PROXY"`` (SPEC-07 §9) : elle ne doit jamais être
  présentée à côté de chiffres officiels ;
- :class:`PipelineResult` — le résultat d'une exécution complète sur un
  document.

**Invariant des offsets (SPEC-10 §4)** : tous les offsets portés par ces
structures (``start``/``end`` des annotations et des décisions) réfèrent au
texte **original** du document, jamais au texte anonymisé. La
transformation est appliquée de droite à gauche par ``transform.apply``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from anonymisation.schema.models import Annotation
from anonymisation.transform.decisions import AnonymizationDecision

#: Ordre canonique des huit étapes (SPEC-10 §3).
STAGE_ORDER: Final[tuple[str, ...]] = (
    "DETECT",
    "FUSE",
    "ASSESS",
    "PLAN",
    "TRANSFORM",
    "VALIDATE",
    "AUDIT",
    "REWRITE",
)

#: Étapes 1 à 6 : obligatoires pour tout profil (audit §12.1 — sans
#: détection, fusion, planification ni transformation, aucune garantie).
CORE_STAGES: Final[tuple[str, ...]] = STAGE_ORDER[:6]

#: Étapes 7 à 8 : LLM, désactivées par défaut (SPEC-10, contraintes C1-C2).
LLM_STAGES: Final[tuple[str, ...]] = STAGE_ORDER[6:]

#: Statuts possibles d'une trace d'étape.
STAGE_STATUSES: Final[tuple[str, ...]] = ("ok", "skipped", "error")

#: Statuts possibles du résultat d'un document.
#:
#: - ``ok`` — les six étapes obligatoires ont abouti, aucun problème ;
#: - ``partial`` — le document a été anonymisé mais VALIDATE a signalé un
#:   problème (fuite, placeholder malformé) sans l'interrompre
#:   (``fail_on_leak=false``) ;
#: - ``error`` — une étape a échoué (ou VALIDATE a interrompu avec
#:   ``fail_on_leak=true``) : le document est exclu de toutes les métriques
#:   (audit §12.5, SPEC-10 §9).
PIPELINE_STATUSES: Final[tuple[str, ...]] = ("ok", "partial", "error")


def entity_key(category: str, start: int, end: int) -> str:
    """Clé stable d'une entité pour les traces : ``<catégorie>:<start>:<end>``.

    Permet de lister dans ``added``/``removed``/``modified`` ce qu'une étape
    a introduit, supprimé ou modifié, sans exposer les surfaces dans les
    métadonnées.
    """
    return f"{category}:{start}:{end}"


@dataclass(frozen=True)
class StageTrace:
    """Trace laissée par une étape sur un document (SPEC-10 §4).

    ``added`` / ``removed`` / ``modified`` sont des clés d'entité
    (cf. :func:`entity_key`) ; ``decisions`` regroupe les décisions
    auditables de l'étape (fusion, anonymisation) sous forme de dictionnaires
    JSON-serialisables.

    ``sha256_before`` / ``sha256_after`` sont les empreintes de l'*état du
    texte* à l'entrée / à la sortie de l'étape : les quatre premières étapes
    ne modifient pas le texte (les deux valeurs y sont donc égales), seule
    TRANSFORM les sépare. Les durées sont mesurées mais non déterministes :
    en profil strict, la sérialisation les remplace par zéro (SPEC-10 §10).
    """

    stage: str
    order: int
    entities_in: int
    entities_out: int
    duration_ms: float
    sha256_before: str
    sha256_after: str
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    decisions: tuple[dict[str, Any], ...] = ()
    status: str = "ok"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Forme JSONL d'une ligne de ``traces.jsonl``."""
        return {
            "stage": self.stage,
            "order": self.order,
            "entities_in": self.entities_in,
            "entities_out": self.entities_out,
            "duration_ms": self.duration_ms,
            "sha256_before": self.sha256_before,
            "sha256_after": self.sha256_after,
            "added": list(self.added),
            "removed": list(self.removed),
            "modified": list(self.modified),
            "decisions": list(self.decisions),
            "status": self.status,
            "error": self.error,
        }


@dataclass(frozen=True)
class RiskAssessment:
    """Estimation du risque de ré-identification d'un document (étape ASSESS).

    Le moteur de la v1 est l'estimateur *naïf* (produit des sélectivités sur
    une population de taille N) : la valeur est donc marquée
    ``status="PROXY"``. SPEC-07 §9 impose qu'aucun chiffre PROXY ne soit
    publié à côté de chiffres officiels tant que l'étalonnage (L4) n'est pas
    fait.
    """

    assessment_id: str
    population_id: str | None
    population_size: int
    k_hat: float
    risk: float
    worst_category: str | None
    worst_risk: float | None
    status: str = "PROXY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "population_id": self.population_id,
            "population_size": self.population_size,
            "k_hat": self.k_hat,
            "risk": self.risk,
            "worst_category": self.worst_category,
            "worst_risk": self.worst_risk,
            "status": self.status,
        }


@dataclass(frozen=True)
class PipelineResult:
    """Résultat de l'exécution complète du pipeline sur un document (SPEC-10 §4).

    - ``original_text`` et les offsets de ``annotations`` / ``decisions``
      réfèrent toujours au texte original (invariant SPEC-10 §4) ;
    - ``anonymized_text`` est le texte réellement produit. Si une erreur est
      intervenue **avant** TRANSFORM, c'est le texte original (l'anonymisation
      n'a pas eu lieu) et la ligne porte ``status="error"`` avec l'étape en
      cause dans ``errors`` — jamais une prédiction vide silencieuse
      (audit §12.5 : un document en erreur n'est jamais compté comme une
      prédiction) ;
    - ``errors`` suit la convention ``"ÉTAPE: détail"`` afin que la
      comptabilité d'exécution (``metrics/accounting.py``) puisse imputer
      chaque échec à son étape.
    """

    doc_id: str
    original_text: str
    anonymized_text: str
    annotations: tuple[Annotation, ...]
    decisions: tuple[AnonymizationDecision, ...]
    risk: RiskAssessment | None
    policy_id: str
    traces: tuple[StageTrace, ...]
    status: str
    errors: tuple[str, ...] = ()
    runtime_ms: float = 0.0
    #: Identité du système ayant produit ce résultat
    #: (``anonymisation.systems.base.SystemIdentity``). Le défaut ``None``
    #: n'est là que pour ne pas contraindre l'ordre des champs : la
    #: sérialisation **refuse** un résultat non estampillé, car le scorer ne
    #: saurait pas quelles métriques sont applicables. Typé ``Any`` pour ne
    #: pas importer ``systems`` ici — ``pipeline`` ne doit pas dépendre des
    #: implémentations qu'il sert.
    identity: Any | None = None


def serialize_annotation(annotation: Annotation) -> dict[str, Any]:
    """Forme JSON d'une annotation (valeurs, jamais de références)."""
    return annotation.model_dump(mode="json")


def serialize_decision(decision: AnonymizationDecision) -> dict[str, Any]:
    """Forme JSON d'une décision d'anonymisation."""
    return {
        "start": decision.start,
        "end": decision.end,
        "original": decision.original,
        "action": decision.action.value,
        "replacement": decision.replacement,
        "qi_category": decision.qi_category,
        "reason": decision.reason,
        "risk_before": decision.risk_before,
        "risk_after": decision.risk_after,
        "meta": dict(decision.meta),
    }


def serialize_stage_trace(trace: StageTrace, *, strict: bool = False) -> dict[str, Any]:
    """Forme JSONL d'une ligne de ``traces.jsonl``.

    En profil strict, la durée (mesurée mais non déterministe) est nulle :
    deux runs doivent produire des fichiers bit-à-bit identiques (SPEC-10
    §10). En mode non strict, la durée mesurée est conservée (informationnelle).
    """
    payload = trace.to_dict()
    if strict:
        payload["duration_ms"] = 0.0
    return payload


def serialize_pipeline_result(result: PipelineResult, *, strict: bool = False) -> dict[str, Any]:
    """Une ligne de ``predictions.jsonl`` (SPEC-10 §5).

    ``error`` est toujours présent : liste vide pour une ligne ``ok``, liste
    des pannes sinon — une ligne en erreur ne peut pas être confondue avec
    une prédiction vide d'annotations (audit §12.5).

    ``strict`` : profil déterministe strict (SPEC-10 §10) — ``runtime_ms``
    (horloge, non déterministe) est mis à zéro pour garantir un replay bit-à-bit.
    """
    if result.identity is None:
        raise ValueError(
            f"Document {result.doc_id!r} : PipelineResult sans identité de "
            f"système. Un résultat non estampillé ne peut pas être écrit dans "
            f"predictions.jsonl — le scorer ne saurait pas quelles métriques "
            f"sont applicables et publierait des zéros trompeurs."
        )
    return {
        "doc_id": result.doc_id,
        "status": result.status,
        "system": result.identity.to_dict(),
        "error": list(result.errors),
        "annotations": [serialize_annotation(a) for a in result.annotations],
        "decisions": [serialize_decision(d) for d in result.decisions],
        "anonymized_text": result.anonymized_text,
        "risk": result.risk.to_dict() if result.risk is not None else None,
        "runtime_ms": 0.0 if strict else result.runtime_ms,
    }

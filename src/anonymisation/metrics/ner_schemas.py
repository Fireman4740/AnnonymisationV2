"""Schémas de correspondance de spans délégués à ``nervaluate`` (EPIC-H H-8).

La v1 réimplémentait SemEval-2013 task 9.1 et s'en écartait : son ``partial``
exigeait une catégorie compatible, alors que le ``partial`` original ignore le
type. On appelle désormais le paquet de référence, à une version épinglée, au
travers d'un adaptateur explicite :

* **offsets** — le pivot a des fins **exclusives** (``text[start:end]``),
  nervaluate des fins **incluses** (deux spans qui se touchent se chevauchent) :
  ``end`` devient ``end - 1`` ;
* **étiquettes** — une annotation porte une ou plusieurs catégories (I-ANN-5) ;
  chaque couple (span, catégorie) devient une entité nervaluate, côté gold comme
  côté prédiction (``llm-full`` émet déjà une décision par catégorie) ;
* **annotations sans offsets** (attribut inféré au niveau document) — elles ne
  sont pas des spans : exclues et comptées (``unanchored_gold``).

Les quatre schémas sont publiés séparément : ``exact`` et ``partial`` mesurent la
**localisation** (type ignoré), ``ent_type`` et ``strict`` la
**classification**. Les comptes nervaluate sont additifs entre documents : la
somme des comptes par document redonne exactement l'évaluation du corpus,
ce qui permet le bootstrap par document.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any, Final

from anonymisation.metrics.entities import SpanLike, bounds, categories

SCHEMAS: Final[tuple[str, ...]] = ("strict", "exact", "partial", "ent_type")
#: Rôle de chaque schéma dans la scorecard.
SCHEMA_ROLE: Final[Mapping[str, str]] = {
    "exact": "localisation (bornes exactes, type ignoré)",
    "partial": "localisation (chevauchement à demi-crédit, type ignoré)",
    "ent_type": "classification (chevauchement, type exact)",
    "strict": "classification (bornes et type exacts)",
}
NERVALUATE_PIN: Final[str] = "1.2.1"


class NervaluateVersionError(RuntimeError):
    """Version de nervaluate différente de la version épinglée."""


def _checked_evaluator() -> Any:
    installed = version("nervaluate")
    if installed != NERVALUATE_PIN:
        raise NervaluateVersionError(
            f"nervaluate {installed} installé, {NERVALUATE_PIN} épinglé : les schémas "
            "ont changé entre versions — `uv sync --locked`."
        )
    from nervaluate import Evaluator

    return Evaluator


@dataclass(frozen=True)
class SchemaCounts:
    """Comptes nervaluate d'un schéma : additifs entre documents."""

    correct: int = 0
    incorrect: int = 0
    partial: int = 0
    missed: int = 0
    spurious: int = 0
    possible: int = 0
    actual: int = 0

    def __add__(self, other: SchemaCounts) -> SchemaCounts:
        return SchemaCounts(**{
            name: getattr(self, name) + getattr(other, name)
            for name in self.__dataclass_fields__
        })

    def credit(self, schema: str) -> float:
        """Numérateur de précision et de rappel (demi-crédit pour ``partial``)."""
        return self.correct + (0.5 * self.partial if schema == "partial" else 0.0)

    def scores(self, schema: str) -> dict[str, float | None]:
        credit = self.credit(schema)
        precision = credit / self.actual if self.actual else None
        recall = credit / self.possible if self.possible else None
        if precision is None or recall is None:
            f1 = None
        else:
            f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        return {"precision": precision, "recall": recall, "f1": f1}

    def to_dict(self, schema: str) -> dict[str, Any]:
        return {**{name: getattr(self, name) for name in self.__dataclass_fields__},
                **self.scores(schema)}


def to_entities(spans: Iterable[SpanLike]) -> tuple[list[dict[str, Any]], int]:
    """Adaptateur pivot → nervaluate : une entité par (span, catégorie), fin incluse."""
    entities: list[dict[str, Any]] = []
    unanchored = 0
    for span in spans:
        span_bounds = bounds(span)
        if span_bounds is None:
            unanchored += 1
            continue
        start, end = span_bounds
        for label in sorted(categories(span)):
            entities.append({"label": label, "start": start, "end": end - 1})
    entities.sort(key=lambda e: (e["start"], e["end"], e["label"]))
    return entities, unanchored


def document_counts(
    gold: Sequence[SpanLike], pred: Sequence[SpanLike]
) -> tuple[dict[str, SchemaCounts], int]:
    """Comptes des quatre schémas pour **un** document, et gold sans offsets."""
    gold_entities, unanchored = to_entities(gold)
    pred_entities, _ = to_entities(pred)
    tags = sorted({e["label"] for e in (*gold_entities, *pred_entities)})
    if not tags:
        return {schema: SchemaCounts() for schema in SCHEMAS}, unanchored
    evaluator = _checked_evaluator()(
        [gold_entities], [pred_entities], tags=tags, loader="dict"
    )
    overall = evaluator.evaluate()["overall"]
    counts = {
        schema: SchemaCounts(
            correct=overall[schema].correct, incorrect=overall[schema].incorrect,
            partial=overall[schema].partial, missed=overall[schema].missed,
            spurious=overall[schema].spurious, possible=overall[schema].possible,
            actual=overall[schema].actual,
        )
        for schema in SCHEMAS
    }
    return counts, unanchored


def corpus_counts(
    rows: Iterable[tuple[Sequence[SpanLike], Sequence[SpanLike]]],
) -> tuple[dict[str, SchemaCounts], list[dict[str, SchemaCounts]], int]:
    """Comptes du corpus, comptes par document (bootstrap) et gold sans offsets."""
    total = {schema: SchemaCounts() for schema in SCHEMAS}
    per_document: list[dict[str, SchemaCounts]] = []
    unanchored = 0
    for gold, pred in rows:
        counts, missing = document_counts(gold, pred)
        per_document.append(counts)
        unanchored += missing
        total = {schema: total[schema] + counts[schema] for schema in SCHEMAS}
    return total, per_document, unanchored


def schema_report(total: Mapping[str, SchemaCounts], unanchored: int) -> dict[str, Any]:
    """Bloc ``details`` publiable : quatre schémas, rôle, adaptateur, version."""
    return {
        "nervaluate_version": NERVALUATE_PIN,
        "adapter": "fin exclusive → incluse (end-1) ; une entité par (span, catégorie)",
        "unanchored_gold": unanchored,
        "schemas": {
            schema: {"role": SCHEMA_ROLE[schema], **total[schema].to_dict(schema)}
            for schema in SCHEMAS
        },
    }


__all__ = [
    "NERVALUATE_PIN",
    "SCHEMAS",
    "SchemaCounts",
    "corpus_counts",
    "document_counts",
    "schema_report",
    "to_entities",
]

"""Métriques de détection au niveau span (SPEC-07 §2, EPIC-D D-1).

Le mode de correspondance est toujours renvoyé dans le résultat. Les
correspondances ``exact`` et ``overlap`` sont injectives : une prédiction ne
peut pas compter deux fois pour deux annotations gold.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from anonymisation.metrics.entities import (
    SpanLike,
    bounds,
    categories,
    field_value,
    group_entities,
    overlaps,
    same_category,
)

_MATCH_MODES = frozenset({"exact", "partial", "overlap", "entity"})
_TOKEN_RE = re.compile(r"\S+")


def _exact_match(gold: SpanLike, pred: SpanLike) -> bool:
    return bounds(gold) == bounds(pred) and same_category(gold, pred)


def _candidate_match(gold: SpanLike, pred: SpanLike, mode: str) -> bool:
    if mode == "exact":
        return _exact_match(gold, pred)
    return overlaps(gold, pred) and same_category(gold, pred)


def _matching_pairs(
    gold: Sequence[SpanLike],
    pred: Sequence[SpanLike],
    mode: str,
) -> frozenset[tuple[int, int]]:
    """Retourne un appariement injectif maximal et déterministe."""
    adjacency = [
        [
            index
            for index, pred_span in enumerate(pred)
            if _candidate_match(gold_span, pred_span, mode)
        ]
        for gold_span in gold
    ]
    holder_of: dict[int, int] = {}

    def _augment(gold_index: int, visited: set[int]) -> bool:
        for pred_index in adjacency[gold_index]:
            if pred_index in visited:
                continue
            visited.add(pred_index)
            holder = holder_of.get(pred_index)
            if holder is None or _augment(holder, visited):
                holder_of[pred_index] = gold_index
                return True
        return False

    for gold_index in range(len(gold)):
        _augment(gold_index, set())
    return frozenset((gold_index, pred_index) for pred_index, gold_index in holder_of.items())


def _one_to_one_counts(
    gold: Sequence[SpanLike], pred: Sequence[SpanLike], mode: str
) -> tuple[int, int, int]:
    pairs = _matching_pairs(gold, pred, mode)
    true_positive = len(pairs)
    return true_positive, len(pred) - true_positive, len(gold) - true_positive


def _partial_counts(
    gold: Sequence[SpanLike], pred: Sequence[SpanLike]
) -> tuple[float, int, int, int]:
    """Compte exacts/partiels selon SemEval-2013 task 9.1.

    Un span partiellement recouvert compte pour 0,5 dans le numerateur de
    precision et de rappel, tout en consommant un gold et une prediction.
    """
    exact_pairs = _matching_pairs(gold, pred, "exact")
    used_gold = {gold_index for gold_index, _ in exact_pairs}
    used_pred = {pred_index for _, pred_index in exact_pairs}
    remaining_gold = [index for index in range(len(gold)) if index not in used_gold]
    remaining_pred = [index for index in range(len(pred)) if index not in used_pred]
    partial_gold = [gold[index] for index in remaining_gold]
    partial_pred = [pred[index] for index in remaining_pred]
    partial_pairs = _matching_pairs(partial_gold, partial_pred, "partial")
    correct = len(exact_pairs)
    partial = len(partial_pairs)
    matched = correct + partial
    return correct + 0.5 * partial, correct, partial, matched


def _entity_counts(gold: Sequence[SpanLike], pred: Sequence[SpanLike]) -> tuple[int, int, int]:
    gold_groups = group_entities(gold)
    pred_groups = group_entities(pred)
    matched_gold = 0
    for mentions in gold_groups.values():
        # Une entité est protégée uniquement si aucune de ses mentions ne fuit.
        if all(
            any(
                same_category(gold_mention, prediction)
                and (
                    overlaps(gold_mention, prediction)
                    or (
                        field_value(gold_mention, "entity_id") is not None
                        and field_value(gold_mention, "entity_id")
                        == field_value(prediction, "entity_id")
                    )
                )
                for prediction in pred
            )
            for gold_mention in mentions
        ):
            matched_gold += 1
    matched_pred = 0
    for mentions in pred_groups.values():
        if any(
            same_category(gold_mention, prediction)
            and (
                overlaps(gold_mention, prediction)
                or (
                    field_value(gold_mention, "entity_id") is not None
                    and field_value(gold_mention, "entity_id")
                    == field_value(prediction, "entity_id")
                )
            )
            for gold_mention in gold
            for prediction in mentions
        ):
            matched_pred += 1
    return matched_gold, len(pred_groups) - matched_pred, len(gold_groups) - matched_gold


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _f_score(precision: float | None, recall: float | None, beta: float) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return 0.0 if precision == recall == 0.0 else None
    beta_squared = beta * beta
    return (1 + beta_squared) * precision * recall / (beta_squared * precision + recall)


def span_metrics(
    gold: Iterable[SpanLike],
    pred: Iterable[SpanLike],
    *,
    match: str = "partial",
) -> dict[str, Any]:
    """Retourne les métriques span-level avec le mode déclaré.

    ``partial`` suit SemEval-2013 task 9.1 : un chevauchement de bornes avec
    label compatible vaut 0,5 en precision et rappel ; ``overlap`` est
    conservé comme alias historique à crédit plein. ``entity`` exige que
    toutes les mentions d'une entité soient couvertes.
    """
    if match not in _MATCH_MODES:
        raise ValueError(
            f"Mode de correspondance inconnu : {match!r} "
            "(choix : exact, partial, overlap, entity)"
        )
    gold_values = tuple(gold)
    pred_values = tuple(pred)
    partial_count = 0
    correct_count = 0
    tp = 0.0
    fp = 0.0
    fn = 0.0
    if match == "entity":
        entity_tp, entity_fp, entity_fn = _entity_counts(gold_values, pred_values)
        tp = float(entity_tp)
        fp = float(entity_fp)
        fn = float(entity_fn)
        correct_count = entity_tp
    elif match == "partial":
        tp, correct_count, partial_count, _ = _partial_counts(gold_values, pred_values)
        fp = len(pred_values) - correct_count - 0.5 * partial_count
        fn = len(gold_values) - correct_count - 0.5 * partial_count
    else:
        exact_tp, exact_fp, exact_fn = _one_to_one_counts(gold_values, pred_values, match)
        tp = float(exact_tp)
        fp = float(exact_fp)
        fn = float(exact_fn)
        correct_count = exact_tp
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    return {
        "match": match,
        "mode": match,
        "tp": tp,
        "correct": correct_count,
        "partial": partial_count,
        "fp": fp,
        "fn": fn,
        "gold": len(gold_values) if match != "entity" else len(group_entities(gold_values)),
        "pred": len(pred_values) if match != "entity" else len(group_entities(pred_values)),
        "precision": precision,
        "recall": recall,
        "f1": _f_score(precision, recall, 1.0),
        "f2": _f_score(precision, recall, 2.0),
    }


def weighted_token_precision(
    gold: Iterable[SpanLike], pred: Iterable[SpanLike], text: str
) -> float | None:
    """Précision token-level pondérée par la longueur des tokens.

    Le poids proxy est le nombre de caractères du token : il est déterministe,
    indépendant d'un modèle externe, et pénalise davantage les faux positifs
    qui exposent une longue séquence. Les tokens prédits sont ceux qui
    intersectent un span prédit ; un token est correct s'il intersecte un span
    gold.

    Retourne ``None`` quand aucun token n'est prédit : le dénominateur est
    vide, la précision n'est pas définie. Renvoyer ``0.0`` ferait chuter la
    moyenne d'un système qui, à raison, ne prédit rien sur un document sans
    identifiant (même règle que les rappels sans gold).
    """
    gold_values = tuple(gold)
    pred_values = tuple(pred)
    predicted_weight = 0
    true_weight = 0
    for token_match in _TOKEN_RE.finditer(text):
        token_start, token_end = token_match.span()
        token_weight = token_end - token_start
        predicted = any(
            (span_bounds := bounds(span)) is not None
            and span_bounds[0] < token_end
            and token_start < span_bounds[1]
            for span in pred_values
        )
        if not predicted:
            continue
        predicted_weight += token_weight
        if any(
            (span_bounds := bounds(span)) is not None
            and span_bounds[0] < token_end
            and token_start < span_bounds[1]
            for span in gold_values
        ):
            true_weight += token_weight
    return true_weight / predicted_weight if predicted_weight else None


def category_metrics(
    gold: Iterable[SpanLike], pred: Iterable[SpanLike], category: str, *, match: str = "partial"
) -> dict[str, Any]:
    """Calcule les métriques d'une catégorie, avec ``None`` si gold absent."""
    gold_values = tuple(
        span for span in gold if category in categories(span)
    )
    pred_values = tuple(
        span for span in pred if category in categories(span)
    )
    result = span_metrics(gold_values, pred_values, match=match)
    result["category"] = category
    return result

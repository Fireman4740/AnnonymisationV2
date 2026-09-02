"""Métriques au niveau entité (SPEC-07 §2, EPIC-D D-1).

Les fonctions acceptent aussi bien les modèles ``Annotation`` que les mappings
JSON issus de ``predictions.jsonl``. Les offsets restent la source de vérité
pour la correspondance ; ``entity_id`` permet de relier plusieurs mentions.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypeAlias

from anonymisation.schema.taxonomy import IdentifierType

SpanLike: TypeAlias = Any
EntityKey: TypeAlias = tuple[str, str]


def field_value(item: SpanLike, name: str, default: Any = None) -> Any:
    """Lit un champ d'un modèle ou d'une ligne JSON."""
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def enum_value(value: Any) -> Any:
    """Retourne la valeur d'un enum ou la valeur brute."""
    return getattr(value, "value", value)


def identifier_value(item: SpanLike) -> str | None:
    value = enum_value(field_value(item, "identifier_type"))
    return str(value) if value is not None else None


def categories(item: SpanLike) -> frozenset[str]:
    values = field_value(item, "qi_categories", ()) or ()
    return frozenset(str(enum_value(value)) for value in values)


def bounds(item: SpanLike) -> tuple[int, int] | None:
    start = field_value(item, "start")
    end = field_value(item, "end")
    if start is None or end is None:
        return None
    try:
        start_i, end_i = int(start), int(end)
    except (TypeError, ValueError):
        return None
    if end_i <= start_i:
        return None
    return start_i, end_i


def overlaps(left: SpanLike, right: SpanLike) -> bool:
    """Indique si deux spans ont une intersection non vide."""
    left_bounds = bounds(left)
    right_bounds = bounds(right)
    if left_bounds is None or right_bounds is None:
        return False
    return left_bounds[0] < right_bounds[1] and right_bounds[0] < left_bounds[1]


def same_category(left: SpanLike, right: SpanLike) -> bool:
    """Les labels partagent-ils au moins une catégorie taxonomique ?"""
    left_categories = categories(left)
    right_categories = categories(right)
    if left_categories and right_categories:
        return bool(left_categories & right_categories)
    left_type = identifier_value(left)
    right_type = identifier_value(right)
    return left_type is not None and left_type == right_type


def same_identifier_type(item: SpanLike, identifier_type: IdentifierType | str) -> bool:
    wanted = str(enum_value(identifier_type))
    return identifier_value(item) == wanted


def entity_key(item: SpanLike, index: int = 0) -> EntityKey:
    """Construit une clé d'entité stable quand le corpus n'a pas d'ID.

    Les annotateurs qui fournissent ``entity_id`` sont prioritaires. Sinon la
    valeur normalisée, puis le texte de span, relient les mentions identiques.
    Le suffixe d'index évite de fusionner des annotations complètement
    anonymes et sans valeur.
    """
    explicit = field_value(item, "entity_id")
    if explicit is not None and str(explicit):
        return "id", str(explicit)
    normalized = field_value(item, "value_normalized")
    if normalized:
        try:
            value = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            value = repr(normalized)
        return "normalized", f"{identifier_value(item)}:{value}"
    span_text = field_value(item, "span_text")
    if span_text:
        return "text", f"{identifier_value(item)}:{span_text}"
    return "anonymous", f"{identifier_value(item)}:{index}"


def group_entities(
    spans: Iterable[SpanLike], *, identifier_type: IdentifierType | str | None = None
) -> dict[EntityKey, tuple[SpanLike, ...]]:
    """Regroupe des mentions par ``entity_id`` ou empreinte de valeur."""
    groups: dict[EntityKey, list[SpanLike]] = defaultdict(list)
    wanted = None if identifier_type is None else str(enum_value(identifier_type))
    for index, span in enumerate(spans):
        if wanted is not None and identifier_value(span) != wanted:
            continue
        groups[entity_key(span, index)].append(span)
    return {key: tuple(values) for key, values in groups.items()}


def _mention_matches(gold: SpanLike, pred: Sequence[SpanLike]) -> bool:
    gold_entity = field_value(gold, "entity_id")
    for candidate in pred:
        candidate_entity = field_value(candidate, "entity_id")
        if (
            gold_entity is not None
            and candidate_entity is not None
            and str(gold_entity) == str(candidate_entity)
        ):
            if bounds(gold) is None or bounds(candidate) is None:
                return True
            if overlaps(gold, candidate):
                return True
            continue
        if not same_category(gold, candidate):
            continue
        if overlaps(gold, candidate):
            return True
    return False


def entity_protection_counts(
    gold: Iterable[SpanLike],
    pred: Iterable[SpanLike],
    *,
    identifier_type: IdentifierType | str,
) -> tuple[int, int]:
    """Retourne ``(entités protégées, entités gold)`` pour **un** document.

    Les offsets ne sont comparables qu'à l'intérieur d'un même document :
    appeler cette fonction sur un mélange de documents ferait « protéger » une
    mention du document A par une prédiction du document B qui se trouve aux
    mêmes offsets. Les appelants qui agrègent un corpus additionnent ces
    compteurs document par document.
    """
    gold_groups = group_entities(gold, identifier_type=identifier_type)
    if not gold_groups:
        return 0, 0
    predictions = tuple(pred)
    protected = sum(
        all(_mention_matches(mention, predictions) for mention in mentions)
        for mentions in gold_groups.values()
    )
    return protected, len(gold_groups)


def entity_recall(
    gold: Iterable[SpanLike],
    pred: Iterable[SpanLike],
    *,
    identifier_type: IdentifierType | str,
) -> float:
    """Calcule le rappel de protection au niveau entité, sur un document.

    Une entité n'est comptée comme protégée que si **toutes** ses mentions gold
    ont une correspondance prédite. Cette définition évite qu'un nom répété
    neuf fois, dont une occurrence fuit encore, soit présenté comme protégé
    (SPEC-07 §2). Une absence d'entité gold renvoie ``0.0`` ; les ventilations
    qui doivent distinguer absence et zéro utilisent ``None`` avant cet appel.

    Les offsets étant relatifs à un texte donné, ``gold`` et ``pred`` doivent
    porter sur le **même document** (voir :func:`entity_protection_counts`).
    """
    protected, total = entity_protection_counts(
        gold, pred, identifier_type=identifier_type
    )
    if not total:
        return 0.0
    return protected / total

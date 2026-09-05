"""Fusion explicable des candidats de détection.

Acquis explicite de la v1 (audit du dépôt précédent, §12) à conserver :
**toute décision de fusion est tracée**. On ne supprime jamais un candidat
sans laisser une ``FusionDecision`` expliquant pourquoi.

Point de conception important, dérivé de SPEC-02 invariant I-ANN-5 : deux
annotations d'un même document PEUVENT se chevaucher légitimement. Exemple
canonique : « infirmière au CHU de Lille » porte à la fois `GEN_OCCUPATION`
(« infirmière »), `GEN_AFFILIATION` (« CHU »/« CHU de Lille ») et `GEN_GEO`
(« Lille »). Ces trois spans se chevauchent partiellement sans que l'un
soit une erreur de l'autre.

**Décision de conception** : la fusion ne considère un chevauchement comme un
« conflit » à trancher que si les deux candidats portent la **même**
`qi_category` (ex. deux façons de repérer le même email, un email détecté à
la fois par regex et par une règle plus large). Un chevauchement entre
catégories différentes est laissé tel quel : ce n'est pas un conflit, c'est
du multi-label imbriqué légitime, et l'écraser perdrait de l'information utile
au calcul de k (SPEC-01 §6).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from anonymisation.detect.base import Candidate
from anonymisation.schema.taxonomy import IdentifierType

#: Ordre de priorité entre identifier_type quand on doit trancher un conflit
#: réel (même catégorie, spans qui se chevauchent). Un DIRECT l'emporte
#: toujours sur un QUASI, qui l'emporte sur un SENSITIVE_ONLY.
_TYPE_PRIORITY: dict[IdentifierType, int] = {
    IdentifierType.DIRECT: 3,
    IdentifierType.QUASI: 2,
    IdentifierType.SENSITIVE_ONLY: 1,
    IdentifierType.IGNORED: 0,
}

STRATEGIES: tuple[str, ...] = ("longest", "highest_score", "priority_longest", "priority_score")


@dataclass(frozen=True)
class FusionDecision:
    """Trace d'une décision de fusion : ce qui a été gardé, ce qui a été abandonné, pourquoi."""

    kept: Candidate
    dropped: tuple[Candidate, ...]
    strategy: str
    reason: str


def _overlaps(a: Candidate, b: Candidate) -> bool:
    return a.start < b.end and b.start < a.end


def _is_real_conflict(a: Candidate, b: Candidate) -> bool:
    """Un chevauchement n'est un conflit à trancher que si même catégorie.

    Voir la note de conception en tête de module (I-ANN-5).
    """
    return _overlaps(a, b) and a.qi_category == b.qi_category


def _sort_key(strategy: str) -> Callable[[Candidate], tuple[float, ...]]:
    if strategy == "longest":
        return lambda c: (float(c.length), c.confidence)
    if strategy == "highest_score":
        return lambda c: (c.confidence, float(c.length))
    if strategy == "priority_longest":
        return lambda c: (float(_TYPE_PRIORITY[c.identifier_type]), float(c.length), c.confidence)
    if strategy == "priority_score":
        return lambda c: (float(_TYPE_PRIORITY[c.identifier_type]), c.confidence, float(c.length))
    raise ValueError(f"Stratégie de fusion inconnue : {strategy!r}. Choix : {STRATEGIES}")


def _reason_for(strategy: str, kept: Candidate, dropped: Candidate) -> str:
    parts = [f"stratégie={strategy}"]
    if kept.qi_category == dropped.qi_category:
        parts.append("même catégorie, spans qui se chevauchent")
    if kept.identifier_type != dropped.identifier_type:
        parts.append(
            f"identifier_type {kept.identifier_type.value} > {dropped.identifier_type.value}"
        )
    if kept.length != dropped.length:
        parts.append(f"longueur {kept.length} > {dropped.length}")
    if kept.confidence != dropped.confidence:
        parts.append(f"confiance {kept.confidence:.2f} > {dropped.confidence:.2f}")
    return " ; ".join(parts)


def fuse(
    candidates: list[Candidate],
    strategy: str = "priority_longest",
) -> tuple[list[Candidate], list[FusionDecision]]:
    """Fusionne les candidats en conflit réel, en traçant chaque décision.

    Un candidat n'est jamais supprimé silencieusement : chaque suppression
    apparaît dans une ``FusionDecision`` retournée aux côtés des candidats
    conservés. Les candidats qui se chevauchent sans être en conflit réel
    (catégories différentes, cf. I-ANN-5) sont tous les deux conservés.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Stratégie de fusion inconnue : {strategy!r}. Choix : {STRATEGIES}")

    key = _sort_key(strategy)

    # Regroupe par catégorie : seuls des candidats de même catégorie peuvent
    # entrer en conflit réel (décision documentée en tête de module).
    by_category: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        by_category.setdefault(candidate.qi_category, []).append(candidate)

    kept: list[Candidate] = []
    decisions: list[FusionDecision] = []

    for category_candidates in by_category.values():
        ordered = sorted(category_candidates, key=key, reverse=True)
        category_kept: list[Candidate] = []
        for candidate in ordered:
            conflicting = [k for k in category_kept if _is_real_conflict(k, candidate)]
            if conflicting:
                winner = conflicting[0]
                decisions.append(
                    FusionDecision(
                        kept=winner,
                        dropped=(candidate,),
                        strategy=strategy,
                        reason=_reason_for(strategy, winner, candidate),
                    )
                )
                continue
            category_kept.append(candidate)
        kept.extend(category_kept)

    # Ordre stable et lisible pour les consommateurs en aval.
    kept.sort(key=lambda c: (c.start, c.end))
    return kept, decisions

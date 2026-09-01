"""Conversion BIO (niveau token) → spans caractères (ticket EPIC-A, A-4).

CleanCoNLL est annoté en BIO au niveau token ; le format pivot exige des
offsets caractères. Cette conversion est la source d'erreur d'offsets la
plus fréquente — l'invariant I-ANN-1 (``text[start:end] == span_text``)
la rendra bruyante à la validation. L'implémentation reconstruit d'abord
le texte et les offsets cumulés, puis projette les entités token par
token : l'invariant est donc garanti **par construction**.

Port de la logique v1 (``eval/core/loaders/conll2003.py``, lecture seule),
corrigée :

- longueurs ``tokens``/``tags`` différentes → ``ValueError`` explicite
  (la v1 tronquait silencieusement via ``zip``) ;
- toute étiquette dont le préfixe n'est pas ``B-``/``I-``/``O`` →
  ``ValueError`` explicite (la v1 l'ignorait silencieusement) ;
- ``I-`` orphelin (sans ``B-`` précédent) → ouvre une nouvelle entité ;
- entité ouverte en fin de séquence → fermée sur le dernier token.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["bio_to_spans"]


def bio_to_spans(
    tokens: Sequence[str],
    tags: Sequence[str],
    *,
    joiner: str = " ",
) -> tuple[str, list[tuple[int, int, str]]]:
    """Convertit une séquence tokenisée en texte + spans caractères.

    Args:
        tokens: tokens de la séquence (dans l'ordre).
        tags: étiquettes BIO, **une par token**, même ordre.
        joiner: séparateur inséré entre deux tokens lors de la
            reconstruction du texte (espace par défaut).

    Returns:
        Le texte reconstruit (``joiner.join(tokens)``) et la liste des
        spans ``(start, end, type)`` triés par ``start`` croissant, où
        ``text[start:end]`` est la surface de l'entité (invariant
        I-ANN-1 garanti par construction).

    Raises:
        ValueError: longueurs ``tokens``/``tags`` différentes, ou
            étiquette invalide (préfixe autre que ``B-``/``I-``/``O``,
            type vide) — le message porte l'index de l'étiquette fautives.
    """
    n = len(tokens)
    if len(tags) != n:
        raise ValueError(
            f"Longueur incohérente : {n} tokens pour {len(tags)} étiquettes BIO — "
            "chaque token doit porter exactement une étiquette."
        )

    # 1. Texte reconstruit + offset de début de chaque token.
    text = joiner.join(tokens)
    offsets: list[int] = []
    pos = 0
    for tok in tokens:
        offsets.append(pos)
        pos += len(tok) + len(joiner)

    # 2. Projection des entités token par token.
    spans: list[tuple[int, int, str]] = []
    entity: str | None = None
    entity_start = 0

    def _close(end_token_idx: int) -> None:
        nonlocal entity
        if entity is None:
            return
        end = offsets[end_token_idx] + len(tokens[end_token_idx])
        spans.append((offsets[entity_start], end, entity))
        entity = None

    for i, tag in enumerate(tags):
        if tag == "O":
            _close(i - 1)
            continue
        prefix, sep, type_ = tag.partition("-")
        if not sep or prefix not in ("B", "I") or not type_:
            raise ValueError(
                f"Étiquette BIO invalide à l'index {i} : {tag!r} — "
                "préfixes autorisés : B-, I-, O."
            )
        # Ouvrent une entité (en fermant celle éventuellement en cours) : un
        # ``B-``, un ``I-`` orphelin, et un ``I-`` d'un autre type. Seul le
        # ``I-`` qui continue l'entité courante ne fait rien.
        if prefix == "B" or entity != type_:
            _close(i - 1)
            entity = type_
            entity_start = i

    _close(n - 1)  # entité ouverte en fin de séquence
    return text, spans

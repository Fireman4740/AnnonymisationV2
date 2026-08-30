"""Split déterministe par hachage de clé de groupe.

Implémente exactement l'algorithme de SPEC-04 §9 : le hachage d'une clé de
groupe (``person_id``, ``org_id``...) avec une graine fixe détermine le split,
jamais un ``random.shuffle`` sur un ordre dépendant du système de fichiers.

Propriété clé : ajouter un nouveau groupe ne redistribue pas les groupes déjà
affectés — ce que ``train_test_split`` ne garantit pas, car chaque clé est
affectée indépendamment des autres.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping


def assign_split(group_key: str, seed: int, ratios: Mapping[str, float]) -> str:
    """Affecte ``group_key`` à un split selon ``ratios``.

    Algorithme (SPEC-04 §9) :

    1. ``h = blake2b(f"{seed}:{group_key}")`` sur 8 octets.
    2. ``x = int(h, big-endian) / 2**64`` — un flottant dans ``[0, 1)``.
    3. Les splits sont triés par **nom** (et non par ordre d'insertion du
       dict, qui n'est pas une garantie stable entre deux exécutions au sens
       de la spec) ; on cumule leurs ratios et on prend le premier seuil que
       ``x`` ne dépasse pas.

    Aucune valeur par défaut silencieuse : des ratios ne sommant pas à 1 (à
    une tolérance flottante près) sont une erreur de configuration, pas un
    cas à absorber discrètement.
    """
    if not ratios:
        raise ValueError("ratios ne peut pas être vide")

    total = sum(ratios.values())
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"La somme des ratios doit valoir 1.0, obtenu {total!r} : {ratios!r}")
    for name, ratio in ratios.items():
        if ratio < 0:
            raise ValueError(f"Ratio négatif pour le split {name!r} : {ratio!r}")

    digest = hashlib.blake2b(f"{seed}:{group_key}".encode("utf-8"), digest_size=8).digest()
    x = int.from_bytes(digest, "big") / 2**64

    cumulative = 0.0
    for name in sorted(ratios):
        cumulative += ratios[name]
        if x < cumulative:
            return name
    # Filet de sécurité pour l'imprécision flottante à la borne supérieure
    # (x très proche de 1.0 après arrondi de la somme cumulée) : on retombe
    # sur le dernier split trié, jamais sur une exception due à un artefact
    # numérique.
    return sorted(ratios)[-1]


def split_groups(
    group_keys: Iterable[str], seed: int, ratios: Mapping[str, float]
) -> dict[str, tuple[str, ...]]:
    """Répartit ``group_keys`` en splits, groupés par nom de split.

    L'ordre d'entrée est préservé à l'intérieur de chaque split (pas de tri
    additionnel), pour rester déterministe même si l'appelant fournit un
    itérable dont l'ordre importe pour d'autres besoins (traçabilité, débogage).
    """
    buckets: dict[str, list[str]] = {name: [] for name in ratios}
    for key in group_keys:
        split = assign_split(key, seed, ratios)
        buckets[split].append(key)
    return {name: tuple(keys) for name, keys in buckets.items()}

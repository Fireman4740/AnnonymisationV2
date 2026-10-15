"""Comptage exact dans une population de référence fournie indépendamment.

Le protocole v1 ne gère que l'égalité d'attributs normalisés. Il refuse les
valeurs manquantes et n'extrapole pas un échantillon en population réelle.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def counted_combinations(population: Mapping[str, Any], combinations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if population.get("schema_version") != "1" or population.get("kind") not in {"synthetic_controlled", "reference_census"}:
        raise ValueError("population : schéma 1 et kind synthetic_controlled/reference_census requis")
    population_id = population.get("population_id")
    records = population.get("records")
    if not isinstance(population_id, str) or not population_id or not isinstance(records, list) or not records:
        raise ValueError("population : identifiant et enregistrements non vides requis")
    subjects = [r.get("subject_id") for r in records]
    if any(not isinstance(s, str) or not s for s in subjects) or len(set(subjects)) != len(subjects):
        raise ValueError("population : subject_id non vide et unique requis")
    if any(not isinstance(r.get("attributes"), dict) for r in records):
        raise ValueError("population : attributes doit être un objet")

    def canonical(value: Any) -> str:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)

    output = []
    seen = set()
    for combo in combinations:
        cid = combo["combination_id"]
        if cid in seen:
            raise ValueError("combination_id dupliqué")
        seen.add(cid)
        if combo["population_id"] != population_id:
            raise ValueError("combinaison et population de référence différentes")
        query = {q["qi_category"]: q["normalized"] for q in combo["qi_set"]}
        if not query or len(query) != len(combo["qi_set"]) or any(v in (None, {}) for v in query.values()):
            raise ValueError("combinaison : catégories distinctes et valeurs normalisées non vides requises")
        if any(not query.keys() <= r["attributes"].keys()
               or any(r["attributes"].get(key) in (None, {}, "", []) for key in query)
               for r in records):
            raise ValueError("population incomplète : attribut absent ; pas de comptage partiel")
        matching = [r["subject_id"] for r in records
                    if all(canonical(r["attributes"][k]) == canonical(v) for k, v in query.items())]
        target = combo["target_id"]
        if target not in matching:
            raise ValueError(f"combinaison {cid} : la cible n'appartient pas à sa classe dans la population")
        k_true = len(matching)
        if combo.get("k_true") is not None and combo["k_true"] != k_true:
            raise ValueError(f"combinaison {cid} : k_true déclaré divergent du comptage indépendant")
        output.append({"combination_id": cid, "target_id": target, "doc_ids": combo["doc_ids"],
                       "annotation_ids": combo.get("annotation_ids", []), "k_true": k_true,
                       "qi_size": len(query)})
    return output

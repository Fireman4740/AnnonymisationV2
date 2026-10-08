"""Taux de ré-identification R_succ depuis une attaque FIGÉE (SPEC-07 §5).

Ne lance aucun modèle (C5) : relit ``attacks.jsonl`` produit par
``anonv2 attack`` et en dérive

* ``R_succ`` = part des documents attaqués avec succès (identifiant direct
  retrouvé, ou correctness CorrectMatch ≥ 0,2 — règle de RAT-Bench) ;
* son intervalle bootstrap (unité : document, comme ``bootstrap_reidentification_rate``
  du dépôt officiel) ;
* la ventilation par difficulté et les sous-composantes (part des succès
  par identifiant direct, correctness moyenne).

Un document en erreur d'attaque n'est ni ré-identifié ni protégé : il est
exclu et compté ; au-delà de 5 % la métrique est ``UNAVAILABLE`` (C4).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from anonymisation.metrics.contracts import MetricDirection, MetricStatus, MetricValue
from anonymisation.metrics.uncertainty import bootstrap_interval, mean

MAX_ATTACK_ERROR_RATE = 0.05


def reid_success_metric(
    rows: Sequence[Mapping[str, Any]], lock: Mapping[str, Any]
) -> dict[str, Any]:
    ok = [r for r in rows if r.get("status") == "ok"]
    errors = len(rows) - len(ok)
    error_rate = errors / len(rows) if rows else 1.0
    attacker = dict(lock.get("attacker") or {})
    base_details: dict[str, Any] = {
        "protocol": lock.get("protocol"),
        "official": lock.get("official"),
        "attacker": attacker,
        "risk": lock.get("risk"),
        "documents_attacked": len(rows),
        "documents_error": errors,
        "error_rate": error_rate,
    }
    if not ok or error_rate > MAX_ATTACK_ERROR_RATE:
        return MetricValue(
            name="reid_success_rate", value=None,
            protocol=str(lock.get("protocol")), protocol_version=str(lock.get("protocol_version")),
            status=MetricStatus.UNAVAILABLE, direction=MetricDirection.MINIMIZE,
            details={**base_details, "reason": (
                f"attaque inexploitable : {errors}/{len(rows)} document(s) en erreur "
                f"(> {MAX_ATTACK_ERROR_RATE:.0%}, C4) — relancer `anonv2 attack`"
            )},
        ).to_dict()
    flags = [1.0 if r["reidentified"] else 0.0 for r in ok]
    for row in ok:
        probability = float(row["correctmatch_correctness"])
        direct = row["correct_direct_ids"]
        if (not 0 <= probability <= 1 or not isinstance(direct, list)
                or not isinstance(row["reidentified"], bool)
                or row["reidentified"] != (bool(direct) or probability >= 0.2)):
            raise ValueError(f"attaque {row.get('doc_id')} : succès ou probabilité incohérent")
    by_difficulty: dict[str, list[float]] = defaultdict(list)
    for row, flag in zip(ok, flags, strict=True):
        by_difficulty[str(row.get("difficulty"))].append(flag)
    details = {
        **base_details,
        "direct_identifier_hit_rate": mean([1.0 if r["correct_direct_ids"] else 0.0 for r in ok]),
        "mean_correctmatch_correctness": mean([float(r["correctmatch_correctness"]) for r in ok]),
        "by_difficulty": {
            level: {"documents": len(values), "value": mean(values)}
            for level, values in sorted(by_difficulty.items())
        },
        "ci95": bootstrap_interval(flags, mean, unit="document"),
        "comparability": (
            "même protocole que RAT-Bench (prompt, jugement, CorrectMatch, seuil 0,2) ; "
            "attaquant différent du papier — non comparable aux chiffres publiés"
        ),
    }
    return MetricValue(
        name="reid_success_rate", value=mean(flags),
        protocol=str(lock.get("protocol")), protocol_version=str(lock.get("protocol_version")),
        status=MetricStatus.DIAGNOSTIC, direction=MetricDirection.MINIMIZE, details=details,
    ).to_dict()


__all__ = ["reid_success_metric"]

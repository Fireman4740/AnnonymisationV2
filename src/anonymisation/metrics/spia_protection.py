"""CPR / IPR du protocole SPIA original, depuis une attaque FIGÉE (EPIC-H H-2).

Ne relance aucun modèle (C5) : relit ``spia_attacks.jsonl`` et appelle
``calculate_ipr_cpr`` du code original (scores d'accord fractionnaires 1 / 0,5
/ 0, filtrage ``certainty_A >= min_certainty``, défaut 3). Seules ces valeurs
portent les noms ``cpr`` / ``ipr`` : l'adversaire littéral (présence d'une
surface gold) reste un diagnostic distinct et ne se substitue jamais à elles.

Écarts à l'original, tous dans le sens « ne rien inventer » :

* un échantillon sans sujet évaluable rend ``UNAVAILABLE`` (l'original publie
  0,0) ;
* au-delà de 5 % de documents en erreur d'attaque, ``UNAVAILABLE`` (C4).

Les intervalles rééchantillonnent les **documents** : les sujets d'un même
texte partagent l'inférence de l'attaquant et ne sont pas indépendants.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from anonymisation.metrics.contracts import MetricDirection, MetricStatus, MetricValue
from anonymisation.metrics.uncertainty import bootstrap_interval

MAX_ATTACK_ERROR_RATE = 0.05
MIN_CERTAINTY = 3


def _unavailable(name: str, lock: Mapping[str, Any], reason: str, details: Mapping[str, Any]
                 ) -> dict[str, Any]:
    return MetricValue(
        name=name, value=None, protocol=str(lock.get("protocol")),
        protocol_version=str(lock.get("protocol_version")), status=MetricStatus.UNAVAILABLE,
        direction=MetricDirection.MAXIMIZE, details={**details, "reason": reason},
    ).to_dict()


def spia_protection(
    rows: Sequence[Mapping[str, Any]], lock: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(cpr, ipr)`` publiés ensemble, ou tous deux ``UNAVAILABLE``."""
    from anonymisation.attack.spia.vendored import SCORING_MODULES, original_spia

    ok = [row for row in rows if row.get("status") == "ok"]
    errors = len(rows) - len(ok)
    error_rate = errors / len(rows) if rows else 1.0
    min_certainty = int((lock.get("config") or {}).get("min_certainty", MIN_CERTAINTY))
    base = {"protocol": lock.get("protocol"), "official": lock.get("official"),
            "attacker": lock.get("attacker"), "config": lock.get("config"),
            "documents_attacked": len(rows), "documents_error": errors,
            "error_rate": error_rate, "min_certainty": min_certainty}
    if not ok or error_rate > MAX_ATTACK_ERROR_RATE:
        reason = (f"attaque SPIA inexploitable : {errors}/{len(rows)} document(s) en erreur "
                  f"(> {MAX_ATTACK_ERROR_RATE:.0%}, C4)")
        return _unavailable("cpr", lock, reason, base), _unavailable("ipr", lock, reason, base)
    documents = [row["evaluation"] for row in ok]
    with original_spia(SCORING_MODULES) as original:
        result = original.ppr.calculate_ipr_cpr({"detailed_results": documents}, min_certainty)

        def per_document(sample: Sequence[Mapping[str, Any]]) -> Any:
            return original.ppr.calculate_ipr_cpr({"detailed_results": list(sample)}, min_certainty)

        def cpr_of(sample: Sequence[Mapping[str, Any]]) -> float | None:
            computed = per_document(sample)
            return computed.cpr if computed.total_pii else None

        def ipr_of(sample: Sequence[Mapping[str, Any]]) -> float | None:
            computed = per_document(sample)
            return computed.ipr if computed.total_subjects else None

        intervals = {"cpr": bootstrap_interval(documents, cpr_of, unit="document"),
                     "ipr": bootstrap_interval(documents, ipr_of, unit="document")}
    if not result.total_subjects:
        reason = (f"aucun sujet avec un attribut gold de certitude ≥ {min_certainty} : "
                  "l'original publierait 0,0, valeur non définie ici")
        return _unavailable("cpr", lock, reason, base), _unavailable("ipr", lock, reason, base)
    details = {
        **base,
        "total_subjects": result.total_subjects,
        "total_pii": result.total_pii,
        "total_score": result.total_score,
        "by_tag": result.by_tag,
        "unmatched_subjects": sum(
            1 for doc in documents for subject in doc["subjects"] if not subject.get("matched")
        ),
        "comparability": "protocole SPIA original ; attaquant différent du papier",
    }
    metrics = []
    for name, value in (("cpr", result.cpr), ("ipr", result.ipr)):
        ci = intervals[name] if intervals[name] is not None else {
            "reason": "intervalle non défini (moins de deux documents évaluables)"}
        metrics.append(MetricValue(
            name=name, value=value, protocol=str(lock.get("protocol")),
            protocol_version=str(lock.get("protocol_version")), status=MetricStatus.DIAGNOSTIC,
            direction=MetricDirection.MAXIMIZE, details={**details, "ci95": ci},
        ).to_dict())
    return metrics[0], metrics[1]


__all__ = ["spia_protection"]

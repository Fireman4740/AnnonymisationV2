"""QICR, QICR@j, RCR@k et calibration du risque (SPEC-07 §3-§4, EPIC-H H-4/H-6).

Vérité terrain **indépendante** exigée :

* chaque combinaison gold cite les annotations qu'elle exige
  (``Combination.annotation_ids``) — sans ce lien, un appariement par catégorie
  créditerait le mauvais attribut ; une combinaison non liée est comptée à part
  et n'entre pas au dénominateur ;
* ``k_true`` vient d'un comptage de population fait à la construction du
  corpus, jamais de l'estimateur évalué. Un corpus sans ``k_true`` rend ces
  métriques ``UNAVAILABLE`` (RAT-Bench : CorrectMatch fournit une estimation
  de correctness, pas un ``k_true``).

Définitions :

* **QICR** = combinaisons à risque (``k_true ≤ k_seuil``) dont **toutes** les
  annotations exigées sont couvertes par une prédiction / combinaisons à risque ;
  **QICR@j** = idem restreint aux combinaisons de taille ``j`` ;
* **RCR@k** = P(k̂ ≥ k | k_true ≥ k), avec k̂ le risque estimé par le système
  pour le document cible ; mesure du sur-masquage. QICR et RCR@k sont
  publiés ensemble.
* **Calibration** (MALE-k, Brier, ECE + sensibilité aux bacs) sur les couples
  (k̂, k_true) du split évalué — un split d'ajustement (``calib``) est refusé :
  ses statistiques sont des erreurs d'ajustement, pas une calibration.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from anonymisation.metrics.calibration import (
    brier,
    ece_equal_mass,
    ece_sensitivity,
    male_k,
)
from anonymisation.metrics.entities import field_value, mention_covered

DEFAULT_K_THRESHOLD = 10
CALIBRATION_FIT_SPLITS = frozenset({"calib", "train"})


class CombinationError(ValueError):
    """Combinaison gold incohérente avec les annotations du pivot."""


def _k_hat(record: Mapping[str, Any] | None) -> float | None:
    risk = (record or {}).get("risk")
    if not isinstance(risk, Mapping) or risk.get("k_hat") is None:
        return None
    return float(risk["k_hat"])


def combination_metrics(
    combinations: Sequence[Any],
    gold_by_doc: Mapping[str, Sequence[Any]],
    predictions_by_doc: Mapping[str, Mapping[str, Any]],
    *,
    k_threshold: int = DEFAULT_K_THRESHOLD,
    rcr_k: int = DEFAULT_K_THRESHOLD,
    split: str,
) -> dict[str, Any]:
    """Comptes et valeurs ; ``None`` quand la vérité ou le risque manque."""
    gold_index = {
        str(field_value(annotation, "annotation_id")): (doc_id, annotation)
        for doc_id, annotations in gold_by_doc.items()
        for annotation in annotations
    }
    at_risk = detected = unlinked = without_k = excluded = 0
    by_size: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    rcr = [0, 0]
    calibration_pairs: list[tuple[float, float]] = []
    for combination in combinations:
        doc_ids = sorted(set(field_value(combination, "doc_ids", ()) or ()))
        scored = [d for d in doc_ids if d in predictions_by_doc]
        if len(scored) != len(doc_ids) or not doc_ids:
            # Un document de la combinaison en erreur : la couvrir « à vide »
            # gonflerait QICR. Exclue et comptée.
            excluded += 1
            continue
        k_true = field_value(combination, "k_true")
        if k_true is None:
            without_k += 1
            continue
        annotation_ids = tuple(field_value(combination, "annotation_ids", ()) or ())
        k_hat = _k_hat(predictions_by_doc.get(scored[0]))
        if k_hat is not None:
            calibration_pairs.append((k_hat, float(k_true)))
            if k_true >= rcr_k:
                rcr[1] += 1
                rcr[0] += int(k_hat >= rcr_k)
        if k_true > k_threshold:
            continue
        if not annotation_ids:
            unlinked += 1
            continue
        missing = [a for a in annotation_ids if a not in gold_index]
        if missing:
            raise CombinationError(
                f"combinaison {field_value(combination, 'combination_id')!r} : annotations "
                f"{missing[:3]} absentes du pivot gold — corpus incohérent, réingérer"
            )
        covered = all(
            mention_covered(annotation, tuple(
                predictions_by_doc[doc_id].get("annotations") or ()))
            for doc_id, annotation in (gold_index[a] for a in annotation_ids)
        )
        at_risk += 1
        detected += int(covered)
        size = len(annotation_ids)
        by_size[size][0] += int(covered)
        by_size[size][1] += 1
    fit_split = split in CALIBRATION_FIT_SPLITS
    return {
        "k_threshold": k_threshold,
        "at_risk": at_risk,
        "detected": detected,
        "unlinked_at_risk": unlinked,
        "without_k_true": without_k,
        "excluded_document_errors": excluded,
        "qicr": detected / at_risk if at_risk else None,
        "qicr_at_j": {str(j): {"detected": d, "total": t, "value": d / t}
                      for j, (d, t) in sorted(by_size.items())},
        "rcr_k": rcr_k,
        "rcr": rcr[0] / rcr[1] if rcr[1] else None,
        "rcr_counts": {"k_hat_ge_k": rcr[0], "k_true_ge_k": rcr[1]},
        "calibration": {
            "pairs": len(calibration_pairs),
            "fit_split": fit_split,
            "male_k": None if fit_split else male_k(calibration_pairs),
            "brier": None if fit_split else brier(
                [(1.0 / max(k, 1.0), 1.0 / max(t, 1.0)) for k, t in calibration_pairs]),
            "ece": None if fit_split else ece_equal_mass(
                [(1.0 / max(k, 1.0), 1.0 / max(t, 1.0)) for k, t in calibration_pairs]),
            "ece_by_bins": {} if fit_split else ece_sensitivity(
                [(1.0 / max(k, 1.0), 1.0 / max(t, 1.0)) for k, t in calibration_pairs]),
            "target": "risque gold continu R = 1/k_true (prosecutor), pas un événement binaire",
        },
    }


__all__ = ["CALIBRATION_FIT_SPLITS", "CombinationError", "combination_metrics"]

"""Contrôle de calibration du risque copule — hors modèle, hors réseau.

``evaluate_risk_calibration(predictions_path, combinations_path)`` lit
uniquement les **prédictions figées** d'un run (``predictions.jsonl``) et
les ``Combination`` gold (``combinations.jsonl``), aligne sur ``doc_id`` et
calcule ECE (10 bacs équipopulés), Brier et MALE-k — sans modèle ni
réseau (contrainte C5). Si ``combinations.jsonl`` est absent, le rapport
renvoie ``status="unavailable"`` avec une raison actionnable — **jamais
zéro, jamais un nombre inventé**.

Ce contrôle est **DIAGNOSTIC** par construction : les k gold sont produits
sur le split du dataset lui-même (RAT-Bench n'a pas de split ``calib``),
sous le modèle prosecutor — le résultat est donc un audit de
*généralisation* de la calibration synthétique embarquée (seed 42) vers
les populations réelles, jamais une calibration officielle. Aucune
métrique produite ici ne peut être publiée comme OFFICIAL (SPEC-07 §9).

CLI (exécute le contrôle sur un run existant)::

    PYTHONPATH=src .venv/bin/python3 -m anonymisation.pipelines.hybrid_qi.calibration \\
        --run runs/eval-hybrid-qi-ratbench-eval-P2-det \\
        --combinations data/processed/ratbench/eval/combinations.jsonl \\
        --out runs/eval-hybrid-qi-ratbench-eval-P2-det/risk_calibration.json
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anonymisation.schema.io import read_jsonl, write_json
from anonymisation.schema.models import Combination

__all__ = [
    "CalibrationReport",
    "CalibrationUnavailable",
    "evaluate_risk_calibration",
    "main",
]

#: Nombre de bacs équipopulés pour l'ECE (parité avec la calibration
#: synthétique embarquée, ``risk.py``).
N_BINS: int = 10


class CalibrationUnavailable(ValueError):
    """Le contrôle ne peut pas être calculé (fichier manquant, run sans
    risque, zéro document aligné). Porte la raison actionnable — le
    rapport publié est alors ``status="unavailable"``, jamais un zéro
    maquillé."""


@dataclass(frozen=True)
class CalibrationReport:
    """Rapport de calibration — agrégats uniquement (n, ece, brier, male_k).

    ``status`` : ``"diagnostic"`` quand les métriques sont calculées,
    ``"unavailable"`` quand le contrôle n'est pas calculable (la raison
    est dans ``reason``). ``calibration_scope`` rappelle toujours que la
    calibration de référence est synthétique (seed 42) — le rapport est
    un audit de généralisation, jamais OFFICIAL.
    """

    status: str
    n: int
    n_predictions: int
    n_gold: int
    n_unaligned_predictions: int
    n_unaligned_gold: int
    ece: float | None
    brier: float | None
    male_k: float | None
    risk_model_predicted: str | None
    risk_model_gold: str | None
    population_gold: str | None
    calibration_scope: str = "synthetic"
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "n": self.n,
            "n_predictions": self.n_predictions,
            "n_gold": self.n_gold,
            "n_unaligned_predictions": self.n_unaligned_predictions,
            "n_unaligned_gold": self.n_unaligned_gold,
            "ece": self.ece,
            "brier": self.brier,
            "male_k": self.male_k,
            "risk_model_predicted": self.risk_model_predicted,
            "risk_model_gold": self.risk_model_gold,
            "population_gold": self.population_gold,
            "calibration_scope": self.calibration_scope,
            "reason": self.reason,
            "note": (
                "Audit DIAGNOSTIC de généralisation de la calibration "
                "synthétique (seed 42) : le k gold provient du split du "
                "dataset (pas de split calib) sous le modèle prosecutor. "
                "Aucune métrique de ce rapport n'est OFFICIAL (SPEC-07 §9)."
            ),
        }


def _unavailable(
    *,
    reason: str,
    n_predictions: int = 0,
    n_gold: int = 0,
) -> CalibrationReport:
    return CalibrationReport(
        status="unavailable",
        n=0,
        n_predictions=n_predictions,
        n_gold=n_gold,
        n_unaligned_predictions=0,
        n_unaligned_gold=0,
        ece=None,
        brier=None,
        male_k=None,
        risk_model_predicted=None,
        risk_model_gold=None,
        population_gold=None,
        reason=reason,
    )


def evaluate_risk_calibration(
    predictions_path: Path, combinations_path: Path
) -> CalibrationReport:
    """Calcule ECE/Brier/MALE-k sur les prédictions figées vs k gold.

    - documents en ``status="error"`` : **exclus** (C4 — une ligne en
      erreur n'est jamais comptée comme prédiction) ;
    - alignement par ``doc_id`` : chaque combinaison gold est indexée par
      ses ``doc_ids`` ; les documents non alignés sont comptés et exposés,
      jamais ignorés silencieusement ;
    - ECE : 10 bacs équipopulés sur le risque prédit ;
    - Brier : sur l'échelle risque (prédit = ``1/k_low``, gold = ``risk_true``) ;
    - MALE-k : moyenne de ``|log(k_pred / k_true)|`` sur l'estimation
      ponctuelle ``k_hat``.
    """
    if not predictions_path.is_file():
        return _unavailable(
            reason=(
                f"run manquant : {predictions_path} introuvable — lancer "
                "d'abord `anonv2 predict` (le contrôle ne relance jamais "
                "de modèle, C5)."
            )
        )
    if not combinations_path.is_file():
        return _unavailable(
            reason=(
                f"combinations.jsonl manquant : {combinations_path} — ce "
                "dataset/split n'a pas de k gold ; le diagnostic de "
                "calibration est UNAVAILABLE, jamais zéro. Vérifier "
                "data/processed/<dataset>/<split>/combinations.jsonl."
            )
        )

    predictions = _read_predictions(predictions_path)
    n_predictions = len(predictions)
    if n_predictions == 0:
        return _unavailable(
            n_predictions=0,
            reason=(
                f"{predictions_path} ne contient aucun document terminé "
                "(ok/partial) — le run est entier en erreur (C4) ; "
                "diagnostic UNAVAILABLE."
            ),
        )

    gold_by_doc: dict[str, Combination] = {}
    golds: list[Combination] = []
    try:
        for combo in read_jsonl(combinations_path, Combination):
            golds.append(combo)
            for doc_id in combo.doc_ids:
                gold_by_doc[doc_id] = combo
    except Exception as exc:
        raise CalibrationUnavailable(
            f"{combinations_path} illisible ({type(exc).__name__}: {exc}) — "
            "fichier gold corrompu ; ré-ingérer le dataset."
        ) from exc
    n_gold = len(golds)

    pairs: list[tuple[float, float, float, float]] = []
    models_predicted: set[str] = set()
    for doc_id, risk in predictions:
        if not isinstance(risk, dict) or "risk" not in risk or "k_hat" not in risk:
            raise CalibrationUnavailable(
                f"document {doc_id!r} dans {predictions_path} : champ "
                "'risk' incomplet (attendu k_hat/risk) — vérifier le "
                "système ayant produit le run."
            )
        k_pred = float(risk["k_hat"])
        r_pred = float(risk["risk"])
        if k_pred <= 0.0 or r_pred < 0.0:
            raise CalibrationUnavailable(
                f"document {doc_id!r} : valeurs de risque incohérentes "
                f"(k_hat={k_pred}, risk={r_pred}) — diagnostic impossible."
            )
        model = risk.get("risk_model")
        if model:
            models_predicted.add(str(model))
        gold = gold_by_doc.get(doc_id)
        if gold is None or gold.k_true is None or gold.risk_true is None:
            continue
        pairs.append((k_pred, r_pred, float(gold.k_true), float(gold.risk_true)))

    if not pairs:
        return _unavailable(
            n_predictions=n_predictions,
            n_gold=n_gold,
            reason=(
                f"zéro document aligné entre {predictions_path} "
                f"({n_predictions} prédictions) et {combinations_path} "
                f"({n_gold} combinaisons) — vérifier que le run et les "
                "gold portent sur le même dataset/split ; diagnostic "
                "UNAVAILABLE, jamais zéro."
            ),
        )

    n = len(pairs)
    brier = sum((r_pred - r_true) ** 2 for _, r_pred, _, r_true in pairs) / n
    ece = _ece_equipopular(
        [(r_pred, r_true) for _, r_pred, _, r_true in pairs], n_bins=N_BINS
    )
    male_k = sum(
        abs(math.log(k_pred / k_true)) for k_pred, _, k_true, _ in pairs
    ) / n
    predicted_doc_ids = {doc_id for doc_id, _ in predictions}
    unaligned_gold = sum(1 for g in golds if not set(g.doc_ids) & predicted_doc_ids)
    risk_models_gold = sorted({g.risk_model.value for g in golds})
    return CalibrationReport(
        status="diagnostic",
        n=n,
        n_predictions=n_predictions,
        n_gold=n_gold,
        n_unaligned_predictions=n_predictions - n,
        n_unaligned_gold=unaligned_gold,
        ece=ece,
        brier=brier,
        male_k=male_k,
        risk_model_predicted=(
            next(iter(sorted(models_predicted))) if models_predicted else None
        ),
        risk_model_gold=risk_models_gold[0] if risk_models_gold else None,
        population_gold=_first_value((g.population_id for g in golds), None),
    )


def _read_predictions(
    path: Path,
) -> list[tuple[str, dict[str, Any]]]:
    """Prédictions terminées uniquement : ``(doc_id, risk)`` par document
    ``ok``/``partial`` (C4). Les lignes en erreur sont comptées ailleurs
    (manifest.lock.json) et exclues ici."""
    out: list[tuple[str, dict[str, Any]]] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CalibrationUnavailable(
                    f"{path} ligne {lineno} : JSON invalide ({exc}) — "
                    "artefact de run corrompu ; relancer predict."
                ) from exc
            status = record.get("status")
            if status not in ("ok", "partial"):
                continue  # ligne en erreur : jamais comptée comme prédiction
            doc_id = record.get("doc_id")
            risk = record.get("risk")
            if doc_id is None:
                raise CalibrationUnavailable(
                    f"{path} ligne {lineno} : champ 'doc_id' absent — "
                    "artefact de run corrompu."
                )
            out.append((str(doc_id), risk if isinstance(risk, dict) else {}))
    return out


def _ece_equipopular(
    risks: list[tuple[float, float]], *, n_bins: int
) -> float:
    """ECE sur ``n_bins`` bacs équipopulés du risque prédit : moyenne
    pondérée des écarts ``|moyenne prédite − moyenne true|`` par bac."""
    n = len(risks)
    if n == 0:
        return 0.0
    bins = max(1, min(n_bins, n))
    ordered = sorted(risks, key=lambda r: r[0])
    size = n // bins
    remainder = n % bins
    ece = 0.0
    idx = 0
    for b in range(bins):
        count = size + (1 if b < remainder else 0)
        if count == 0:
            continue
        chunk = ordered[idx : idx + count]
        idx += count
        pred = sum(p for p, _ in chunk) / count
        truth = sum(t for _, t in chunk) / count
        ece += (count / n) * abs(pred - truth)
    return ece


def _first_value(values: Iterator[Any], default: Any) -> Any:
    return next(iter(values), default)


def main(argv: Sequence[str] | None = None) -> None:
    """CLI du contrôle de calibration (ne relance aucun modèle, C5)."""
    parser = argparse.ArgumentParser(
        description=(
            "Contrôle DIAGNOSTIC de calibration du risque copule sur un "
            "run existant (prédictions figées vs k gold) — aucun modèle, "
            "aucun réseau."
        )
    )
    parser.add_argument(
        "--run",
        required=True,
        help="répertoire du run (contient predictions.jsonl)",
    )
    parser.add_argument(
        "--combinations",
        required=True,
        help="chemin du combinations.jsonl gold",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="chemin du rapport JSON (défaut : <run>/risk_calibration.json)",
    )
    args = parser.parse_args(argv)
    run_dir = Path(args.run)
    predictions = run_dir / "predictions.jsonl"
    report = evaluate_risk_calibration(predictions, Path(args.combinations))
    out = Path(args.out) if args.out else run_dir / "risk_calibration.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, report.to_dict())
    if report.status == "unavailable":
        print(f"UNAVAILABLE : {report.reason}")
    else:
        print(
            f"DIAGNOSTIC : n={report.n} ece={report.ece:.6f} "
            f"brier={report.brier:.6f} male_k={report.male_k:.6f} "
            f"(scope={report.calibration_scope} — jamais OFFICIAL) -> {out}"
        )


if __name__ == "__main__":
    main()

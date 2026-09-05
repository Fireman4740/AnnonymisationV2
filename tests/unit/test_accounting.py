"""Comptabilité des erreurs de run (ticket C-5, SPEC-10 §2/§4)."""

from __future__ import annotations

import pytest

from anonymisation.metrics.accounting import RunAccounting
from anonymisation.metrics.contracts import MetricStatus


def test_non_ok_documents_are_excluded_and_separately_counted() -> None:
    accounting = RunAccounting.from_predictions(
        [
            {"doc_id": "d1", "status": "ok", "error": []},
            {"doc_id": "d2", "status": "error", "error": ["DETECT: timeout"]},
            {"doc_id": "d3", "status": "error", "error": ["BUDGET: too long"]},
        ]
    )
    assert accounting.documents_total == 3
    assert accounting.documents_scored == 1
    assert accounting.documents_errored == 2
    assert accounting.error_rate == pytest.approx(2 / 3)
    assert accounting.errors_by_stage == {"BUDGET": 1, "DETECT": 1}
    assert accounting.errors_by_type == {"budget": 1, "timeout": 1}


def test_ten_percent_errors_degrade_official_to_sampled() -> None:
    predictions = [{"status": "ok", "error": []} for _ in range(9)]
    predictions.append({"status": "error", "error": ["TRANSFORM: failed"]})
    accounting = RunAccounting.from_predictions(predictions)
    assert accounting.error_rate == pytest.approx(0.1)
    assert accounting.status_for(MetricStatus.OFFICIAL) is MetricStatus.SAMPLED
    assert accounting.publishable is False  # seuil bloquant de 5 %
    assert accounting.warning is not None


def test_partial_is_scored_and_is_not_an_error() -> None:
    """Un ``partial`` est un RÉSULTAT, pas une panne : il doit être scoré.

    Ce test affirmait l'inverse, et c'était un biais grave : un document
    ``partial`` a traversé tout le pipeline et porte des prédictions valides —
    VALIDATE a simplement constaté une fuite gold. Les exclure retirait des
    métriques les documents **les plus mauvais**, faisait paraître le système
    meilleur qu'il n'est, et rendait deux runs incomparables dès que leur
    proportion de constats différait.

    Mesuré sur quasifr : l'exclusion faisait passer ER_di de 0,522 à 1,000 et
    le taux de fuite de 0,484 à 0,000, en ne scorant que 7 documents sur 31.
    """
    accounting = RunAccounting.from_predictions(
        [{"status": "partial", "error": ["VALIDATE: fuite gold"]}]
    )
    assert accounting.documents_scored == 1
    assert accounting.documents_errored == 0
    assert accounting.documents_with_findings == 1
    assert accounting.error_rate == 0.0
    # Un constat n'empêche pas de publier ; une panne d'exécution, si.
    assert accounting.publishable


def test_empty_run_has_zero_error_rate() -> None:
    accounting = RunAccounting.from_predictions([])
    assert accounting.documents_total == 0
    assert accounting.error_rate == 0.0
    assert accounting.warning is None


def test_stage_errors_are_recovered_from_traces() -> None:
    """Un document en échec sans message agrégé garde son étape fautive.

    Sans le repli sur les traces, l'étape serait perdue et ``errors_by_stage``
    ne permettrait plus d'identifier le point de panne (critère C-5).
    """
    accounting = RunAccounting.from_predictions(
        [
            {"doc_id": "d1", "status": "ok", "error": []},
            {
                "doc_id": "d2",
                "status": "error",
                "error": [],
                "traces": [
                    {"stage": "DETECT", "status": "ok"},
                    {"stage": "TRANSFORM", "status": "error", "error": "placeholder tronqué"},
                ],
            },
        ]
    )
    assert accounting.errors_by_stage == {"TRANSFORM": 1}
    assert accounting.errors_by_type == {"malformed_placeholder": 1}

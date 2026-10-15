"""Catalogue fermé des métriques du banc actif (scorecards 3.0).

Les utilitaires historiques restent lisibles pour les anciens runs et pour
les statistiques internes des pipelines ; ils ne sont plus publiés par score.
"""

from typing import Final

PRIMARY_METRICS: Final = frozenset({"cpr", "ipr", "reid_success_rate"})
DIAGNOSTIC_METRICS: Final = frozenset(
    {
        "span_precision",
        "span_recall",
        "span_f1",
        "span_strict_f1",
        "gold_leak_rate",
        "direct_leak_rate",
        "mask_coverage",
        "tab_official",
    }
)
RETIRED_METRICS: Final = frozenset(
    {
        "mean_utility",
        "rouge_l",
        "utility_retention",
        "trir",
        "qicr",
        "rcr_at_k",
        "male_k",
        "ece",
        "brier",
        "literal_cpr",
        "literal_ipr",
        "weighted_token_precision",
        "ER_di",
        "ER_qi",
        "entity_recall_direct",
        "entity_recall_quasi",
        "span_classification_f1",
        "span_schemas",
        "macro_f1",
        "span_f2",
    }
)

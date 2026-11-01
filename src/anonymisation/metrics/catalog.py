"""Catalogue fermé des métriques du banc actif (scorecards 3.1).

Les utilitaires historiques restent lisibles pour les anciens runs et pour
les statistiques internes des pipelines ; ils ne sont plus publiés par score.
"""

from typing import Final

from anonymisation.metrics.detailed_quality import METRICS as DETAILED_QUALITY_METRICS

PRIMARY_METRICS: Final = frozenset({"cpr", "ipr", "reid_success_rate"})
DIAGNOSTIC_METRICS: Final = DETAILED_QUALITY_METRICS | frozenset(
    {
        "span_precision",
        "span_recall",
        "span_f1",
        "span_strict_f1",
        "gold_leak_rate",
        "direct_leak_rate",
        "mask_coverage",
        "tab_official",
        "local_readability",
        "local_relevance",
        "local_faithfulness",
        "human_readability",
        "human_relevance",
        "human_faithfulness",
        "utility_retention",
        "task_f1_delta",
        "qicr",
        "male_k",
        "brier",
        "ece",
    }
)
RETIRED_METRICS: Final = frozenset(
    {
        "mean_utility",
        "rouge_l",
        "trir",
        "rcr_at_k",
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

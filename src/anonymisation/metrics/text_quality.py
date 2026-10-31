"""Évaluations humaines figées de clarté, pertinence et fidélité.

Les notes sont descriptives et non validées comme certification. Aucun modèle
n'est appelé lors du scoring ; il faut au moins deux évaluateurs par document.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from anonymisation.metrics.contracts import MetricDirection, MetricStatus, MetricValue
from anonymisation.metrics.uncertainty import bootstrap_interval, mean, with_interval

RUBRIC = "human-text-quality-v1"
DIMENSIONS = {"human_readability": "readability", "human_relevance": "relevance",
              "human_faithfulness": "faithfulness"}


def freeze_human_quality(payload: Mapping[str, Any], predictions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Valide couverture, deux évaluateurs, échelle et empreintes des textes."""
    if payload.get("rubric") != RUBRIC or payload.get("evaluator") != "human":
        raise ValueError("qualité : rubric=human-text-quality-v1 et evaluator=human requis")
    study_id = payload.get("study_id")
    if not isinstance(study_id, str) or not study_id.strip():
        raise ValueError("qualité : study_id non vide requis pour comparer les systèmes")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("qualité : liste rows non vide requise")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"doc_id", "anonymized_sha256", "ratings"}:
            raise ValueError("qualité : doc_id, anonymized_sha256 et ratings exactement requis")
        doc_id = row["doc_id"]
        if not isinstance(doc_id, str) or doc_id in seen or doc_id not in predictions:
            raise ValueError("qualité : document dupliqué ou étranger aux prédictions")
        seen.add(doc_id)
        text = predictions[doc_id].get("anonymized_text")
        if not isinstance(text, str) or row["anonymized_sha256"] != hashlib.sha256(text.encode()).hexdigest():
            raise ValueError(f"qualité : empreinte du texte anonymisé divergente pour {doc_id}")
        ratings = row["ratings"]
        if not isinstance(ratings, list) or len(ratings) < 2:
            raise ValueError(f"qualité : deux évaluateurs indépendants requis pour {doc_id}")
        raters: set[str] = set()
        for rating in ratings:
            if not isinstance(rating, dict) or set(rating) != {"rater", *DIMENSIONS.values()}:
                raise ValueError("qualité : rater, readability, relevance, faithfulness requis")
            rater = rating["rater"]
            if not isinstance(rater, str) or not rater.strip() or rater in raters:
                raise ValueError("qualité : identifiants d'évaluateurs non vides et distincts requis")
            raters.add(rater)
            if any(type(rating[k]) is not int or rating[k] not in (0, 1, 2) for k in DIMENSIONS.values()):
                raise ValueError("qualité : chaque note doit être un entier 0, 1 ou 2")
    if seen != set(predictions):
        raise ValueError("qualité : chaque document réussi doit être évalué, sans omission")
    reviewers = sorted((row["doc_id"], sorted(r["rater"] for r in row["ratings"])) for row in rows)
    reviewer_digest = hashlib.sha256(json.dumps(reviewers, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return {"rows": rows, "metadata": {"rubric": RUBRIC, "evaluator": "human", "study_id": study_id,
        "reviewers_by_doc_sha256": reviewer_digest, "scale": "0=échec, 1=partiel, 2=préservé", "raters_per_document_min": 2,
        "limitation": "jugement humain descriptif ; protocole de revue aveugle à documenter"}}


def human_quality_metrics(rows: Sequence[Mapping[str, Any]], metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Moyennes par document, séparées et normalisées sur [0,1]."""
    if metadata.get("rubric") != RUBRIC or metadata.get("evaluator") != "human":
        raise ValueError("qualité : protocole ou source des évaluations invalide")
    result = {}
    for metric, field in DIMENSIONS.items():
        per_doc = [sum(float(r[field]) for r in row["ratings"]) / (2 * len(row["ratings"])) for row in rows]
        agreement = [int(len({r[field] for r in row["ratings"]}) == 1) for row in rows]
        metric_value = MetricValue(name=metric, value=mean(per_doc), protocol=RUBRIC,
            protocol_version="1", status=MetricStatus.DIAGNOSTIC, direction=MetricDirection.MAXIMIZE,
            details={**metadata, "documents": len(rows), "exact_rater_agreement": mean(agreement),
                     "aggregation": "moyenne des évaluateurs par document puis moyenne des documents"})
        result[metric] = with_interval(metric_value.to_dict(), bootstrap_interval(per_doc, mean, unit="document"))
    return result

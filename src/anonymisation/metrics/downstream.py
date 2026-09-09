"""Évaluation de l'utilité aval (downstream utility) sur tâches de classification (SPEC-07).

Mesure la rétention de performance aval :
    utility_retention = score_anonymized / score_original

Entraîne un classifieur par centroïdes TF-IDF sur le split d'entraînement original
(sans réentraînement sur l'anonymisé), puis évalue sur l'original et l'anonymisé.
Si le score original est nul, si le train est vide ou si les labels manquent,
renvoie UNAVAILABLE avec explication.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from anonymisation.metrics._tfidf import CentroidClassifier, TfidfVectorizer
from anonymisation.metrics.contracts import MetricStatus
from anonymisation.schema.models import Document, TaskLabel


@dataclass(frozen=True)
class DownstreamTaskResult:
    task: str
    metric: str
    protocol: str
    protocol_version: str
    score_original: float | None
    score_anonymized: float | None
    utility_retention: float | None
    train_size: int
    eval_size: int
    method: str
    status: MetricStatus
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "metric": self.metric,
            "protocol": self.protocol,
            "protocol_version": self.protocol_version,
            "score_original": self.score_original,
            "score_anonymized": self.score_anonymized,
            "utility_retention": self.utility_retention,
            "train_size": self.train_size,
            "eval_size": self.eval_size,
            "method": self.method,
            "status": self.status.value,
            "reason": self.reason,
        }


def _accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    if not y_true:
        return 0.0
    correct = sum(1 for yt, yp in zip(y_true, y_pred, strict=True) if yt == yp)
    return correct / len(y_true)


def evaluate_downstream_task(
    *,
    task_name: str,
    train_docs: Sequence[Document],
    train_tasks: Sequence[TaskLabel],
    eval_docs_orig: Sequence[Document],
    eval_docs_anon: Sequence[str],
    eval_tasks: Sequence[TaskLabel],
    protocol: str = "downstream-tfidf",
    protocol_version: str = "1",
) -> DownstreamTaskResult:
    """Évalue une tâche aval de classification textuelle."""
    # Indexer les labels d'entraînement
    train_label_by_doc: dict[str, str] = {
        t.doc_id: str(t.label) for t in train_tasks if t.task == task_name
    }
    train_pairs = [
        (doc.text, train_label_by_doc[doc.doc_id])
        for doc in train_docs
        if doc.doc_id in train_label_by_doc
    ]

    eval_label_by_doc: dict[str, str] = {
        t.doc_id: str(t.label) for t in eval_tasks if t.task == task_name
    }
    eval_pairs_orig = [
        (doc.text, eval_label_by_doc[doc.doc_id])
        for doc in eval_docs_orig
        if doc.doc_id in eval_label_by_doc
    ]
    eval_anon_pairs = [
        (anon_text, eval_label_by_doc[doc.doc_id])
        for doc, anon_text in zip(eval_docs_orig, eval_docs_anon, strict=True)
        if doc.doc_id in eval_label_by_doc
    ]

    if not train_pairs:
        return DownstreamTaskResult(
            task=task_name,
            metric="accuracy",
            protocol=protocol,
            protocol_version=protocol_version,
            score_original=None,
            score_anonymized=None,
            utility_retention=None,
            train_size=0,
            eval_size=len(eval_pairs_orig),
            method="tfidf_centroid",
            status=MetricStatus.UNAVAILABLE,
            reason="données d'entraînement absentes pour cette tâche",
        )

    if not eval_pairs_orig:
        return DownstreamTaskResult(
            task=task_name,
            metric="accuracy",
            protocol=protocol,
            protocol_version=protocol_version,
            score_original=None,
            score_anonymized=None,
            utility_retention=None,
            train_size=len(train_pairs),
            eval_size=0,
            method="tfidf_centroid",
            status=MetricStatus.UNAVAILABLE,
            reason="données d'évaluation absentes pour cette tâche",
        )

    train_texts, train_labels = zip(*train_pairs, strict=True)
    eval_texts_orig, eval_labels = zip(*eval_pairs_orig, strict=True)
    eval_texts_anon, _ = zip(*eval_anon_pairs, strict=True)

    # Entraîner le vectoriseur et le classifieur sur le texte ORIGINAL d'entraînement
    vectorizer = TfidfVectorizer().fit(train_texts)
    train_vecs = [vectorizer.transform_one(t) for t in train_texts]
    classifier = CentroidClassifier().fit(train_vecs, train_labels)

    # Évaluer sur original
    eval_vecs_orig = [vectorizer.transform_one(t) for t in eval_texts_orig]
    preds_orig = classifier.predict(eval_vecs_orig)
    acc_orig = _accuracy(eval_labels, preds_orig)

    # Évaluer sur anonymisé
    eval_vecs_anon = [vectorizer.transform_one(t) for t in eval_texts_anon]
    preds_anon = classifier.predict(eval_vecs_anon)
    acc_anon = _accuracy(eval_labels, preds_anon)

    if acc_orig <= 0.0:
        return DownstreamTaskResult(
            task=task_name,
            metric="accuracy",
            protocol=protocol,
            protocol_version=protocol_version,
            score_original=0.0,
            score_anonymized=acc_anon,
            utility_retention=None,
            train_size=len(train_pairs),
            eval_size=len(eval_pairs_orig),
            method="tfidf_centroid",
            status=MetricStatus.UNAVAILABLE,
            reason="score original nul, rétention indéfinie",
        )

    retention = acc_anon / acc_orig

    return DownstreamTaskResult(
        task=task_name,
        metric="accuracy",
        protocol=protocol,
        protocol_version=protocol_version,
        score_original=acc_orig,
        score_anonymized=acc_anon,
        utility_retention=retention,
        train_size=len(train_pairs),
        eval_size=len(eval_pairs_orig),
        method="tfidf_centroid",
        status=MetricStatus.DIAGNOSTIC,
    )

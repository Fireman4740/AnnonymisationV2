"""Évaluation de l'utilité aval (downstream utility) sur tâches de classification (SPEC-07).

Mesure la rétention de performance aval :
    utility_retention = macro_F1(anonymisé) / macro_F1(original)

Entraîne un classifieur par centroïdes TF-IDF sur le split d'entraînement original
(variante **figée** de SPEC-07 §6 : sans réentraînement sur l'anonymisé), puis
évalue sur l'original et l'anonymisé. Si le score original est nul, si le train
est vide ou si les labels manquent, renvoie UNAVAILABLE avec explication.

Pourquoi le macro-F1 plutôt que l'accuracy (v1) : SPEC-07 §6.B exprime la
rétention en F1 (routage, modération), et l'accuracy masque l'effondrement des
classes rares — un classifieur qui ne prédit plus que la classe majoritaire
après anonymisation garderait une accuracy flatteuse. L'accuracy reste publiée
en détail.

Deux variantes, toujours étiquetées (``variant``) :

* ``frozen`` — protocole principal de TAU-Eval : classifieur entraîné sur le
  train ORIGINAL, figé, appliqué au test original puis anonymisé ;
* ``retrained`` — variante supplémentaire : un second classifieur est entraîné
  sur le train ANONYMISÉ par le même système (run ``predict`` du split train),
  appliqué au test anonymisé ; la référence reste le classifieur original sur
  le test original. Un document de train en erreur d'anonymisation est exclu
  du train anonymisé et compté (``train_excluded``), jamais remplacé par son
  texte original.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from anonymisation.metrics._tfidf import CentroidClassifier, TfidfVectorizer
from anonymisation.metrics.contracts import MetricStatus
from anonymisation.metrics.uncertainty import bootstrap_interval
from anonymisation.schema.models import Document, TaskLabel

PRIMARY_METRIC = "macro_f1"
_VARIANTS = {
    "frozen": "classifieur entraîné sur le train original, figé (protocole principal TAU-Eval)",
    "retrained": "classifieur réentraîné sur le train anonymisé, évalué sur le test anonymisé",
}


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
    accuracy_original: float | None = None
    accuracy_anonymized: float | None = None
    ci95: dict[str, Any] | None = None
    variant: str = "frozen"
    train_excluded: int = 0

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
            "accuracy_original": self.accuracy_original,
            "accuracy_anonymized": self.accuracy_anonymized,
            "variant": self.variant,
            "variant_definition": _VARIANTS[self.variant],
            "train_excluded": self.train_excluded,
            "ci95": self.ci95,
        }


def _accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    if not y_true:
        return 0.0
    correct = sum(1 for yt, yp in zip(y_true, y_pred, strict=True) if yt == yp)
    return correct / len(y_true)


def macro_f1(y_true: Sequence[str], y_pred: Sequence[str]) -> float | None:
    """Macro-F1 sur l'union des labels vrais et prédits (convention scikit-learn).

    Une classe prédite mais absente du gold compte (F1 = 0) : sinon un
    classifieur qui invente des classes après anonymisation ne serait pas pénalisé.
    """
    labels = sorted(set(y_true) | set(y_pred))
    if not labels:
        return None
    scores = []
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == label and p != label)
        denominator = 2 * tp + fp + fn
        scores.append(2 * tp / denominator if denominator else 0.0)
    return sum(scores) / len(scores)


def _retention_of(sample: Sequence[tuple[str, str, str]]) -> float | None:
    """Rétention macro-F1 sur un échantillon apparié (vrai, prédit orig, prédit anon)."""
    truth = [row[0] for row in sample]
    original = macro_f1(truth, [row[1] for row in sample])
    anonymized = macro_f1(truth, [row[2] for row in sample])
    if not original or anonymized is None:
        return None
    return anonymized / original


def evaluate_downstream_task(
    *,
    task_name: str,
    train_docs: Sequence[Document],
    train_tasks: Sequence[TaskLabel],
    eval_docs_orig: Sequence[Document],
    eval_docs_anon: Sequence[str],
    eval_tasks: Sequence[TaskLabel],
    protocol: str = "downstream-tfidf",
    protocol_version: str = "2",
    train_texts_anon: dict[str, str] | None = None,
) -> DownstreamTaskResult:
    """Évalue une tâche aval ; ``train_texts_anon`` active la variante réentraînée."""
    variant = "frozen" if train_texts_anon is None else "retrained"
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
            metric=PRIMARY_METRIC,
            protocol=protocol,
            protocol_version=protocol_version,
            score_original=None,
            score_anonymized=None,
            utility_retention=None,
            train_size=0,
            eval_size=len(eval_pairs_orig),
            method="tfidf_centroid",
            variant=variant,
            status=MetricStatus.UNAVAILABLE,
            reason="données d'entraînement absentes pour cette tâche",
        )

    if not eval_pairs_orig:
        return DownstreamTaskResult(
            task=task_name,
            metric=PRIMARY_METRIC,
            protocol=protocol,
            protocol_version=protocol_version,
            score_original=None,
            score_anonymized=None,
            utility_retention=None,
            train_size=len(train_pairs),
            eval_size=0,
            method="tfidf_centroid",
            variant=variant,
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

    # Évaluer sur anonymisé — classifieur figé, ou réentraîné sur le train anonymisé.
    train_excluded = 0
    if train_texts_anon is None:
        eval_vecs_anon = [vectorizer.transform_one(t) for t in eval_texts_anon]
        preds_anon = classifier.predict(eval_vecs_anon)
    else:
        anon_pairs = [
            (train_texts_anon[doc.doc_id], train_label_by_doc[doc.doc_id])
            for doc in train_docs
            if doc.doc_id in train_label_by_doc and doc.doc_id in train_texts_anon
        ]
        train_excluded = len(train_pairs) - len(anon_pairs)
        if not anon_pairs:
            return DownstreamTaskResult(
                task=task_name, metric=PRIMARY_METRIC, protocol=protocol,
                protocol_version=protocol_version, score_original=None,
                score_anonymized=None, utility_retention=None, train_size=0,
                eval_size=len(eval_pairs_orig), method="tfidf_centroid", variant=variant,
                train_excluded=train_excluded, status=MetricStatus.UNAVAILABLE,
                reason="aucun document de train anonymisé sans erreur",
            )
        anon_texts, anon_labels = zip(*anon_pairs, strict=True)
        anon_vectorizer = TfidfVectorizer().fit(anon_texts)
        anon_classifier = CentroidClassifier().fit(
            [anon_vectorizer.transform_one(t) for t in anon_texts], anon_labels)
        preds_anon = anon_classifier.predict(
            [anon_vectorizer.transform_one(t) for t in eval_texts_anon])

    f1_orig = macro_f1(eval_labels, preds_orig)
    f1_anon = macro_f1(eval_labels, preds_anon)
    acc_orig = _accuracy(eval_labels, preds_orig)
    acc_anon = _accuracy(eval_labels, preds_anon)

    # Garde d'informativité : si le classifieur ne fait pas mieux, sur le texte
    # ORIGINAL, qu'une prédiction constante de la classe majoritaire, il
    # n'utilise pas le texte — sa « rétention » sur l'anonymisé vaudrait 1 par
    # construction (constaté : redact-all à 1.0 sur des tâches à 2 documents).
    majority = classifier.majority_class
    baseline_f1 = macro_f1(eval_labels, [majority] * len(eval_labels)) if majority else None
    if f1_orig is not None and baseline_f1 is not None and f1_orig <= baseline_f1:
        return DownstreamTaskResult(
            task=task_name,
            metric=PRIMARY_METRIC,
            protocol=protocol,
            protocol_version=protocol_version,
            score_original=f1_orig,
            score_anonymized=f1_anon,
            utility_retention=None,
            train_size=len(train_pairs),
            eval_size=len(eval_pairs_orig),
            method="tfidf_centroid",
            variant=variant,
            status=MetricStatus.UNAVAILABLE,
            reason=(
                f"classifieur aval non informatif : macro-F1 original {f1_orig:.3f} "
                f"≤ classe majoritaire {baseline_f1:.3f} ; rétention non définie"
            ),
            accuracy_original=acc_orig,
            accuracy_anonymized=acc_anon,
        )

    if not f1_orig:
        return DownstreamTaskResult(
            task=task_name,
            metric=PRIMARY_METRIC,
            protocol=protocol,
            protocol_version=protocol_version,
            score_original=f1_orig,
            score_anonymized=f1_anon,
            utility_retention=None,
            train_size=len(train_pairs),
            eval_size=len(eval_pairs_orig),
            method="tfidf_centroid",
            variant=variant,
            status=MetricStatus.UNAVAILABLE,
            reason="macro-F1 original nul, rétention indéfinie",
            accuracy_original=acc_orig,
            accuracy_anonymized=acc_anon,
        )

    # Bootstrap APPARIÉ : un même document tiré compte pour l'original et pour
    # l'anonymisé, ce qui neutralise la variance propre au corpus d'évaluation.
    paired = list(zip(eval_labels, preds_orig, preds_anon, strict=True))
    return DownstreamTaskResult(
        task=task_name,
        metric=PRIMARY_METRIC,
        protocol=protocol,
        protocol_version=protocol_version,
        score_original=f1_orig,
        score_anonymized=f1_anon,
        utility_retention=(f1_anon or 0.0) / f1_orig,
        train_size=len(train_pairs),
        eval_size=len(eval_pairs_orig),
        method="tfidf_centroid",
        variant=variant,
        train_excluded=train_excluded,
        status=MetricStatus.DIAGNOSTIC,
        accuracy_original=acc_orig,
        accuracy_anonymized=acc_anon,
        ci95=bootstrap_interval(paired, _retention_of, unit="document"),
    )

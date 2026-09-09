"""Tests unitaires pour metrics/downstream.py et metrics/_tfidf.py."""

from __future__ import annotations

from anonymisation.metrics._tfidf import CentroidClassifier, TfidfVectorizer
from anonymisation.metrics.contracts import MetricStatus
from anonymisation.metrics.downstream import evaluate_downstream_task
from anonymisation.schema.models import Document, Domain, LabelType, TaskLabel


def test_tfidf_vectorizer_and_centroid_classifier():
    texts = [
        "J'adore le football et le sport",
        "Le match de football était incroyable",
        "La physique quantique et les mathématiques",
        "Théorie des quanta et algèbre linéaire",
    ]
    labels = ["sport", "sport", "science", "science"]

    vec = TfidfVectorizer().fit(texts)
    assert len(vec.vocabulary) > 0
    sparse_vecs = [vec.transform_one(t) for t in texts]

    clf = CentroidClassifier().fit(sparse_vecs, labels)
    assert clf.classes == ["science", "sport"]

    preds = clf.predict(sparse_vecs)
    assert preds == labels


def test_downstream_task_evaluation():
    train_docs = [
        Document(doc_id="d1", dataset="ds", split="train", domain=Domain.GENERIC, language="fr", text="problème de mot de passe et connexion"),
        Document(doc_id="d2", dataset="ds", split="train", domain=Domain.GENERIC, language="fr", text="accès refusé identifiant erroné"),
        Document(doc_id="d3", dataset="ds", split="train", domain=Domain.GENERIC, language="fr", text="facturation erronée paiement débit"),
        Document(doc_id="d4", dataset="ds", split="train", domain=Domain.GENERIC, language="fr", text="remboursement facture et prix"),
    ]
    train_tasks = [
        TaskLabel(doc_id="d1", task="cat", label="auth", label_type=LabelType.SINGLE),
        TaskLabel(doc_id="d2", task="cat", label="auth", label_type=LabelType.SINGLE),
        TaskLabel(doc_id="d3", task="cat", label="billing", label_type=LabelType.SINGLE),
        TaskLabel(doc_id="d4", task="cat", label="billing", label_type=LabelType.SINGLE),
    ]

    eval_docs_orig = [
        Document(doc_id="e1", dataset="ds", split="test", domain=Domain.GENERIC, language="fr", text="impossible de me connecter mot de passe"),
        Document(doc_id="e2", dataset="ds", split="test", domain=Domain.GENERIC, language="fr", text="question sur ma facture et le paiement"),
    ]
    eval_docs_anon = [
        "impossible de me connecter [MOTDEPASSE_SUPPRIME]",
        "question sur ma facture et le paiement",
    ]
    eval_tasks = [
        TaskLabel(doc_id="e1", task="cat", label="auth", label_type=LabelType.SINGLE),
        TaskLabel(doc_id="e2", task="cat", label="billing", label_type=LabelType.SINGLE),
    ]

    res = evaluate_downstream_task(
        task_name="cat",
        train_docs=train_docs,
        train_tasks=train_tasks,
        eval_docs_orig=eval_docs_orig,
        eval_docs_anon=eval_docs_anon,
        eval_tasks=eval_tasks,
    )

    assert res.status == MetricStatus.DIAGNOSTIC
    assert res.score_original == 1.0
    assert res.score_anonymized == 1.0
    assert res.utility_retention == 1.0

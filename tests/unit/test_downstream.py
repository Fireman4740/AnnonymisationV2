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


def test_macro_f1_exposes_minority_class_collapse():
    """L'accuracy masque l'effondrement d'une classe rare ; le macro-F1 non."""
    from anonymisation.metrics.downstream import macro_f1

    truth = ["a"] * 9 + ["b"]
    collapsed = ["a"] * 10
    accuracy = sum(t == p for t, p in zip(truth, collapsed, strict=True)) / len(truth)
    assert accuracy == 0.9
    f1 = macro_f1(truth, collapsed)
    assert f1 is not None and f1 < 0.5
    assert macro_f1(truth, truth) == 1.0
    assert macro_f1([], []) is None


def test_downstream_result_declares_variant_and_interval():
    train_docs = [
        Document(doc_id=f"t{i}", dataset="ds", split="train", domain=Domain.GENERIC,
                 language="fr", text=text)
        for i, text in enumerate([
            "mot de passe connexion", "identifiant connexion refusée",
            "facture paiement", "remboursement facture",
        ])
    ]
    train_tasks = [
        TaskLabel(doc_id=f"t{i}", task="cat", label=label, label_type=LabelType.SINGLE)
        for i, label in enumerate(["auth", "auth", "billing", "billing"])
    ]
    eval_docs = [
        Document(doc_id=f"e{i}", dataset="ds", split="test", domain=Domain.GENERIC,
                 language="fr", text=text)
        for i, text in enumerate([
            "connexion mot de passe", "identifiant refusé connexion",
            "paiement facture", "facture remboursement",
        ])
    ]
    eval_tasks = [
        TaskLabel(doc_id=f"e{i}", task="cat", label=label, label_type=LabelType.SINGLE)
        for i, label in enumerate(["auth", "auth", "billing", "billing"])
    ]
    res = evaluate_downstream_task(
        task_name="cat", train_docs=train_docs, train_tasks=train_tasks,
        eval_docs_orig=eval_docs, eval_docs_anon=[d.text for d in eval_docs],
        eval_tasks=eval_tasks,
    )
    payload = res.to_dict()
    assert payload["metric"] == "macro_f1"
    assert payload["variant"].startswith("frozen")
    assert payload["retrained_variant"].startswith("unavailable")
    assert payload["accuracy_original"] == 1.0
    assert res.ci95 is not None and res.ci95["low"] <= 1.0 <= res.ci95["high"]


def test_empty_text_predicts_prior_class_not_alphabetical_first():
    clf = CentroidClassifier().fit([{0: 1.0}, {1: 1.0}, {1: 1.0}], ["a_rare", "z_major", "z_major"])
    assert clf.predict_one({}) == "z_major"
    assert clf.predict_one({99: 1.0}) == "z_major"  # aucun terme commun


def test_non_informative_classifier_gives_unavailable_retention():
    """Classifieur qui ne bat pas la classe majoritaire : rétention non définie."""
    docs = [
        Document(doc_id=f"t{i}", dataset="ds", split="train", domain=Domain.GENERIC,
                 language="fr", text=t)
        for i, t in enumerate(["alpha beta", "gamma delta", "epsilon"])
    ]
    tasks = [TaskLabel(doc_id=f"t{i}", task="cat", label="same", label_type=LabelType.SINGLE)
             for i in range(3)]
    evals = [Document(doc_id="e0", dataset="ds", split="test", domain=Domain.GENERIC,
                      language="fr", text="alpha"),
             Document(doc_id="e1", dataset="ds", split="test", domain=Domain.GENERIC,
                      language="fr", text="gamma")]
    eval_tasks = [TaskLabel(doc_id=f"e{i}", task="cat", label="same", label_type=LabelType.SINGLE)
                  for i in range(2)]
    res = evaluate_downstream_task(
        task_name="cat", train_docs=docs, train_tasks=tasks, eval_docs_orig=evals,
        eval_docs_anon=["[SUPPRIME]", "[SUPPRIME]"], eval_tasks=eval_tasks,
    )
    assert res.utility_retention is None
    assert res.status == MetricStatus.UNAVAILABLE
    assert "non informatif" in (res.reason or "")

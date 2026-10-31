"""Étape locale explicite : évaluateur de tâche et références populationnelles.

Cette commande peut entraîner un évaluateur scikit-learn sur le train original.
Elle fige ses prédictions ; `score` ne fait ensuite aucun entraînement/appel.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from anonymisation.metrics.reference_inputs import counted_combinations
from anonymisation.metrics.research import official_library
from anonymisation.schema.integrity import locked_files, verify_pivot_files
from anonymisation.schema.io import read_jsonl, sha256_file, write_json
from anonymisation.schema.models import Combination, Document, LabelType, TaskLabel

EVALUATION_FILE = "evaluation.json"
EVALUATION_LOCK = "evaluation.lock.json"
PROTOCOL = "independent-evaluation-inputs"
VERSION = "1"


def _unique(items: Sequence[Any], key: str) -> dict[str, Any]:
    result = {}
    for item in items:
        value = getattr(item, key)
        if value in result:
            raise ValueError(f"{key} dupliqué : {value}")
        result[value] = item
    return result


def _groups(documents: Sequence[Document]) -> set[tuple[str, str]]:
    return {("subject" if key == "author_id" else key, value) for doc in documents for key in ("author_id", "thread_id")
            if (value := getattr(doc, key))} | {
                ("subject", subject) for doc in documents for subject in doc.subject_ids
            }


def freeze_task(
    train: Sequence[Document], train_labels: Sequence[TaskLabel],
    evaluation: Sequence[Document], evaluation_labels: Sequence[TaskLabel],
    predictions: Mapping[str, Mapping[str, Any]], *, task: str,
) -> dict[str, Any]:
    from sklearn.dummy import DummyClassifier
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    library = official_library()
    train_by_id = _unique(train, "doc_id")
    eval_by_id = _unique(evaluation, "doc_id")
    if train_by_id.keys() & eval_by_id.keys() or {d.text for d in train} & {d.text for d in evaluation} or _groups(train) & _groups(evaluation):
        raise ValueError("fuite train/test : documents, textes, auteurs, sujets ou fils communs")

    def labels(items: Sequence[TaskLabel]) -> dict[str, str]:
        selected = [t for t in items if t.task == task]
        if any(t.label_type != LabelType.SINGLE or not isinstance(t.label, str) for t in selected):
            raise ValueError("évaluation de tâche v1 : classification single-label textuelle requise")
        return {doc_id: t.label for doc_id, t in _unique(selected, "doc_id").items()}

    train_y, test_y = labels(train_labels), labels(evaluation_labels)
    if train_y.keys() - train_by_id.keys() or test_y.keys() - eval_by_id.keys():
        raise ValueError("label de tâche sans document")
    train_docs = [d for d in train if d.doc_id in train_y]
    if any(doc_id not in test_y for doc_id in predictions):
        raise ValueError("label de tâche manquant pour un document évalué")
    selected = [d for d in evaluation if d.doc_id in predictions]
    vocabulary = sorted({train_y[d.doc_id] for d in train_docs})
    if len(vocabulary) < 2 or not selected:
        raise ValueError("évaluation de tâche : train à deux classes et test non vide requis")
    if set(test_y.values()) - set(vocabulary):
        raise ValueError("classes de test absentes du train")
    # Paramètres fixes, sans recherche d'hyperparamètres sur le test.
    settings = {"vectorizer": "sklearn.feature_extraction.text.TfidfVectorizer",
                "ngram_range": [1, 2], "classifier": "sklearn.linear_model.LogisticRegression",
                "C": 1.0, "solver": "lbfgs", "max_iter": 1000, "random_state": 42,
                "class_weight": "balanced"}
    model = make_pipeline(TfidfVectorizer(ngram_range=(1, 2)), LogisticRegression(
        C=1.0, solver="lbfgs", max_iter=1000, random_state=42, class_weight="balanced"))
    import warnings

    from sklearn.exceptions import ConvergenceWarning

    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        model.fit([d.text for d in train_docs], [train_y[d.doc_id] for d in train_docs])
    original = model.predict([d.text for d in selected])
    anonymized = model.predict([predictions[d.doc_id]["anonymized_text"] for d in selected])
    baseline = DummyClassifier(strategy="most_frequent").fit(
        [[0]] * len(train_docs), [train_y[d.doc_id] for d in train_docs])
    majority = baseline.predict([[0]] * len(selected))
    classifier = model.steps[-1][1]
    vectorizer = model.steps[0][1]
    digest = hashlib.sha256(json.dumps({"vocabulary": vectorizer.vocabulary_,
        "idf": vectorizer.idf_.tolist(), "coef": classifier.coef_.tolist(),
        "intercept": classifier.intercept_.tolist(), "classes": classifier.classes_.tolist()},
        sort_keys=True).encode()).hexdigest()
    rows = [{"doc_id": d.doc_id, "gold": test_y[d.doc_id], "original": str(o),
             "anonymized": str(a), "majority": str(m)}
            for d, o, a, m in zip(selected, original, anonymized, majority, strict=True)]
    return {"rows": rows, "metadata": {"task": task, "labels": vocabulary, "library": library,
            "evaluator": settings, "model_sha256": digest, "train_documents": len(train_docs),
            "variant": "frozen-original-train", "group_disjointness": "author_id, subject_ids, thread_id si disponibles",
            "limitation": "évaluateur linéaire de référence ; validation sur le domaine nécessaire"}}


def cmd_evaluate(run: str | Path, *, task: str | None = None, train_split: str = "train",
                 population: str | Path | None = None, k_threshold: int = 10,
                 quality_ratings: str | Path | None = None,
                 local_quality_backend: str | None = None, local_quality_workers: int = 2) -> int:
    from anonymisation.cli import score

    run_dir = Path(run)
    if task is None and population is None and quality_ratings is None and local_quality_backend is None:
        raise ValueError("evaluate : --task, --population, --quality-ratings ou --local-quality-backend requis")
    # Une tentative échouée ne doit pas laisser une ancienne évaluation utilisable.
    (run_dir / EVALUATION_LOCK).unlink(missing_ok=True)
    (run_dir / EVALUATION_FILE).unlink(missing_ok=True)
    (run_dir / score.SCORECARD_NAME).unlink(missing_ok=True)
    lock = score._read_json(run_dir / score.LOCK_NAME)
    dataset, split = lock["run"]["dataset"], lock["run"]["split"]
    inputs = score._verify_inputs(run_dir, lock, dataset, split)
    files = locked_files(lock["data_version"], context="evaluate")
    root = score.PROCESSED_ROOT / dataset
    predictions = score._read_predictions(run_dir / score.PREDICTIONS_NAME)
    if len({r["doc_id"] for r in predictions}) != len(predictions):
        raise ValueError("prédictions : doc_id dupliqué")
    successful = {r["doc_id"]: r for r in predictions if r.get("status") in {"ok", "partial"}}
    if not successful:
        raise ValueError("aucune prédiction sans erreur à évaluer")
    payload: dict[str, Any] = {}
    external = {}
    if task is not None:
        if split not in {"test", "eval"} or train_split == split:
            raise ValueError("utilité : test indépendant requis, train_split distinct du test")
        for part in (split, train_split):
            inputs["pivot"].update(verify_pivot_files(root, part, ("documents.jsonl", "tasks.jsonl"), files,
                context="evaluate task", required=("documents.jsonl", "tasks.jsonl")))
        train = list(read_jsonl(root / train_split / "documents.jsonl", Document))
        evaluation = list(read_jsonl(root / split / "documents.jsonl", Document))
        payload["utility"] = freeze_task(train, list(read_jsonl(root / train_split / "tasks.jsonl", TaskLabel)),
            evaluation, list(read_jsonl(root / split / "tasks.jsonl", TaskLabel)), successful, task=task)
    if population is not None:
        if isinstance(k_threshold, bool) or not isinstance(k_threshold, int) or k_threshold < 1:
            raise ValueError("k_threshold doit être un entier positif")
        inputs["pivot"].update(verify_pivot_files(root, split, ("combinations.jsonl",), files,
            context="evaluate population", required=("combinations.jsonl",)))
        population_path = Path(population).resolve()
        population_data = score._read_json(population_path)
        external[str(population_path)] = sha256_file(population_path)
        combinations = [c.model_dump(mode="json") for c in read_jsonl(root / split / "combinations.jsonl", Combination)]
        # Un sous-échantillon du pivot n'a pas à contenir tous ses sujets.
        requested = {r["doc_id"] for r in predictions}
        combinations = [c for c in combinations if set(c["doc_ids"]) & requested]
        payload["population"] = {"combinations": counted_combinations(population_data, combinations),
            "metadata": {"population_id": population_data["population_id"], "kind": population_data["kind"],
                         "population_sha256": external[str(population_path)],
                         "population_size": len(population_data["records"]), "k_threshold": k_threshold,
                         "matching": "exact-normalized-equality-v1"}}
    if quality_ratings is not None:
        from anonymisation.metrics.text_quality import freeze_human_quality

        quality_path = Path(quality_ratings).resolve()
        quality_data = score._read_json(quality_path)
        payload["text_quality"] = freeze_human_quality(quality_data, successful)
        external[str(quality_path)] = sha256_file(quality_path)
    if local_quality_backend is not None:
        from anonymisation.judge.local_quality import freeze_local_quality

        docs = {d.doc_id: d for d in read_jsonl(root / split / "documents.jsonl", Document)}
        payload["local_quality"] = freeze_local_quality(docs, successful,
            backend_name=local_quality_backend, workers=local_quality_workers)
    context = {"pivot": inputs["pivot"], "external": external,
               "successful_doc_ids": sorted(successful)}
    for section in payload.values():
        section["metadata"]["evaluation_context"] = context
    write_json(run_dir / EVALUATION_FILE, payload)
    write_json(run_dir / EVALUATION_LOCK, {"protocol": PROTOCOL, "protocol_version": VERSION,
        "inputs": inputs, "external": external, "source_sha256": sha256_file(Path(__file__)),
        "outputs": {EVALUATION_FILE: sha256_file(run_dir / EVALUATION_FILE)}})
    print(f"evaluate : références et prédictions de tâche figées — {run_dir / EVALUATION_FILE}")
    return 0


def load_evaluation(run_dir: Path, lock: Mapping[str, Any], inputs: Mapping[str, Any],
                    expected_doc_ids: set[str]) -> dict[str, Any] | None:
    """Charge une étape figée ; toute dépendance modifiée rend l'étape invalide."""
    from anonymisation.cli import score
    from anonymisation.schema.integrity import verify_run_outputs

    path = run_dir / EVALUATION_LOCK
    if not path.is_file():
        if (run_dir / EVALUATION_FILE).exists():
            raise ValueError("evaluation.json sans evaluation.lock.json")
        return None
    evaluation_lock = score._read_json(path)
    if evaluation_lock.get("protocol") != PROTOCOL or evaluation_lock.get("protocol_version") != VERSION:
        raise ValueError("évaluation : protocole/version non pris en charge")
    frozen_inputs = evaluation_lock["inputs"]
    if frozen_inputs["run"] != inputs["run"]:
        raise ValueError("évaluation menée sur d'autres prédictions")
    files = locked_files(lock["data_version"], context="score evaluation")
    root = score.PROCESSED_ROOT / lock["run"]["dataset"]
    for key, sha in frozen_inputs["pivot"].items():
        if files.get(key) != sha or sha256_file(root / key) != sha:
            raise ValueError(f"évaluation : pivot modifié/non verrouillé : {key}")
    if not inputs["pivot"].items() <= frozen_inputs["pivot"].items():
        raise ValueError("évaluation : gold différent")
    for filename, sha in evaluation_lock["external"].items():
        if sha256_file(Path(filename)) != sha:
            raise ValueError("évaluation : référence externe modifiée")
    outputs = verify_run_outputs(run_dir, evaluation_lock["outputs"], (EVALUATION_FILE,), context="score evaluation")
    payload = score._read_json(run_dir / EVALUATION_FILE)
    if set(payload) - {"utility", "population", "text_quality", "local_quality"}:
        raise ValueError("évaluation : section inconnue")
    for section in payload.values():
        context = section["metadata"]["evaluation_context"]
        if context != {"pivot": frozen_inputs["pivot"], "external": evaluation_lock["external"],
                       "successful_doc_ids": sorted(expected_doc_ids)}:
            raise ValueError("évaluation : documents ou références divergents")
    if "utility" in payload and {r["doc_id"] for r in payload["utility"]["rows"]} != expected_doc_ids:
        raise ValueError("évaluation : couverture des documents de tâche divergente")
    if "text_quality" in payload and {r["doc_id"] for r in payload["text_quality"]["rows"]} != expected_doc_ids:
        raise ValueError("évaluation : couverture des notes humaines divergente")
    if "local_quality" in payload and {r["doc_id"] for r in payload["local_quality"]["rows"]} != expected_doc_ids:
        raise ValueError("évaluation : couverture des notes locales divergente")
    # Le scorer conserve les empreintes de TOUTES ses dépendances indirectes.
    inputs["pivot"].update(frozen_inputs["pivot"])
    inputs["run"].update(outputs)
    inputs["run"][EVALUATION_LOCK] = sha256_file(path)
    inputs["external"] = evaluation_lock["external"]
    return payload

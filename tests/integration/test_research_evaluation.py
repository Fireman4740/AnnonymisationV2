"""Étape evaluate -> score -> replay, dépendances verrouillées et absence de modèle."""

import copy
import json

import pytest

from anonymisation.cli import score
from anonymisation.cli.evaluate import cmd_evaluate
from anonymisation.metrics.comparison import MetricComparisonError, assert_comparable_across_systems
from anonymisation.schema.io import sha256_file


def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


@pytest.fixture
def reference_run(tmp_path, monkeypatch):
    root = tmp_path / "processed"
    monkeypatch.setattr(score, "PROCESSED_ROOT", root)
    config = tmp_path / "configs"
    config.mkdir()
    (config / "mini.yaml").write_text("evaluation:\n  protocol: mini-v1\n  protocol_version: '1'\n  default_metric_status: DIAGNOSTIC\n  gold_scope:\n    exhaustive: true\n    reason: fixture de test\n")
    monkeypatch.setattr(score, "DATASETS_CONFIG", config)
    texts = {"train": ["paiement facture carte", "facture montant paiement", "connexion compte motdepasse", "compte connexion accès"],
             "test": ["20 ans carte facture paiement", "30 ans accès compte connexion"]}
    docs = {}
    hashes = {}
    for split, values in texts.items():
        docs[split] = [{"doc_id": f"{split}:{i}", "dataset": "mini", "split": split, "domain": "support", "language": "fr", "text": text}
                       for i, text in enumerate(values)]
        labels = [{"doc_id": d["doc_id"], "task": "routing", "label_type": "single",
                   "label": "billing" if i < len(values) // 2 else "login"} for i, d in enumerate(docs[split])]
        _jsonl(root / "mini" / split / "documents.jsonl", docs[split])
        _jsonl(root / "mini" / split / "tasks.jsonl", labels)
        for name in ("documents.jsonl", "tasks.jsonl"):
            hashes[f"{split}/{name}"] = sha256_file(root / "mini" / split / name)
    gold = [{"annotation_id": "ann", "doc_id": "test:0", "start": 0, "end": 2, "span_text": "20",
             "identifier_type": "QUASI", "qi_categories": ["GEN_AGE"], "expression_mode": "EXPLICIT",
             "granularity": "EXACT", "stability": "STABLE"}]
    _jsonl(root / "mini" / "test" / "annotations.jsonl", gold)
    hashes["test/annotations.jsonl"] = sha256_file(root / "mini" / "test" / "annotations.jsonl")
    combinations = [{"combination_id": "c", "dataset": "mini", "target_type": "person", "target_id": "p1", "scope": "document",
                     "population_id": "pop", "doc_ids": ["test:0"], "annotation_ids": ["ann"], "k_true": 2,
                     "qi_set": [{"qi_category": "GEN_AGE", "normalized": {"exact": 20}}],
                     "risk_model": "prosecutor", "at_risk": True, "source": "generated"}]
    _jsonl(root / "mini" / "test" / "combinations.jsonl", combinations)
    hashes["test/combinations.jsonl"] = sha256_file(root / "mini" / "test" / "combinations.jsonl")
    population = tmp_path / "population.json"
    population.write_text(json.dumps({"schema_version": "1", "population_id": "pop", "kind": "synthetic_controlled",
        "records": [{"subject_id": "p1", "attributes": {"GEN_AGE": {"exact": 20}}},
                    {"subject_id": "p2", "attributes": {"GEN_AGE": {"exact": 20}}}]}))
    run = tmp_path / "run"
    run.mkdir()
    predictions = [{"doc_id": d["doc_id"], "status": "ok", "error": [], "annotations": gold if i == 0 else [],
                    "decisions": [], "anonymized_text": d["text"], "runtime_ms": 1.0,
                    "risk": {"k_hat": 2, "population_id": "pop", "combination_id": "c"} if i == 0 else None}
                   for i, d in enumerate(docs["test"])]
    _jsonl(run / "predictions.jsonl", predictions)
    lock = {"run": {"dataset": "mini", "split": "test", "profile": "identity", "policy": "P2", "status": "complete"},
            "data_version": {"source": "fixture", "files": hashes}, "taxonomy_version": "1.0",
            "code": {"git_commit": "fixture", "git_dirty": False}, "models": [], "seeds": {"determinism": 42},
            "prompts": [], "policy": {"id": "P2", "source": "fixture", "sha256": "a" * 64},
            "system": {"system_id": "fixture", "system_version": "1", "capabilities": ["spans", "risk", "decisions"]},
            "outputs": {"predictions.jsonl": sha256_file(run / "predictions.jsonl")}}
    (run / "manifest.lock.json").write_text(json.dumps(lock))
    return run, population


def test_evaluate_score_replay_without_training_or_model_calls(reference_run, monkeypatch):
    from sklearn.linear_model import LogisticRegression

    run, population = reference_run
    assert cmd_evaluate(run, task="routing", population=population) == 0

    def forbidden(*args, **kwargs):
        raise AssertionError("entraînement appelé pendant score")

    monkeypatch.setattr(LogisticRegression, "fit", forbidden)
    assert score.cmd_score(run, "mini-v1") == 0
    before = (run / "scorecard.json").read_bytes()
    card = json.loads(before)
    assert card["diagnostic"]["utility_retention"]["value"] == 1
    assert card["diagnostic"]["task_f1_delta"]["value"] == 0
    assert card["diagnostic"]["qicr"]["value"] == 1
    assert card["diagnostic"]["male_k"]["value"] == 0
    assert "brier" in card["not_applicable"]
    assert card["inputs"]["external"][str(population)] == sha256_file(population)
    assert "train/tasks.jsonl" in card["inputs"]["pivot"]
    assert score.cmd_score(run, "mini-v1") == 0
    assert before == (run / "scorecard.json").read_bytes()


@pytest.mark.parametrize("changed", ["population", "train", "predictions", "evaluation", "orphan"])
def test_stale_reference_or_outputs_never_leave_old_scorecard(reference_run, changed):
    run, population = reference_run
    cmd_evaluate(run, task="routing", population=population)
    (run / "scorecard.json").write_text("stale")
    if changed == "population":
        population.write_text(population.read_text() + " ")
    elif changed == "train":
        path = score.PROCESSED_ROOT / "mini/train/tasks.jsonl"
        path.write_text(path.read_text() + " ")
    elif changed == "predictions":
        path = run / "predictions.jsonl"
        path.write_text(path.read_text() + " ")
    elif changed == "evaluation":
        (run / "evaluation.json").write_text("{}")
    else:
        (run / "evaluation.lock.json").unlink()
    with pytest.raises(ValueError):
        score.cmd_score(run, "mini-v1")
    assert not (run / "scorecard.json").exists()


def test_comparison_rejects_different_evaluator_or_reference(reference_run):
    run, population = reference_run
    cmd_evaluate(run, task="routing", population=population)
    score.cmd_score(run, "mini-v1")
    card = json.loads((run / "scorecard.json").read_text())
    other = copy.deepcopy(card)
    other["diagnostic"]["utility_retention"]["details"]["model_sha256"] = "different"
    with pytest.raises(MetricComparisonError, match="définition incompatible"):
        assert_comparable_across_systems([card, other])
    other = copy.deepcopy(card)
    other["diagnostic"]["qicr"]["details"]["k_threshold"] = 5
    with pytest.raises(MetricComparisonError, match="définition incompatible"):
        assert_comparable_across_systems([card, other])


def test_failed_evaluation_invalidates_previous_result(reference_run):
    run, population = reference_run
    cmd_evaluate(run, task="routing", population=population)
    with pytest.raises(ValueError, match="entier positif"):
        cmd_evaluate(run, population=population, k_threshold=0)
    assert not (run / "evaluation.lock.json").exists()


def test_observed_event_calibration_is_wired_to_verified_attack_and_run(reference_run):
    run, _ = reference_run
    attacker = {"model": "frozen-test-attacker", "temperature": 0}
    contract = {"protocol": "ratbench-staab-correctmatch", "protocol_version": "2",
                "attacker": attacker, "event": "ratbench_reidentified", "text_stage": "anonymized"}
    predictions = [json.loads(line) for line in (run / "predictions.jsonl").read_text().splitlines()]
    for i, row in enumerate(predictions):
        row["risk"] = {"event_forecast": {"probability": [0.1, 0.9][i], "contract": contract}}
    _jsonl(run / "predictions.jsonl", predictions)
    lock_path = run / "manifest.lock.json"
    lock = json.loads(lock_path.read_text())
    lock["outputs"]["predictions.jsonl"] = sha256_file(run / "predictions.jsonl")
    profiles = score.PROCESSED_ROOT / "mini/test/profiles.jsonl"
    profiles.write_text("[]\n")
    lock["data_version"]["files"]["test/profiles.jsonl"] = sha256_file(profiles)
    lock_path.write_text(json.dumps(lock))
    attacks = [{"doc_id": row["doc_id"], "status": "ok", "reidentified": bool(i),
                "correctmatch_correctness": [0.0, 0.9][i], "correct_direct_ids": [], "difficulty": 1}
               for i, row in enumerate(predictions)]
    _jsonl(run / "attacks.jsonl", attacks)
    attack_lock = {"protocol": "ratbench-staab-correctmatch", "protocol_version": "2", "attacker": attacker,
                   "inputs": {"predictions.jsonl": lock["outputs"]["predictions.jsonl"], "profiles.jsonl": sha256_file(profiles)},
                   "outputs": {"attacks.jsonl": sha256_file(run / "attacks.jsonl")},
                   "documents": 2, "documents_error": 0, "error_rate": 0.0, "publishable": True}
    (run / "attack.lock.json").write_text(json.dumps(attack_lock))
    assert score.cmd_score(run, "mini-v1") == 0
    card = json.loads((run / "scorecard.json").read_text())
    assert card["diagnostic"]["brier"]["value"] == pytest.approx(0.01)
    assert card["diagnostic"]["ece"]["value"] == pytest.approx(0.1)
    # Ajouter ou modifier une prévision après l'attaque invalide son lien au run.
    predictions[0]["risk"]["event_forecast"]["probability"] = 0.0
    _jsonl(run / "predictions.jsonl", predictions)
    lock["outputs"]["predictions.jsonl"] = sha256_file(run / "predictions.jsonl")
    lock_path.write_text(json.dumps(lock))
    with pytest.raises(ValueError, match="autres prédictions"):
        score.cmd_score(run, "mini-v1")


def test_human_quality_is_frozen_scored_and_invalidated_if_modified(reference_run, tmp_path):
    import hashlib

    run, _ = reference_run
    predictions = [json.loads(line) for line in (run / 'predictions.jsonl').read_text().splitlines()]
    rows = []
    for item in predictions:
        rows.append({'doc_id': item['doc_id'],
            'anonymized_sha256': hashlib.sha256(item['anonymized_text'].encode()).hexdigest(),
            'ratings': [{'rater': 'r1', 'readability': 2, 'relevance': 1, 'faithfulness': 2},
                        {'rater': 'r2', 'readability': 2, 'relevance': 2, 'faithfulness': 2}]})
    ratings = tmp_path / 'ratings.json'
    ratings.write_text(json.dumps({'rubric': 'human-text-quality-v1', 'evaluator': 'human', 'study_id': 'study-1', 'rows': rows}))
    assert cmd_evaluate(run, task='routing', quality_ratings=ratings) == 0
    assert score.cmd_score(run, 'mini-v1') == 0
    card = json.loads((run / 'scorecard.json').read_text())
    assert card['diagnostic']['human_readability']['value'] == 1.0
    assert card['diagnostic']['human_relevance']['value'] == 0.75
    assert card['diagnostic']['human_faithfulness']['value'] == 1.0
    assert card['inputs']['external'][str(ratings)] == sha256_file(ratings)
    other = copy.deepcopy(card)
    for name in ('utility_retention', 'task_f1_delta', 'human_readability', 'human_relevance', 'human_faithfulness'):
        other['diagnostic'][name]['details']['evaluation_context']['external'] = {'other-rating-file': 'different'}
    assert_comparable_across_systems([card, other])
    other['diagnostic']['human_readability']['details']['reviewers_by_doc_sha256'] = 'different'
    with pytest.raises(MetricComparisonError, match='définition incompatible'):
        assert_comparable_across_systems([card, other])
    ratings.write_text(ratings.read_text() + ' ')
    with pytest.raises(ValueError, match='modifiée|modifié'):
        score.cmd_score(run, 'mini-v1')


def test_quality_template_is_unscored_until_reviewed(reference_run, tmp_path):
    from scripts.prepare_text_quality import prepare

    run, _ = reference_run
    template = tmp_path / 'template.json'
    anonymous = tmp_path / 'readability.json'
    paired = tmp_path / 'review.json'
    assert prepare(run, template, study_id='study-1', raters=['r1', 'r2'],
                   review_out=paired, readability_out=anonymous) == 2
    data = json.loads(template.read_text())
    assert data['rows'][0]['ratings'][0]['readability'] is None
    assert 'original' not in json.loads(anonymous.read_text())['documents'][0]
    assert 'original' in json.loads(paired.read_text())['documents'][0]
    with pytest.raises(ValueError, match='entier'):
        cmd_evaluate(run, quality_ratings=template)


def test_local_quality_is_frozen_and_scored_offline(reference_run, monkeypatch):
    from anonymisation.judge import local_quality
    from sklearn.linear_model import LogisticRegression

    run, _ = reference_run
    def fake(documents, predictions, *, backend_name, workers):
        rows=[]
        for doc_id in sorted(predictions):
            rows.append({'doc_id':doc_id,'status':'ok','error':None,'readability':2,'relevance':1,'faithfulness':2,
                         'controls':{'empty_readability':0,'empty_relevance':0,'empty_faithfulness':0,
                                     'identity_relevance':2,'identity_faithfulness':2}})
        return {'rows':rows,'metadata':{'protocol':'local-quality-anchors-v1',
                'judge':{'model':'stub','backend':backend_name,'temperature':0.0}}}
    monkeypatch.setattr(local_quality,'freeze_local_quality',fake)
    assert cmd_evaluate(run,task='routing',local_quality_backend='stub')==0
    monkeypatch.setattr(LogisticRegression,'fit',lambda *a,**k: (_ for _ in ()).throw(AssertionError('train')))
    assert score.cmd_score(run,'mini-v1')==0
    card=json.loads((run/'scorecard.json').read_text())
    assert card['diagnostic']['local_readability']['value']==1.0
    assert card['diagnostic']['local_relevance']['value']==0.5
    assert card['diagnostic']['local_faithfulness']['value']==1.0
    assert card['diagnostic']['local_relevance']['status']=='diagnostic'

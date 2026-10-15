"""Parité avec les calculs officiels et cas adverses des nouveaux protocoles."""

import copy

import pytest
from sklearn.calibration import calibration_curve
from sklearn.metrics import brier_score_loss, f1_score

from anonymisation.cli.evaluate import freeze_task
from anonymisation.metrics.reference_inputs import counted_combinations
from anonymisation.metrics.research import event_calibration, population_metrics, task_utility
from anonymisation.schema.models import Document, TaskLabel


def test_utility_parity_official_f1_paired_difference_and_retention():
    rows = [{"doc_id": str(i), "gold": g, "original": g, "anonymized": a, "majority": "a"}
            for i, (g, a) in enumerate(zip("aabb", "aaaa", strict=True))]
    result = task_utility(rows, {"task": "routing", "labels": ["a", "b"]})
    expected = f1_score(list("aabb"), list("aaaa"), labels=["a", "b"], average="macro")
    assert result["utility_retention"]["value"] == pytest.approx(expected)
    assert result["task_f1_delta"]["value"] == pytest.approx(expected - 1)
    assert result["task_f1_delta"]["details"]["ci95"]["unit"] == "document"
    assert result["utility_retention"]["details"]["library"]["version"] == "1.8.0"


def test_noninformative_task_is_unavailable_not_perfect_retention():
    rows = [{"doc_id": str(i), "gold": g, "original": "a", "anonymized": "a", "majority": "a"}
            for i, g in enumerate("aabb")]
    result = task_utility(rows, {"task": "routing", "labels": ["a", "b"]})
    assert all(m["status"] == "unavailable" and m["value"] is None for m in result.values())


def _documents():
    return [Document(doc_id=str(i), dataset="test", split="train", domain="support", language="fr", text=text)
            for i, text in enumerate(["paiement facture carte", "facture montant paiement",
                                      "connexion compte motdepasse", "compte connexion accès"])]


def _task(doc_id, label):
    return TaskLabel(doc_id=doc_id, task="routing", label=label, label_type="single")


def test_official_frozen_evaluator_identity_and_blank_controls():
    train = _documents()
    evaluation = [Document(doc_id="a", dataset="test", split="test", domain="support", language="fr", text="carte facture paiement"),
                  Document(doc_id="b", dataset="test", split="test", domain="support", language="fr", text="accès compte connexion")]
    args = (train, [_task(str(i), "billing" if i < 2 else "login") for i in range(4)],
            evaluation, [_task("a", "billing"), _task("b", "login")])
    identity = freeze_task(*args, {d.doc_id: {"anonymized_text": d.text} for d in evaluation}, task="routing")
    assert all(r["original"] == r["anonymized"] == r["gold"] for r in identity["rows"])
    blank = freeze_task(*args, {d.doc_id: {"anonymized_text": ""} for d in evaluation}, task="routing")
    assert len({r["anonymized"] for r in blank["rows"]}) == 1
    assert identity["metadata"]["model_sha256"] == blank["metadata"]["model_sha256"]
    assert identity == freeze_task(*args, {d.doc_id: {"anonymized_text": d.text} for d in evaluation}, task="routing")


@pytest.mark.parametrize("leak", ["id", "text", "author", "subject", "thread"])
def test_downstream_train_test_leakage_rejected(leak):
    train = _documents()
    test = train[0].model_copy(update={"doc_id": "other", "text": "unique", "split": "test"})
    if leak == "id":
        test = test.model_copy(update={"doc_id": train[0].doc_id})
    elif leak == "text":
        test = test.model_copy(update={"text": train[0].text})
    elif leak == "author":
        train[0] = train[0].model_copy(update={"author_id": "same"})
        test = test.model_copy(update={"author_id": "same"})
    elif leak == "subject":
        train[0] = train[0].model_copy(update={"author_id": "same"})
        test = test.model_copy(update={"subject_ids": ("same",)})
    else:
        train[0] = train[0].model_copy(update={"thread_id": "same"})
        test = test.model_copy(update={"thread_id": "same"})
    with pytest.raises(ValueError, match="fuite train/test"):
        freeze_task(train, [], [test], [], {}, task="routing")


POPULATION = {"schema_version": "1", "kind": "synthetic_controlled", "population_id": "pop",
              "records": [{"subject_id": "p1", "attributes": {"GEN_AGE": {"exact": 30}}},
                          {"subject_id": "p2", "attributes": {"GEN_AGE": {"exact": 30}}},
                          {"subject_id": "p3", "attributes": {"GEN_AGE": {"exact": 60}}}]}
COMBO = {"combination_id": "c", "target_id": "p1", "population_id": "pop", "doc_ids": ["d"],
         "annotation_ids": ["ann"], "qi_set": [{"qi_category": "GEN_AGE", "normalized": {"exact": 30}}]}
GOLD = {"d": [{"annotation_id": "ann", "doc_id": "d", "start": 0, "end": 5, "qi_categories": ["GEN_AGE"]}]}


def test_qicr_population_count_and_strict_coverage_and_matched_k():
    counted = counted_combinations(POPULATION, [COMBO])
    assert counted[0]["k_true"] == 2
    prediction = {"annotations": [{"start": 0, "end": 1, "qi_categories": ["GEN_AGE"]}],
                  "risk": {"k_hat": 2, "combination_id": "c", "population_id": "pop"}}
    result = population_metrics(counted, GOLD, {"d": prediction}, {"population_id": "pop"}, split="test")
    assert result["qicr"]["value"] == 0
    assert result["male_k"]["value"] == 0
    prediction["annotations"][0]["end"] = 5
    result = population_metrics(counted, GOLD, {"d": prediction}, {"population_id": "pop"}, split="test")
    assert result["qicr"]["value"] == 1
    assert result["qicr"]["details"]["qicr_at_j"]["1"]["value"] == 1
    del prediction["risk"]["combination_id"]
    result = population_metrics(counted, GOLD, {"d": prediction}, {"population_id": "pop"}, split="test")
    assert result["male_k"]["value"] is None


@pytest.mark.parametrize("defect", ["count", "target", "missing", "null", "duplicate"])
def test_independent_population_truth_never_guessed(defect):
    pop, combo = copy.deepcopy(POPULATION), copy.deepcopy(COMBO)
    if defect == "count":
        combo["k_true"] = 50
    elif defect == "target":
        combo["target_id"] = "absent"
    elif defect == "missing":
        pop["records"][0]["attributes"] = {}
    elif defect == "null":
        pop["records"][1]["attributes"] = {"GEN_AGE": None}
    else:
        pop["records"].append(pop["records"][0])
    with pytest.raises(ValueError):
        counted_combinations(pop, [combo])


def test_combination_error_excluded_and_document_mismatch_rejected():
    counted = counted_combinations(POPULATION, [COMBO])
    result = population_metrics(counted, GOLD, {}, {"population_id": "pop"}, split="test")
    assert result["qicr"]["value"] is None
    assert result["qicr"]["details"]["excluded_document_errors"] == 1
    counted[0]["doc_ids"] = ["another"]
    with pytest.raises(ValueError, match="autre document"):
        population_metrics(counted, GOLD, {"another": {}}, {"population_id": "pop"}, split="test")


def _event_fixture():
    lock = {"protocol": "ratbench-staab-correctmatch", "protocol_version": "2", "attacker": {"model": "fixed"}, "publishable": True}
    contract = {k: lock[k] for k in ("protocol", "protocol_version", "attacker")}
    contract.update(event="ratbench_reidentified", text_stage="anonymized")
    probabilities, outcomes = [0.1, 0.9, 0.8, 0.4], [False, True, True, False]
    predictions = {str(i): {"risk": {"event_forecast": {"probability": p, "contract": contract}}}
                   for i, p in enumerate(probabilities)}
    attacks = [{"doc_id": str(i), "status": "ok", "reidentified": y} for i, y in enumerate(outcomes)]
    return predictions, (attacks, lock), probabilities, outcomes


def test_brier_and_reliability_curve_match_official_library():
    pred, attack, p, y = _event_fixture()
    result = event_calibration(pred, attack, split="test")
    assert result["brier"]["value"] == pytest.approx(brier_score_loss(y, p, pos_label=True, scale_by_half=True))
    assert result["brier"]["value"] == pytest.approx(0.055)
    observed, predicted = calibration_curve(y, p, n_bins=10, strategy="uniform")
    curve = result["ece"]["details"]["reliability"]
    assert curve["mean_probability"] == pytest.approx(predicted.tolist())
    assert curve["observed_frequency"] == pytest.approx(observed.tolist())
    assert set(result["ece"]["details"]["ece_by_bins"]) == {"5", "10", "15", "20"}


@pytest.mark.parametrize("defect", ["attacker", "probability", "target"])
def test_event_contract_and_binary_targets_are_strict(defect):
    pred, attack, _, _ = _event_fixture()
    if defect == "attacker":
        pred["0"]["risk"]["event_forecast"]["contract"] = {"attacker": "different"}
    elif defect == "probability":
        pred["0"]["risk"]["event_forecast"]["probability"] = 1.008
    else:
        attack[0][0]["reidentified"] = 0.5
    with pytest.raises(ValueError):
        event_calibration(pred, attack, split="test")


@pytest.mark.parametrize("defect", ["train", "partial", "failed"])
def test_calibration_requires_heldout_test_and_complete_forecasts(defect):
    pred, attack, _, _ = _event_fixture()
    split = "train" if defect == "train" else "test"
    if defect == "partial":
        del pred["0"]["risk"]["event_forecast"]
    if defect == "failed":
        attack[1]["publishable"] = False
    result = event_calibration(pred, attack, split=split)
    assert result["brier"]["value"] is None and result["ece"]["value"] is None


def test_equal_forecasts_stay_in_one_calibration_bin():
    pred, attack, _, _ = _event_fixture()
    for row in pred.values():
        row["risk"]["event_forecast"]["probability"] = 0.5
    result = event_calibration(pred, attack, split="test")
    assert result["ece"]["value"] == 0
    assert result["ece"]["details"]["reliability"]["counts"] == [4]


def test_risk_producer_can_freeze_explicit_evaluation_contracts():
    from anonymisation.pipeline.traces import RiskAssessment

    kwargs = dict(assessment_id="a", population_id="pop", population_size=100,
                  k_hat=2, risk=0.5, worst_category=None, worst_risk=None)
    original = RiskAssessment(**kwargs).to_dict()
    assert "combination_id" not in original and "event_forecast" not in original
    tagged = RiskAssessment(**kwargs, combination_id="c", event_forecast={"probability": 0.2}).to_dict()
    assert tagged["combination_id"] == "c"
    assert tagged["event_forecast"] == {"probability": 0.2}

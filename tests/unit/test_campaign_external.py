import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


external = _load("campaign_external")
campaign = _load("evaluation_campaign")
report = _load("campaign_report")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spec(tmp_path, ids=("a", "b"), excluded=("z",)):
    sel, pivot, dev = tmp_path / "ids.json", tmp_path / "pivot.json", tmp_path / "dev.json"
    sel.write_text(json.dumps(list(ids)))
    pivot.write_text(json.dumps({"datasets": {"quasileak": {"test": [{"doc_id": i, "text_sha256": "x"} for i in ids]}}}))
    dev.write_text(json.dumps(list(excluded)))
    return {"split": "test", "selection": str(sel), "selection_sha256": _sha(sel), "pivot_selection": str(pivot),
            "pivot_selection_sha256": _sha(pivot), "protocol": "quasileak-v1", "excluded_selections": [str(dev)],
            "llm_grouping": True, "native_detector": True, "disclosure_policy": "document"}


def test_committed_campaign_includes_quasileak_outside_the_frozen_cohort():
    cfg = json.loads((ROOT / "configs/evaluation/campaign.json").read_text())
    assert "quasileak" not in cfg["datasets"]
    assert set(external.validate_external(cfg)) == {"quasileak"}
    assert json.loads((ROOT / "configs/evaluation/active_suite.json").read_text())["suite"] == "campaign"


def test_validation_refuses_drift_size_overlap_and_implicit_defaults(tmp_path):
    cfg = {"datasets": {}, "evaluation_subset": {"documents_per_dataset": 2},
           "external_datasets": {"quasileak": _spec(tmp_path)}}
    assert external.validate_external(cfg)
    cfg["evaluation_subset"]["documents_per_dataset"] = 3
    with pytest.raises(ValueError, match="par dataset"):
        external.validate_external(cfg)
    cfg["evaluation_subset"]["documents_per_dataset"] = 2
    cfg["external_datasets"]["quasileak"] = _spec(tmp_path, excluded=("a",))
    with pytest.raises(ValueError, match="développement"):
        external.validate_external(cfg)
    spec = _spec(tmp_path)
    Path(spec["selection"]).write_text(json.dumps(["a", "c"]))
    cfg["external_datasets"]["quasileak"] = spec
    with pytest.raises(ValueError, match="modifié"):
        external.validate_external(cfg)
    spec = _spec(tmp_path)
    del spec["native_detector"]
    cfg["external_datasets"]["quasileak"] = spec
    with pytest.raises(ValueError, match="aucun défaut"):
        external.validate_external(cfg)
    cfg["external_datasets"] = {"tab": _spec(tmp_path)}
    with pytest.raises(ValueError, match="non pris en charge"):
        external.validate_external(cfg)


def test_predict_args_use_the_dataset_own_selection_and_policy(tmp_path):
    spec = _spec(tmp_path)
    cfg = {"external_datasets": {"quasileak": spec},
           "evaluation_subset": {"manifest": "cohort.json"}, "_evaluation_subset_limits": {},
           "anonymizer_backend": "qwen_local_box"}
    variant = {"system": "llm-windowed", "policy": None, "params": {}, "disclosure_policy": None}
    args = campaign.predict_args(cfg, "quasileak", "test", variant, tmp_path / "run")
    assert args[args.index("--selection-manifest") + 1] == spec["pivot_selection"]
    assert args[args.index("--limit") + 1] == "2"
    assert args[args.index("--disclosure-policy") + 1] == "document"


def test_consolidated_scores_keep_profile_references_apart(tmp_path):
    summary = {"results": [{"dataset": "quasileak", "split": "test", "system": "llm-windowed",
                            "gold_aware": False, "status": "sampled", "publishable": True,
                            "primary": {}, "diagnostic": {"quasileak_pgf1_d8": {"value": 0.02}},
                            "reference_d8_llm_grouping": {"official": {"scores_0_100": {"P-GF1": 7.5}}}}],
               "reference_results": [{"dataset": "quasileak", "reference": "native-detector-zero-shot",
                                      "official": {"scores_0_100": {"P-GF1": 11.9}}}]}
    rows = report.consolidated_scores(summary)
    assert rows[0]["metrics"] == {"diagnostic.quasileak_pgf1_d8": 0.02}
    assert rows[0]["reference_d8_llm_grouping_pgf1"] == 7.5
    summary["scores"] = rows
    out = tmp_path / "scores.md"
    report.write_scores_markdown(summary, out)
    text = out.read_text()
    assert "reçoit le profil, hors comparaison" in text and "| llm-windowed | 0.02 | True |" in text


def test_parity_detects_any_divergence_with_the_isolated_official_scorer(tmp_path):
    row = {"sample_id": "test-1", "document": "clinical rotation and four-year tuition",
           "profile": {"profile_id": "p1"}, "policy": {"hide": ["education"], "keep": [], "neutral": []},
           "gold": {"groups": [{"group_id": "g1", "attribute": "education", "cue_ids": ["s1", "s2"],
                                "secondary_attributes": []}],
                    "spans": [{"span_id": "s1", "start": 0, "end": 17}, {"span_id": "s2", "start": 22, "end": 39}],
                    "distractors": []}}
    source = tmp_path / "source"
    source.mkdir()
    (source / "quasileak_bench_data_full.jsonl").write_text(json.dumps(row) + "\n")
    run = tmp_path / "run"
    run.mkdir()
    (run / "quasileak_d8_selection.json").write_text(json.dumps(["test-1"]))
    (run / "quasileak_d8_groups.jsonl").write_text(json.dumps({"sample_id": "test-1", "evidence": [
        {"attribute": "education", "spans": [{"start": 0, "end": 17}, {"start": 22, "end": 39}]}]}) + "\n")

    def card(scores):
        (run / "scorecard.json").write_text(json.dumps({"diagnostic": {"quasileak_pgf1_d8": {
            "details": {"official": {"scores_0_100": scores}}}}}))

    official = json.loads(subprocess.run(
        [sys.executable, "-I", str(external.VENDOR_SCORER), "--predictions", str(run / "quasileak_d8_groups.jsonl"),
         "--dataset", str(source / "quasileak_bench_data_full.jsonl")], capture_output=True, text=True,
        check=True).stdout)
    assert official["P-GF1"] == 100
    card(official)
    assert external.parity([run], source, tmp_path / "parity")["ok"] is True
    card({**official, "P-GF1": 99.0})
    assert external.parity([run], source, tmp_path / "parity")["ok"] is False

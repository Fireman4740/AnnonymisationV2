"""Les échantillons gardent le gold complet et les profils liés."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts/evaluation_campaign.py"
_SPEC = importlib.util.spec_from_file_location("evaluation_campaign", _PATH)
assert _SPEC and _SPEC.loader
campaign = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(campaign)


def test_auxiliary_train_excludes_test_texts_people_threads_without_using_labels():
    def doc(key, **changes):
        return SimpleNamespace(**{"doc_id": key, "text": key, "author_id": None,
                                  "subject_ids": (), "thread_id": None, **changes})

    held_out = [doc("test", author_id="person", thread_id="thread")]
    candidates = [doc("test"), doc("same-text", text="test"),
                  doc("same-author", author_id="person"),
                  doc("same-subject", subject_ids=("person",)),
                  doc("same-thread", thread_id="thread"), doc("independent")]
    excluded = {}
    selected = list(campaign.disjoint_training_documents(candidates, held_out, excluded))
    assert [d.doc_id for d in selected] == ["independent"]
    assert excluded == {"overlap": 5}


def test_population_evaluation_sample_keeps_only_complete_combinations():
    source = SimpleNamespace(key="mini", manifest=None, raw_dir=Path("."),
        iter_combinations=lambda split: iter([
            SimpleNamespace(combination_id="complete", doc_ids=("a", "b")),
            SimpleNamespace(combination_id="partial", doc_ids=("a", "outside")),
        ]))
    selected = [SimpleNamespace(doc_id=key, subject_ids=(), author_id=None) for key in ("a", "b")]
    sample = campaign.CompleteSample(source, {"test": selected})
    assert [c.combination_id for c in sample.iter_combinations("test")] == ["complete"]


def test_sample_keeps_all_annotations_tasks_and_late_linked_profiles():
    selected = SimpleNamespace(doc_id="chosen", subject_ids=("subject",), author_id=None)
    source = SimpleNamespace(
        key="spia", manifest=None, raw_dir=Path("."),
        iter_annotations=lambda split: iter([
            SimpleNamespace(doc_id="other"),
            *[SimpleNamespace(doc_id="chosen", index=i) for i in range(9)],
        ]),
        iter_profiles=lambda split: iter([
            SimpleNamespace(person_id="other"), SimpleNamespace(person_id="subject"),
        ]),
        iter_tasks=lambda split: iter([
            SimpleNamespace(doc_id="other"), SimpleNamespace(doc_id="chosen"),
        ]),
    )
    sample = campaign.CompleteSample(source, {"test": [selected]})
    assert len(list(sample.iter_annotations("test"))) == 9
    assert [p.person_id for p in sample.iter_profiles("test")] == ["subject"]
    assert [t.doc_id for t in sample.iter_tasks("test")] == ["chosen"]


def _docs(field, groups):
    return [
        SimpleNamespace(doc_id=f"{group}-{i}", text="text", meta={field: group})
        for group in groups for i in range(100)
    ]


@pytest.mark.parametrize(("key", "field", "groups", "counts"), [
    ("ratbench", "difficulty", (1, 2, 3), (7, 7, 6)),
    ("spia", "source_corpus", ("tab", "panorama"), (10, 10)),
])
def test_twenty_exact_hash_bottom_k_order_independent(key, field, groups, counts):
    docs = _docs(field, groups)
    selected, report = campaign.choose(iter(docs), key, "test", 20, 8000, 42)
    other, other_report = campaign.choose(reversed(docs), key, "test", 20, 8000, 42)
    assert [d.doc_id for d in selected] == [d.doc_id for d in other]
    assert report == other_report
    assert len(selected) == len({d.doc_id for d in selected}) == 20
    for group, count in zip(groups, counts, strict=True):
        expected = sorted(
            (d for d in docs if d.meta[field] == group),
            key=lambda d: hashlib.sha256(f"42\0{key}\0test\0{d.doc_id}".encode()).digest(),
        )[:count]
        assert [d.doc_id for d in selected if d.meta[field] == group] == [
            d.doc_id for d in expected
        ]


@pytest.mark.parametrize("count", [1, 2])
def test_ratbench_small_sample_zero_quotas(count):
    selected, report = campaign.choose(_docs("difficulty", (1, 2, 3)), "ratbench", "test", count, 8000, 42)
    assert len(selected) == report["selected"] == count
    assert report["strata"]["3"] == {"requested": 0, "available": 100, "selected": 0}


def test_ratbench_sample_rejects_missing_requested_stratum():
    with pytest.raises(ValueError, match="échantillon incomplet"):
        campaign.choose(_docs("difficulty", (1, 2)), "ratbench", "test", 3, 8000, 42)


def test_dataset_budget_redistributes_a_short_split_without_duplicates():
    available = {"anonymization": 31, "hard_quasi_id": 40, "max_anonymization": 1}
    assert campaign.split_budget(available, 20) == {
        "anonymization": 10, "hard_quasi_id": 9, "max_anonymization": 1,
    }
    with pytest.raises(ValueError, match="incomplet"):
        campaign.split_budget({"small": 1}, 20)


def test_dataset_budget_can_leave_a_split_empty_explicitly():
    assert campaign.split_budget({"empty": 0, "full": 20}, 20) == {"empty": 0, "full": 20}


def test_capped_sample_uses_all_small_corpora_without_duplication():
    docs = _docs("difficulty", (1, 2, 3))
    selected, report = campaign.choose(docs, "ratbench", "eval", 500, 8000, 42, capped=True)
    assert len(selected) == len({d.doc_id for d in selected}) == 300
    assert report["requested"] == 500
    assert all(s["selected"] == 100 for s in report["strata"].values())


def test_capped_spia_redistributes_short_stratum_stably():
    docs = [SimpleNamespace(doc_id=f"{g}-{i}", text="text", meta={"source_corpus": g})
            for g, n in (("tab", 142), ("panorama", 531)) for i in range(n)]
    selected, report = campaign.choose(docs, "spia", "test", 500, 8000, 42, capped=True)
    other, other_report = campaign.choose(reversed(docs), "spia", "test", 500, 8000, 42, capped=True)
    assert len(selected) == 500
    assert report["strata"]["tab"]["selected"] == 142
    assert report["strata"]["panorama"]["selected"] == 358
    assert [d.doc_id for d in selected] == [d.doc_id for d in other]
    assert report == other_report


def test_capped_sample_rejects_duplicate_identifiers():
    docs = [SimpleNamespace(doc_id="same", text="text", meta={})] * 2
    with pytest.raises(ValueError, match="dupliqué"):
        campaign.choose(docs, "mini", "test", 500, 8000, 42, capped=True)


@pytest.mark.parametrize(("stages", "replay_identical", "expected"), [
    # Score 1 = publication bloquée (C4, arbre modifié) : un résultat, pas une panne.
    ({"predict": 0, "score": 1, "replay": 1}, True, []),
    ({"predict": 0, "score": 0, "replay": 0}, True, []),
    ({"predict": 1, "score": 0, "replay": 0}, True, ["predict"]),
    ({"predict": 0, "attack": 1, "score": 0, "replay": 0}, True, ["attack"]),
    # Score 2 = erreur d'usage : aucune scorecard de ce run n'existe.
    ({"predict": 0, "score": 2, "replay": 2}, True, ["score", "replay"]),
    ({"predict": 0, "score": 0, "replay": 1}, True, ["replay"]),
    ({"predict": 0, "score": 0, "replay": 0}, False, ["replay"]),
])
def test_stage_failures_check_score_and_replay_exit_codes(stages, replay_identical, expected):
    assert campaign.stage_failures(stages, replay_identical) == expected


def _campaign_cfg():
    import json

    return json.loads((Path(__file__).resolve().parents[2] / "configs/evaluation/campaign.json").read_text())


def _full_policy_cfg():
    cfg = _campaign_cfg()
    cfg["systems"] = [
        {"system": "passthrough", "spia_attack": True},
        {"system": "redact-all", "params": {"replacement": ""}, "spia_attack": True},
        {"system": "oracle-mask", "spia_attack": True},
        {"system": "regex-only", "spia_attack": True},
        *[{"system": name, "policies": [f"P{i}" for i in range(5)], "spia_attack_policies": ["P2"]}
          for name in ("deterministic", "hybrid-qi")],
        {"system": "llm-full", "remote_only": True, "spia_attack": True},
    ]
    return cfg


def _openrouter_cfg():
    cfg = _campaign_cfg()
    cfg["anonymizer_backend"] = "openrouter_ling_3_0_flash"
    cfg["attacker_backend"] = "openrouter_ling_3_0_flash"
    return cfg


def test_campaign_uses_only_requested_systems_and_caps_evaluation_at_500():
    cfg = _campaign_cfg()
    assert cfg["documents_per_dataset"] == 500 and cfg["cap_documents"] is True
    assert {v["name"] for v in campaign.system_variants(cfg, remote_allowed=True)} == {
        "oracle-mask", "regex-only", "llm-windowed"}


def test_local_backend_requires_no_openrouter_price_cap():
    from anonymisation.llm.config import load_backends_config

    models = campaign.campaign_models(_campaign_cfg(), load_backends_config())
    assert all(m["model"] == "qwen3.8-27b" and m["remote"] is False
               for m in models.values())
    assert campaign.validate_provider_routes(_campaign_cfg(), models) == []


def test_ling_3_0_accepts_only_declared_price_openrouter_routes():
    from dataclasses import replace

    from anonymisation.llm.config import load_backends_config

    cfg = _openrouter_cfg()
    llm_cfg = load_backends_config()
    models = campaign.campaign_models(cfg, llm_cfg)
    assert all(m["model"] == "inclusionai/ling-3.0-flash" for m in models.values())
    assert all(m["remote"] is True for m in models.values())
    backend = llm_cfg.resolve(name=cfg["anonymizer_backend"])
    for changes in (
        {"extra_body": {}},
        {"extra_body": {"provider": {"max_price": {"prompt": 0, "completion": 0.1}}}},
        {"base_url": "https://another-provider.example/v1", "extra_body": {}},
    ):
        invalid = replace(llm_cfg, backends={**llm_cfg.backends, backend.name: replace(backend, **changes)})
        with pytest.raises(ValueError, match="plafond tarifaire"):
            campaign.campaign_models(cfg, invalid)


def test_route_preflight_respects_price_units_and_current_cap(monkeypatch):
    import io
    import json

    models = {"anonymizer_backend": {"model": "inclusionai/ling-3.1-flash", "remote": True}}
    requests = []

    def urlopen(url, **kwargs):
        requests.append(url)
        return io.BytesIO(json.dumps({"data": {"endpoints": [{
            "provider_name": "Novita", "pricing": {
                "prompt": "0.000000075", "completion": "0.000000225"},
        }]}}).encode())

    monkeypatch.setattr(campaign.urllib.request, "urlopen", urlopen)
    with pytest.raises(ValueError, match="Aucune route"):
        campaign.validate_provider_routes({}, models)
    caps = {"prompt": 0.075, "completion": 0.225}
    report = campaign.validate_provider_routes({"provider_max_price": caps}, models)
    assert report[0]["allowed_routes"][0]["prices_per_million"] == {
        "prompt": "0.075000000", "completion": "0.225000000"}
    assert requests[-1].endswith("/inclusionai/ling-3.1-flash/endpoints")
    with pytest.raises(ValueError, match="Aucune route"):
        campaign.validate_provider_routes({"provider_max_price": {**caps, "completion": 0.2}}, models)


@pytest.mark.parametrize("caps", [None, {}, {"prompt": 0},
                                   {"prompt": -1, "completion": 0},
                                   {"prompt": "NaN", "completion": 0},
                                   {"prompt": True, "completion": 0}])
def test_invalid_price_caps_are_rejected(caps):
    with pytest.raises(ValueError, match="provider_max_price"):
        campaign.provider_price_caps({"provider_max_price": caps})


def test_nonzero_price_cap_must_be_explicit_and_identical_in_every_backend():
    from dataclasses import replace

    from anonymisation.llm.config import load_backends_config

    cfg = _openrouter_cfg()
    llm_cfg = load_backends_config()
    backend = llm_cfg.resolve(name=cfg["anonymizer_backend"])
    caps = {"prompt": 0.075, "completion": 0.225}
    paid = replace(backend, extra_body={**backend.extra_body, "provider": {"max_price": caps}})
    llm_cfg = replace(llm_cfg, backends={**llm_cfg.backends, backend.name: paid})
    with pytest.raises(ValueError, match="plafond tarifaire"):
        campaign.campaign_models(cfg, llm_cfg)
    cfg = {**cfg, "provider_max_price": caps}
    assert campaign.campaign_models(cfg, llm_cfg)["anonymizer_backend"]["extra_body"]["provider"]["max_price"] == caps


def test_variants_run_every_policy_but_spia_attacks_only_reference_runs():
    variants = {v["name"]: v for v in campaign.system_variants(_full_policy_cfg(), remote_allowed=True)}
    assert {f"deterministic-P{i}" for i in range(5)} <= set(variants)
    assert {f"hybrid-qi-P{i}" for i in range(5)} <= set(variants)
    assert {"passthrough", "redact-all", "oracle-mask", "regex-only", "llm-full"} <= set(variants)
    judged = sorted(name for name, v in variants.items() if v["spia_attack"])
    assert judged == ["deterministic-P2", "hybrid-qi-P2", "llm-full", "oracle-mask",
                      "passthrough", "redact-all", "regex-only"]


def test_real_corpus_without_authorization_never_runs_llm_full():
    names = {v["name"] for v in campaign.system_variants(_full_policy_cfg(), remote_allowed=False)}
    assert "llm-full" not in names and "deterministic-P0" in names


def test_predict_args_carry_policy_and_explicit_parameters(tmp_path):
    cfg = _full_policy_cfg()
    variants = {v["name"]: v for v in campaign.system_variants(cfg, remote_allowed=True)}
    args = campaign.predict_args(cfg, "ratbench", "eval", variants["hybrid-qi-P3"], tmp_path)
    assert args[args.index("--policy") + 1] == "P3"
    assert args[args.index("--profile") + 1] == "hybrid_qi"
    redact = campaign.predict_args(cfg, "ratbench", "eval", variants["redact-all"], tmp_path)
    assert "replacement=" in redact
    llm = campaign.predict_args(cfg, "ratbench", "eval", variants["llm-full"], tmp_path)
    assert f"backend={cfg['anonymizer_backend']}" in llm


def test_remote_authorization_is_per_dataset_and_explicit():
    cfg = {"remote_real_corpora_authorized": False, "remote_authorized_datasets": ["spia"]}
    assert campaign.remote_authorized(cfg, "spia", synthetic=False)
    assert not campaign.remote_authorized(cfg, "tab", synthetic=False)
    assert campaign.remote_authorized(cfg, "ratbench", synthetic=True)
    with pytest.raises(KeyError):
        campaign.remote_authorized({"remote_real_corpora_authorized": False}, "spia", False)

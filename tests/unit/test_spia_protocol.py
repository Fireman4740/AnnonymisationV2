"""Protocole SPIA original : chargement vérifié, flux d'attaque, CPR/IPR (EPIC-H H-2).

Aucun réseau : le transport du code original est remplacé par des réponses
écrites à la main, lues par les VRAIS parseurs de SPIA.
"""

from __future__ import annotations

import json

import pytest

from anonymisation.attack.spia.runner import _Transport, attack_document
from anonymisation.attack.spia.vendored import VendoredSpiaError, original_spia, verify
from anonymisation.llm.client import LlmCompletion, LlmEmptyResponseError
from anonymisation.metrics.spia_protection import spia_protection

LOCK = {"protocol": "spia-original", "protocol_version": "1", "config": {"min_certainty": 3}}

ORIGINAL = "Alice Martin, 34, a nurse from Lyon, met Bob."
ANONYMIZED = "[NAME], 30s, a health worker from [CITY], met [NAME]."
GOLD = {
    "_data_id": "d1", "_origin": "panorama", "text": ORIGINAL,
    "subjects": [{"id": 0, "description": "Alice", "PIIs": [
        {"tag": "NAME", "keyword": "Alice Martin", "certainty": 5, "hardness": 1},
        {"tag": "AGE", "keyword": "34", "certainty": 5, "hardness": 1},
        {"tag": "OCCUPATION", "keyword": "nurse", "certainty": 4, "hardness": 1},
        {"tag": "LOCATION", "keyword": "Lyon, France", "certainty": 2, "hardness": 1},
    ]}],
}


def _evaluation(*subjects):
    return {"data_id": "d", "number_of_subjects": len(subjects), "subjects": [
        {"subject_id": i, "matched": True, "description": "", "evaluations": {
            tag: {"certainty_A": certainty, "agreement_score": score}
            for tag, (certainty, score) in evaluations.items()}}
        for i, evaluations in enumerate(subjects)]}


def test_vendored_copy_is_verified_and_alteration_is_refused(tmp_path, monkeypatch):
    manifest = verify()
    assert manifest["commit"].startswith("3fa78a1")
    from anonymisation.attack.spia import vendored

    original = vendored.ROOT
    copy = tmp_path / "original"
    import shutil

    shutil.copytree(original, copy)
    (copy / "src/evaluate/privacy/calculate_ipr_cpr.py").write_text("# altéré\n")
    monkeypatch.setattr(vendored, "ROOT", copy)
    with pytest.raises(VendoredSpiaError, match="altéré"):
        verify()


def test_cpr_ipr_match_the_original_fractional_formula():
    rows = [
        {"doc_id": "a", "status": "ok", "evaluation": _evaluation(
            {"NAME": (5, 1.0), "AGE": (4, 0.5), "LOCATION": (2, 1.0)},  # certitude 2 exclue
            {"NAME": (5, 0.0)})},
        {"doc_id": "b", "status": "ok", "evaluation": _evaluation({"SEX": (3, 0.5), "AGE": (5, 0.0)})},
    ]
    cpr, ipr = spia_protection(rows, LOCK)
    # S = 1.5, 0, 0.5 ; A = 2, 1, 2 → CPR = 1 - 2/5 ; IPR = mean(0.25, 1, 0.75)
    assert cpr["value"] == pytest.approx(1 - 2 / 5)
    assert ipr["value"] == pytest.approx((0.25 + 1.0 + 0.75) / 3)
    assert cpr["details"]["total_pii"] == 5
    with original_spia({"ppr": "src.evaluate.privacy.calculate_ipr_cpr"}) as original:
        reference = original.ppr.calculate_ipr_cpr(
            {"detailed_results": [r["evaluation"] for r in rows]}, 3)
    assert (cpr["value"], ipr["value"]) == (reference.cpr, reference.ipr)


def test_attack_errors_above_threshold_make_both_unavailable():
    rows = [{"doc_id": "a", "status": "ok", "evaluation": _evaluation({"NAME": (5, 1.0)})},
            {"doc_id": "b", "status": "error"}]
    cpr, ipr = spia_protection(rows, LOCK)
    assert cpr["value"] is None and ipr["value"] is None
    assert "C4" in cpr["details"]["reason"]


def test_no_subject_above_certainty_is_unavailable_not_zero():
    rows = [{"doc_id": "a", "status": "ok", "evaluation": _evaluation({"NAME": (1, 1.0)})}]
    cpr, ipr = spia_protection(rows, LOCK)
    assert cpr["value"] is None and "0,0" in cpr["details"]["reason"]


SA = ("Individual Character Analysis:\n- Person 0: a health worker in their 30s\n"
      "The Number of Subjects: 1")
SPC = json.dumps([{"id": 0, "description": "health worker", "PIIs": []}])
SPNC = json.dumps([{"id": 0, "description": "health worker", "PIIs": [
    {"tag": "AGE", "keyword": "30-39", "certainty": 3, "hardness": 2},
    {"tag": "OCCUPATION", "keyword": "nurse", "certainty": 3, "hardness": 2}]}])
ALIGN = "---\nReasoning: same person\nResult: Matched\nSubject: A_0; B_0\n---"


class _Client:
    """Client factice : routage par gabarit de prompt original."""

    def __init__(self, align: str = ALIGN, agreement: str = "less precise", fail: str | None = None,
                 spnc: str = SPNC):
        self.align, self.agreement, self.fail, self.spnc = align, agreement, fail, spnc
        self.backend = type("B", (), {"name": "fake", "model": "fake", "max_concurrency": 1})()

    def complete(self, prompt, **_):
        if self.fail and self.fail in prompt:
            raise LlmEmptyResponseError("vide")
        if prompt.startswith("The following response has a JSON formatting error"):
            # `fix_json_with_llm` officiel : renvoyer le JSON d'origine intact.
            content = prompt.split("Original Response:\n", 1)[1].split("\n\nError:", 1)[0]
        elif prompt.startswith("Your task is to identify and count"):
            content = SA
        elif "- IDENTIFICATION_NUMBER:" in prompt:
            content = SPC
        elif "- NAME: Names that directly" in prompt:
            content = self.spnc
        elif "match and align subject IDs" in prompt:
            content = self.align
        else:
            content = self.agreement
        return LlmCompletion(content, "fake", "fake", False, "stop", 0.0)


def _run(client):
    transport = _Transport(client, sleep=lambda _: None)
    with original_spia() as original:
        original.client.install_transport(transport)
        try:
            return attack_document(original, transport, GOLD, ANONYMIZED)
        finally:
            original.client.install_transport(None)


def test_rule_miss_is_settled_by_the_model_with_half_credit():
    spnc = SPNC.replace('"nurse"', '"health worker"')
    row = _run(_Client(agreement="less precise", spnc=spnc))
    evaluation = row["evaluation"]["subjects"][0]["evaluations"]["OCCUPATION"]
    assert evaluation["agreement_score"] == 0.5
    assert evaluation["evaluation_method"] == "MODEL"


def test_attack_runs_the_original_stages_on_the_anonymized_text():
    row = _run(_Client())
    assert row["status"] == "ok", row.get("error")
    assert row["matched_pairs"] == [["0", "0"]] or row["matched_pairs"] == [[0, 0]]
    evaluations = row["evaluation"]["subjects"][0]["evaluations"]
    assert evaluations["NAME"]["agreement_score"] == 0.0      # non inféré
    assert evaluations["OCCUPATION"]["agreement_score"] == 1.0  # règle exacte
    assert evaluations["AGE"]["certainty_A"] == 5
    assert row["alignment_fallback"] is None


def test_unaligned_document_falls_back_to_gold_only_subjects_like_the_original():
    row = _run(_Client(align="---\nReasoning: nobody\nResult: Unmatched\nSubject: A_0\n---"))
    assert row["status"] == "ok"
    assert row["alignment_fallback"] == "gt_only_subject"
    assert len(row["alignment_attempts"]) == 3
    subject = row["evaluation"]["subjects"][0]
    assert subject["matched"] is False
    assert all(e["agreement_score"] == 0.0 for e in subject["evaluations"].values())


def test_llm_failure_swallowed_by_the_original_becomes_a_document_error():
    """L'original note 0 quand le juge plante : ici, erreur du document (C3)."""
    # « health worker » ≠ « nurse » pour les règles : l'original consulte le modèle.
    spnc = SPNC.replace('"nurse"', '"health worker"')
    row = _run(_Client(fail="Below I give you two PII annotation values", spnc=spnc))
    assert row["status"] == "error"
    assert row["error"].startswith("llm:")

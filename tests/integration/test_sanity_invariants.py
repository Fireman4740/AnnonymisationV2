"""Tests de sanité S1–S6 de SPEC-07 §11 sur cas contrôlés (EPIC-H H-9).

Sur corpus réels, ces tendances sont des observations à examiner ; ici, sur
des cas construits, leur violation est un bug.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import load_micro  # noqa: E402
from test_predict import _lock, micro_pivot  # noqa: E402,F401

from anonymisation.cli.main import main  # noqa: E402
from anonymisation.metrics.downstream import evaluate_downstream_task  # noqa: E402
from anonymisation.metrics.entities import entity_recall  # noqa: E402
from anonymisation.metrics.leakage import aggregate_leak_counts, gold_leak_counts  # noqa: E402
from anonymisation.metrics.masking import document_coverage  # noqa: E402
from anonymisation.metrics.ner_schemas import corpus_counts  # noqa: E402
from anonymisation.metrics.utility import rouge_l  # noqa: E402
from anonymisation.schema.models import Document, Domain, LabelType, TaskLabel  # noqa: E402
from anonymisation.schema.taxonomy import IdentifierType  # noqa: E402

TRAIN = ["connexion mot de passe Alice", "identifiant refusé Bob", "paiement facture Carole",
         "facture remboursement David"]
TEST = ["connexion refusée Emma", "mot de passe Farid", "paiement en attente Gina",
        "remboursement facture Hugo"]
LABELS = ["auth", "auth", "billing", "billing"]


def _docs(texts, split):
    return [Document(doc_id=f"{split}{i}", dataset="ds", split=split, domain=Domain.GENERIC,
                     language="fr", text=t) for i, t in enumerate(texts)]


def _tasks(split):
    return [TaskLabel(doc_id=f"{split}{i}", task="cat", label=label, label_type=LabelType.SINGLE)
            for i, label in enumerate(LABELS)]


def _retention(anonymized):
    return evaluate_downstream_task(
        task_name="cat", train_docs=_docs(TRAIN, "t"), train_tasks=_tasks("t"),
        eval_docs_orig=_docs(TEST, "e"), eval_docs_anon=anonymized, eval_tasks=_tasks("e"),
    ).utility_retention


def test_s1_untouched_text_leaks_everything_and_keeps_all_utility():
    micro = load_micro()
    leaks = aggregate_leak_counts([
        gold_leak_counts(d.text, [a for a in micro["annotations"] if a.doc_id == d.doc_id])
        for d in micro["documents"]])
    assert leaks.rate == 1.0
    assert _retention(TEST) == 1.0


def test_s2_fully_removed_text_leaks_nothing_and_loses_utility():
    micro = load_micro()
    leaks = aggregate_leak_counts([
        gold_leak_counts("", [a for a in micro["annotations"] if a.doc_id == d.doc_id])
        for d in micro["documents"]])
    assert leaks.rate == 0.0
    retention = _retention([""] * len(TEST))
    assert retention is None or retention < 1.0


@pytest.mark.parametrize("system", ["deterministic", "hybrid-qi"])
def test_s3_stricter_policy_masks_more_and_keeps_less_text(micro_pivot: Path, tmp_path, system):  # noqa: F811
    micro = load_micro()
    docs = {d.doc_id: d for d in micro["documents"]}
    gold: dict[str, list] = {}
    for annotation in micro["annotations"]:
        gold.setdefault(annotation.doc_id, []).append(annotation.model_dump(mode="json"))
    masked, rouge = [], []
    for policy in ("P0", "P1", "P2", "P3", "P4"):
        out = tmp_path / f"{system}-{policy}"
        profile = "hybrid_qi" if system == "hybrid-qi" else "deterministic"
        assert main(["predict", "--dataset", "micro", "--split", "train", "--system", system,
                     "--policy", policy, "--profile", profile, "--out", str(out)]) == 0
        rows = [json.loads(line) for line in (out / "predictions.jsonl").read_text().splitlines()]
        masked.append(sum(document_coverage(gold.get(r["doc_id"], []), r["decisions"],
                                            docs[r["doc_id"]].text).covered_chars for r in rows))
        rouge.append(sum(rouge_l(docs[r["doc_id"]].text, r["anonymized_text"]) for r in rows))
    assert masked == sorted(masked) and masked[0] < masked[-1], masked
    assert rouge == sorted(rouge, reverse=True) and rouge[0] > rouge[-1], rouge


def test_s4_non_standard_expression_is_harder_to_detect():
    explicit = {"start": 0, "end": 4, "qi_categories": ["DIR_NAME"], "identifier_type": "DIRECT"}
    obfuscated = {"start": 10, "end": 17, "qi_categories": ["DIR_NAME"], "identifier_type": "DIRECT"}
    # Un détecteur littéral trouve la forme explicite, pas « A.l.i.c.e ».
    explicit_counts, _, _ = corpus_counts([([explicit], [explicit])])
    obfuscated_counts, _, _ = corpus_counts([([obfuscated], [])])
    assert (obfuscated_counts["partial"].scores("partial")["recall"]
            < explicit_counts["partial"].scores("partial")["recall"])


def test_s5_author_scope_gap_is_declared_not_silently_dropped(micro_pivot: Path, tmp_path):  # noqa: F811
    """P3/P4 demandent la portée auteur, non implémentée : le lock doit le dire."""
    out = tmp_path / "p4"
    assert main(["predict", "--dataset", "micro", "--split", "train", "--system", "deterministic",
                 "--policy", "P4", "--profile", "deterministic", "--out", str(out)]) == 0
    policy = _lock(out)["policy"]
    assert policy["scope_requested"] == "author"
    assert policy["scope_applied"] == "document"
    assert "S5 non vérifiable" in policy["scope_gap"]


def test_s6_entity_recall_differs_from_span_recall_on_repeated_mentions():
    mentions = [{"start": i * 10, "end": i * 10 + 4, "qi_categories": ["DIR_NAME"],
                 "identifier_type": "DIRECT", "entity_id": "p", "span_text": "xxxx"}
                for i in range(2)]
    counts, _, _ = corpus_counts([(mentions, mentions[:1])])
    span_recall = counts["strict"].scores("strict")["recall"]
    assert span_recall == 0.5
    assert entity_recall(mentions, mentions[:1], identifier_type=IdentifierType.DIRECT) == 0.0

"""Scorecard et invariants d'agrégation (ticket D-4, SPEC-07 §10).

Ces tests portent sur ``build_scorecard`` seul : aucun fichier, aucun run, et
donc aucune dépendance au pivot ingéré. Les cas couverts sont ceux où une
agrégation naïve donnerait un chiffre flatteur mais faux.
"""

from __future__ import annotations

import json

import pytest

from anonymisation.metrics.contracts import MetricStatus
from anonymisation.metrics.scorecard import ScorecardError, build_scorecard, validate_scorecard
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Stability,
)

LOCK = {
    "run": {
        "dataset": "mini",
        "split": "train",
        "profile": "deterministic",
        "policy": "P2",
        "status": "complete",
    },
    "data_version": {"source": "fixture"},
    "taxonomy_version": "1.0",
    "code": {"git_commit": "fixture-commit", "git_dirty": False},
    "models": [],
    "seeds": {"determinism": 42},
    "prompts": [],
    "policy": {"id": "P2", "source": "policies.yaml", "sha256": "a" * 64},
}


def _document(doc_id: str, text: str) -> Document:
    return Document(
        doc_id=doc_id,
        dataset="mini",
        split="train",
        domain="hr",
        language="fr",
        text=text,
    )


def _annotation(
    doc_id: str,
    start: int,
    end: int,
    *,
    span_text: str,
    expression_mode: ExpressionMode = ExpressionMode.EXPLICIT,
    identifier_type: IdentifierType = IdentifierType.DIRECT,
    category: str = "DIR_NAME",
) -> Annotation:
    return Annotation(
        annotation_id=f"{doc_id}-{start}-{end}",
        doc_id=doc_id,
        start=start,
        end=end,
        span_text=span_text,
        identifier_type=identifier_type,
        qi_categories=(category,),
        expression_mode=expression_mode,
        granularity=Granularity.EXACT,
        stability=Stability.STABLE,
    )


def _prediction(doc_id: str, annotations: list[Annotation]) -> dict:
    return {
        "doc_id": doc_id,
        "status": "ok",
        "error": [],
        "annotations": [a.model_dump(mode="json") for a in annotations],
        "decisions": [],
        "anonymized_text": "",
        "risk": None,
        "runtime_ms": 0.0,
    }


#: Système de référence des tests : déclare toutes les capacités, pour que le
#: portillon laisse passer les métriques de l'axe A. Les tests de dégradation
#: passent explicitement un système sans capacités.
_SYSTEM = {
    "system_id": "test-v1",
    "system_version": "1",
    "capabilities": [
        "decisions", "gold_aware", "policy", "risk", "spans", "traces",
    ],
    "params_digest": "0" * 64,
    "oracle": False,
}


def _build(documents, gold_by_doc, predictions, **kwargs) -> dict:
    kwargs.setdefault("system", _SYSTEM)
    return build_scorecard(
        run_id="run-1",
        dataset="mini",
        split="train",
        protocol="mini-diagnostic",
        protocol_version="1",
        predictions=predictions,
        gold_by_doc=gold_by_doc,
        documents_by_doc=documents,
        reproducibility=LOCK,
        requested_status=MetricStatus.DIAGNOSTIC,
        **kwargs,
    )


@pytest.mark.parametrize(("text", "rate"), [("âge supprimé", 0.0), ("28 ans", 1.0)])
def test_quasi_only_leakage_uses_all_surfaces_and_explains_absent_directs(text, rate):
    doc = _document("d", "28 ans")
    gold = _annotation("d", 0, 2, span_text="28",
                       identifier_type=IdentifierType.QUASI, category="GEN_AGE")
    row = _prediction("d", [])
    row["anonymized_text"] = text
    card = _build({"d": doc}, {"d": (gold,)}, [row])
    full = card["diagnostic"]["gold_leak_rate"]
    assert full["value"] == rate == full["details"]["rate"]
    assert full["status"] == "diagnostic"
    assert full["details"]["definition_id"] == "gold-surface-leak-v2"
    assert "direct_leak_rate" not in card["diagnostic"]
    assert "DIRECT" in card["not_applicable"]["direct_leak_rate"]


def test_empty_gold_leakage_is_unavailable_with_reason():
    doc = _document("d", "Document sans identifiant")
    row = _prediction("d", [])
    row["anonymized_text"] = doc.text
    card = _build({"d": doc}, {"d": ()}, [row])
    for name in ("gold_leak_rate", "direct_leak_rate"):
        assert name not in card["diagnostic"]
        assert card["not_applicable"][name]


def test_gold_and_direct_leakage_have_distinct_pooled_rates_and_intervals():
    docs, gold, rows = {}, {}, []
    for i, (text, anonymous) in enumerate([("Alice 28 30 40", "Alice"), ("Bob 50", "50")]):
        doc_id = f"d{i}"
        docs[doc_id] = _document(doc_id, text)
        spans = []
        for j, word in enumerate(text.split()):
            start = text.index(word)
            spans.append(_annotation(
                doc_id, start, start + len(word), span_text=word,
                identifier_type=IdentifierType.DIRECT if j == 0 else IdentifierType.QUASI,
                category="DIR_NAME" if j == 0 else "GEN_AGE",
            ))
        gold[doc_id] = tuple(spans)
        row = _prediction(doc_id, [])
        row["anonymized_text"] = anonymous
        rows.append(row)
    card = _build(docs, gold, rows)
    full, direct = (card["diagnostic"][key] for key in ("gold_leak_rate", "direct_leak_rate"))
    assert full["value"] == pytest.approx(2 / 6)
    assert direct["value"] == pytest.approx(1 / 2)
    assert full["details"]["ci95"]["low"] == pytest.approx(1 / 4)
    assert full["details"]["ci95"]["high"] == pytest.approx(1 / 2)
    assert direct["details"]["ci95"]["low"] == 0.0
    assert direct["details"]["ci95"]["high"] == 1.0


def test_entity_recall_never_matches_across_documents() -> None:
    """Une prédiction du document B ne protège pas une mention du document A.

    Les deux documents portent « Alice » aux mêmes offsets ; seul le second est
    prédit. Une agrégation qui met en commun les spans de tout le corpus avant
    de comparer les offsets afficherait 100 % de protection.
    """
    documents = {
        "d1": _document("d1", "Alice travaille."),
        "d2": _document("d2", "Alice travaille."),
    }
    gold = {
        "d1": (_annotation("d1", 0, 5, span_text="Alice"),),
        "d2": (_annotation("d2", 0, 5, span_text="Alice"),),
    }
    predictions = [
        _prediction("d1", []),
        _prediction("d2", [_annotation("d2", 0, 5, span_text="Alice")]),
    ]
    card = _build(documents, gold, predictions)
    recall = card["diagnostic"]["span_recall"]
    assert card["diagnostic"]["counts"]["gold"] == 2
    assert recall["value"] == pytest.approx(0.5)


def test_by_expression_splits_gold_and_predictions_per_mode() -> None:
    """Chaque mode ne porte que ses propres spans.

    Le document mélange une mention explicite et une mention implicite ; verser le
    document entier dans les deux seaux ferait apparaître 2 golds par mode,
    soit le double de l'effectif réel du corpus.
    """
    documents = {"d1": _document("d1", "Alice, la voisine du dessus, travaille.")}
    explicit = _annotation("d1", 0, 5, span_text="Alice")
    implicit = _annotation(
        "d1", 7, 29, span_text="la voisine du dessus",
        expression_mode=ExpressionMode.IMPLICIT,
    )
    gold = {"d1": (explicit, implicit)}
    predictions = [_prediction("d1", [explicit])]
    card = _build(documents, gold, predictions)
    by_expression = card["by_expression"]
    assert by_expression["EXPLICIT"]["gold"] == 1
    assert by_expression["EXPLICIT"]["tp"] == 1
    assert by_expression["IMPLICIT"]["gold"] == 1
    assert by_expression["IMPLICIT"]["tp"] == 0
    assert sum(values["gold"] for values in by_expression.values()) == 2


def test_document_without_gold_or_prediction_does_not_zero_micro_precision() -> None:
    """Un document sans identifiant ni prédiction sort de la moyenne token.

    Compter sa précision comme ``0.0`` ferait chuter de moitié le score d'un
    système pourtant parfait sur les deux documents.
    """
    documents = {
        "d1": _document("d1", "Alice travaille."),
        "d2": _document("d2", "Rien a signaler ici."),
    }
    annotation = _annotation("d1", 0, 5, span_text="Alice")
    gold = {"d1": (annotation,)}
    predictions = [_prediction("d1", [annotation]), _prediction("d2", [])]
    card = _build(documents, gold, predictions)
    assert card["diagnostic"]["span_precision"]["value"] == pytest.approx(1.0)
    assert "weighted_token_precision" not in card["diagnostic"]


def test_category_counts_are_kept_without_a_redundant_macro_f1() -> None:
    documents = {"d1": _document("d1", "Alice travaille a Lyon.")}
    annotation = _annotation("d1", 0, 5, span_text="Alice")
    gold = {"d1": (annotation,)}
    predictions = [_prediction("d1", [annotation])]
    card = _build(documents, gold, predictions)
    assert card["by_qi_category"]["DIR_NAME"]["f1"] == pytest.approx(1.0)
    assert "macro_f1" not in card


def test_scorecard_survives_a_json_round_trip() -> None:
    """Aller-retour JSON sans perte : la scorecard relue reste valide (D-4)."""
    documents = {"d1": _document("d1", "Alice travaille.")}
    annotation = _annotation("d1", 0, 5, span_text="Alice")
    predictions = [_prediction("d1", [annotation])]
    card = _build(documents, {"d1": (annotation,)}, predictions)
    reloaded = json.loads(json.dumps(card, ensure_ascii=False, sort_keys=True))
    validate_scorecard(reloaded)
    assert reloaded == json.loads(json.dumps(card, ensure_ascii=False, sort_keys=True))
    assert reloaded["publishable"] is True
    assert reloaded["error_rate"] == 0.0

def test_primary_proxy_is_rejected_only_on_an_official_scorecard() -> None:
    """Un PROXY dans ``primary`` n'est interdit que si la carte se dit OFFICIAL.

    C'est le mélange d'un chiffre approché et d'un chiffre officiel que
    SPEC-07 §9 proscrit, pas l'usage d'un proxy correctement étiqueté. CPR,
    IPR et TRIR sont nécessairement PROXY tant que l'adversaire est littéral :
    les interdire en bloc viderait ``primary`` et ramènerait le F1 de spans au
    premier plan, exactement ce que SPEC-07 v2.0 cherche à éviter.
    """
    documents = {"d1": _document("d1", "Alice travaille.")}
    annotation = _annotation("d1", 0, 5, span_text="Alice")
    card = _build(documents, {"d1": (annotation,)}, [_prediction("d1", [annotation])])
    card["primary"]["naive_risk"] = {"status": MetricStatus.PROXY}

    # Catalogue fermé : même étiqueté, un nouveau proxy n'est plus publiable.
    with pytest.raises(ScorecardError, match="catalogue actif"):
        validate_scorecard(card)

    # Carte OFFICIAL : refusé.
    card["status"] = MetricStatus.OFFICIAL.value
    with pytest.raises(ScorecardError, match="catalogue actif"):
        validate_scorecard(card)


def test_naive_risk_cannot_produce_official_scorecard() -> None:
    documents = {"d1": _document("d1", "Alice travaille.")}
    annotation = _annotation("d1", 0, 5, span_text="Alice")
    prediction = _prediction("d1", [annotation])
    prediction["risk"] = {"risk": 0.5, "status": "PROXY"}

    # Dégradation explicite plutôt qu'un échec : le run reste scorable, mais
    # la carte ne se présente jamais comme OFFICIAL.
    card = build_scorecard(
        run_id="run-naive",
        dataset="mini",
        split="train",
        protocol="mini-diagnostic",
        protocol_version="1",
        predictions=[prediction],
        gold_by_doc={"d1": (annotation,)},
        documents_by_doc=documents,
        reproducibility=LOCK,
        system=_SYSTEM,
        requested_status=MetricStatus.OFFICIAL,
    )
    assert card["status"] == MetricStatus.PROXY.value
    assert "risque PROXY" in card["status_reason"]


# --------------------------------------------------------------------------- #
# EPIC-H : TRIR sans repli doc_id, contrat du texte anonymisé, intervalles
# --------------------------------------------------------------------------- #
def test_trir_is_unavailable_without_cross_document_identity() -> None:
    """Sans author_id ni sujet, TRIR n'est pas défini — la v1 publiait 1.0."""
    documents = {
        f"d{i}": _document(f"d{i}", f"Texte {i} sur Alice") for i in range(3)
    }
    predictions = [{**_prediction(doc_id, []), "anonymized_text": doc.text}
                   for doc_id, doc in documents.items()]
    card = _build(documents, {}, predictions)
    assert "trir" not in card["primary"]
    assert "trir" not in card["not_applicable"]


def test_scored_prediction_without_anonymized_text_is_rejected() -> None:
    documents = {"d1": _document("d1", "Alice travaille.")}
    prediction = _prediction("d1", [])
    del prediction["anonymized_text"]
    with pytest.raises(ScorecardError, match="anonymized_text"):
        _build(documents, {}, [prediction])


def test_point_estimates_fall_inside_their_intervals() -> None:
    texts = ["Alice travaille.", "Bob travaille.", "Carole travaille.", "David travaille."]
    documents = {f"d{i}": _document(f"d{i}", text) for i, text in enumerate(texts)}
    gold = {
        f"d{i}": (_annotation(f"d{i}", 0, len(text.split()[0]), span_text=text.split()[0]),)
        for i, text in enumerate(texts)
    }
    # Deux documents détectés et masqués, deux manqués et laissés en clair.
    predictions = [
        {**_prediction(f"d{i}", list(gold[f"d{i}"]) if i < 2 else []),
         "anonymized_text": "<PERSON> travaille." if i < 2 else texts[i]}
        for i in range(4)
    ]
    card = _build(documents, gold, predictions)
    for block, name in (("diagnostic", "span_recall"), ("diagnostic", "span_f1"),
                        ("diagnostic", "gold_leak_rate"), ("diagnostic", "mask_coverage")):
        metric = card[block][name]
        ci = metric["details"]["ci95"]
        assert ci["low"] <= metric["value"] <= ci["high"], name
        assert ci["seed"] and ci["replicates"] == 1000
        assert ci["unit"] == "document"


def test_official_run_without_spia_attack_is_scorable_and_never_substitutes_literal_cpr():
    """Un run OFFICIAL complet reste scorable ; CPR/IPR viennent du seul protocole SPIA.

    Sans attaque SPIA figée, ils sont UNAVAILABLE avec leur raison ; la
    présence littérale reste publiée sous un nom explicite, jamais à leur place.
    """
    doc = _document("d", "Alice")
    gold = _annotation("d", 0, 5, span_text="Alice")
    row = _prediction("d", [gold])
    row["anonymized_text"] = "[NOM]"
    card = build_scorecard(
        run_id="run-1", dataset="mini", split="train", protocol="mini-official",
        protocol_version="1", predictions=[row], gold_by_doc={"d": (gold,)},
        documents_by_doc={"d": doc}, reproducibility=LOCK, system=_SYSTEM,
        requested_status=MetricStatus.OFFICIAL,
    )
    assert card["status"] == "official"
    for name in ("cpr", "ipr"):
        assert name not in card["primary"]
        assert "SPIA" in card["not_applicable"][name]
    assert card["diagnostic"]["gold_leak_rate"]["value"] == 0.0
    assert "literal_cpr" not in card["diagnostic"]
    validate_scorecard(card)


def test_f1_is_zero_when_gold_is_present_but_detector_finds_nothing():
    doc = _document("d", "Alice")
    annotation = _annotation("d", 0, 5, span_text="Alice")
    card = _build({"d": doc}, {"d": (annotation,)}, [_prediction("d", [])])
    assert card["diagnostic"]["span_recall"]["value"] == 0.0
    for name in ("span_f1", "span_strict_f1"):
        assert card["diagnostic"][name]["value"] == 0.0
    assert "span_precision" in card["not_applicable"]


def test_false_positives_without_gold_are_not_hidden_as_undefined_f1():
    doc = _document("d", "Alice")
    annotation = _annotation("d", 0, 5, span_text="Alice")
    card = _build({"d": doc}, {"d": ()}, [_prediction("d", [annotation])], span_gold_available=True)
    assert card["diagnostic"]["span_f1"]["value"] == 0.0
    assert card["diagnostic"]["span_precision"]["value"] == 0.0
    assert "span_recall" in card["not_applicable"]


def test_corpus_without_span_gold_is_not_treated_as_negative_annotations():
    doc = _document("d", "Alice")
    annotation = _annotation("d", 0, 5, span_text="Alice")
    card = _build({"d": doc}, {}, [_prediction("d", [annotation])])
    for name in ("span_precision", "span_recall", "span_f1", "span_strict_f1"):
        assert name not in card["diagnostic"]
        assert "absence d'annotations" in card["not_applicable"][name]
    assert card["by_qi_category"] == {} and card["by_language"] == {}
    assert "fp" not in card["diagnostic"]["counts"]
    assert not card["publishable"]
    assert any("aucune métrique de qualité" in reason for reason in card["publication_blockers"])


def test_catalog_is_closed_and_retired_metrics_cannot_be_reintroduced():
    from anonymisation.metrics.catalog import RETIRED_METRICS

    doc = _document("d", "Alice")
    annotation = _annotation("d", 0, 5, span_text="Alice")
    card = _build({"d": doc}, {"d": (annotation,)}, [_prediction("d", [annotation])])
    assert not (set(card["primary"]) | set(card["diagnostic"])) & RETIRED_METRICS
    for name in RETIRED_METRICS:
        altered = {**card, "diagnostic": {**card["diagnostic"], name: {
            **card["diagnostic"]["span_f1"], "name": name}}}
        with pytest.raises(ScorecardError, match="catalogue actif"):
            validate_scorecard(altered)
    with pytest.raises(ScorecardError, match="catalogue actif"):
        _build({"d": doc}, {}, [_prediction("d", [])], external_diagnostics={"rouge_l": {}})


def test_core_scoring_never_calls_retired_computations_or_any_model(monkeypatch):
    from anonymisation.llm.client import LlmClient
    from anonymisation.metrics import combinations, downstream, tria, utility

    def forbidden(*args, **kwargs):
        raise AssertionError("calcul retiré ou modèle appelé par score")

    for module, name in ((combinations, "combination_metrics"), (downstream, "evaluate_downstream_task"),
                         (tria, "evaluate_trir"), (utility, "mean_utility_from_judgments"),
                         (utility, "mean_utility_over_documents"), (utility, "rouge_l")):
        monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(LlmClient, "complete", forbidden)
    doc = _document("d", "Alice")
    annotation = _annotation("d", 0, 5, span_text="Alice")
    card = _build({"d": doc}, {"d": (annotation,)}, [_prediction("d", [annotation])])
    assert card["schema_version"] == "3.1"
    assert card["diagnostic"]["span_f1"]["value"] == 1.0
    assert card["scoring"]["modules_sha256"]["scorecard.py"]

"""Tests de l'orchestrateur des huit étapes (ticket C-1, SPEC-10 §3-4, §10).

Couvre l'acceptation C-1 :
* le profil « deterministic » se charge : pas de NER, pas de LLM ;
* chaque étape centrale laisse sa ``StageTrace`` (jamais d'absence) ;
* les étapes LLM désactivées laissent une trace « skipped » explicite ;
* l'invariant d'offset : tous les offsets portent sur le texte original ;
* l'exécution bout-en-bout du jeu micro (statuts ``ok`` / ``partial``).

Plus les garde-fous d'orchestration : exclusion par budget (C4), refus à la
construction des capacités non implémentées, exception d'étape convertie en
``error`` (jamais de crash), interruption ``fail_on_leak`` limitée au
document fautif, déterminisme bit-à-bit du mode strict, et les scénarios
S1-S3 de SPEC-07 §11 (monotonie risque/utilité des politiques).

Les métriques de risque sont des PROXIES (SPEC-07 §9) : estimateur naive,
coût utilitaire de la table du moteur — jamais publiées comme chiffres
officiels.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import yaml

from anonymisation.pipeline.orchestrator import (
    Pipeline,
    PipelineCapabilityError,
    _merge_overlapping,
)
from anonymisation.pipeline.profiles import RuntimeProfile, load_runtime_profile
from anonymisation.pipeline.traces import (
    PIPELINE_STATUSES,
    STAGE_ORDER,
    serialize_pipeline_result,
    serialize_stage_trace,
)
from anonymisation.policy.engine import (
    DEFAULT_UTILITY_COST,
    NaiveRiskEstimator,
    PolicyEngine,
    _QiState,
)
from anonymisation.policy.models import load_policy_set
from anonymisation.schema.models import Annotation, Document, Domain
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Stability,
)
from anonymisation.transform.decisions import Action, AnonymizationDecision
from anonymisation.transform.generalize import generalize

REPO_ROOT = Path(__file__).resolve().parents[2]
_MICRO = REPO_ROOT / "tests" / "fixtures" / "micro"
POLICIES = REPO_ROOT / "configs" / "policy" / "policies.yaml"
DETERMINISTIC_YAML = REPO_ROOT / "configs" / "runtime" / "deterministic.yaml"

#: Rang de protection croissante des actions (plus grand = plus protectrice).
_ACTION_RANK = {
    Action.KEEP: 0,
    Action.GENERALIZE: 1,
    Action.PSEUDONYMIZE: 2,
    Action.MASK: 3,
    Action.SUPPRESS: 4,
}


# --------------------------------------------------------------------------- #
# Fixtures et helpers
# --------------------------------------------------------------------------- #
def _load_micro() -> tuple[list[Document], dict[str, tuple[Annotation, ...]]]:
    """Le jeu micro du dépôt (5 documents, annotations gold du pivot)."""
    docs = [
        Document.model_validate(json.loads(line))
        for line in (_MICRO / "documents.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    gold: dict[str, list[Annotation]] = {}
    for line in (_MICRO / "annotations.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ann = Annotation.model_validate(json.loads(line))
        gold.setdefault(ann.doc_id, []).append(ann)
    return docs, {k: tuple(v) for k, v in gold.items()}


@pytest.fixture(scope="module")
def micro() -> tuple[list[Document], dict[str, tuple[Annotation, ...]]]:
    return _load_micro()


@pytest.fixture(scope="module")
def pipeline() -> Pipeline:
    return Pipeline("deterministic")


def _profile_from_raw(mutate) -> RuntimeProfile:
    """Charge le profil deterministic avec une mutation de sa forme YAML."""
    raw = yaml.safe_load(DETERMINISTIC_YAML.read_text(encoding="utf-8"))
    mutate(raw)
    return RuntimeProfile.model_validate(raw)


def _set(raw: dict, key_path: tuple[str, ...], value) -> None:
    node = raw
    for key in key_path[:-1]:
        node = node[key]
    node[key_path[-1]] = value


# --------------------------------------------------------------------------- #
# C-1 A1 — le profil deterministic se charge : pas de NER, pas de LLM
# --------------------------------------------------------------------------- #
def test_deterministic_profile_loads_without_ner_or_llm() -> None:
    loaded = load_runtime_profile("deterministic")
    p = loaded.profile
    assert p.profile == "deterministic"
    assert p.stages.detect.deterministic.enabled is True
    assert p.stages.detect.ner.enabled is False
    assert p.stages.detect.llm_reviewer.enabled is False
    assert p.stages.audit.enabled is False
    assert p.stages.rewrite.enabled is False
    assert p.llm.allow_remote is False
    assert p.determinism.strict is True
    assert p.determinism.seed == 42

def test_naive_profile_emits_one_proxy_warning(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="anonymisation.pipeline.profiles")
    caplog.clear()

    load_runtime_profile("deterministic")

    warnings = [
        record
        for record in caplog.records
        if "assess.estimator='naive'" in record.getMessage()
    ]
    assert len(warnings) == 1


# --------------------------------------------------------------------------- #
# C-1 A2 — chaque étape centrale laisse sa trace
# --------------------------------------------------------------------------- #
def test_six_core_stages_each_produce_a_trace(micro: object, pipeline: Pipeline) -> None:
    docs, _ = micro
    result = pipeline.run(docs[0])
    assert len(result.traces) == 8
    assert [t.stage for t in result.traces] == list(STAGE_ORDER)
    assert [t.order for t in result.traces] == list(range(1, 9))
    # Les six étapes centrales s'exécutent toutes avec succès.
    for trace in result.traces[:6]:
        assert trace.status == "ok", f"{trace.stage} : {trace.error}"


# --------------------------------------------------------------------------- #
# C-1 A3 — les étapes LLM désactivées laissent une trace « skipped »
# --------------------------------------------------------------------------- #
def test_disabled_llm_stages_produce_skipped_traces(micro: object, pipeline: Pipeline) -> None:
    docs, _ = micro
    result = pipeline.run(docs[0])
    for stage in ("AUDIT", "REWRITE"):
        trace = next(t for t in result.traces if t.stage == stage)
        assert trace.status == "skipped", stage
        assert trace.decisions, f"{stage} : une trace skipped doit documenter sa raison"
        assert "v1" in trace.decisions[0]["reason"]


# --------------------------------------------------------------------------- #
# C-1 A4 — invariant d'offset : offsets sur le texte original, après transform
# --------------------------------------------------------------------------- #
def test_offsets_always_refer_to_original_text(micro: object, pipeline: Pipeline) -> None:
    docs, gold = micro
    for doc in docs:
        result = pipeline.run(doc, gold.get(doc.doc_id))
        for ann in result.annotations:
            assert result.original_text[ann.start : ann.end] == ann.span_text, (
                f"{ann.doc_id} : l'annotation {ann.annotation_id} ne pointe pas "
                "sur le texte original"
            )
        for decision in result.decisions:
            assert result.original_text[decision.start : decision.end] == decision.original, (
                f"{doc.doc_id} : la décision {decision.qi_category} ne pointe pas "
                "sur le texte original"
            )


# --------------------------------------------------------------------------- #
# C-1 A5 — exécution bout-en-bout du jeu micro
# --------------------------------------------------------------------------- #
def test_micro_dataset_end_to_end(micro: object, pipeline: Pipeline) -> None:
    docs, gold = micro
    assert [d.doc_id for d in docs] == [f"micro:d{i}" for i in range(1, 6)]
    for doc in docs:
        result = pipeline.run(doc, gold.get(doc.doc_id))
        assert result.status in PIPELINE_STATUSES, result.errors
        assert len(result.traces) == 8

    # Tous les identifiants DIRECT du micro sont désormais protégés : l'email
    # `jean.dupont@example.com` l'est depuis que `deny_context` dégrade la
    # confiance d'un candidat DIRECT au lieu de l'écarter (les domaines
    # réservés RFC 2606 sont ceux des corpus synthétiques, donc des adresses
    # à protéger). La détection de fuite est éprouvée séparément, sur un cas
    # que le détecteur ne peut pas voir : voir
    # `test_gold_leak_is_detected_independently_of_the_detector`.
    statuses = [pipeline.run(d, gold.get(d.doc_id)).status for d in docs]
    assert statuses == ["ok", "ok", "ok", "ok", "ok"]

    d5 = pipeline.run(docs[4], gold.get(docs[4].doc_id))
    assert "jean.dupont@example.com" not in d5.anonymized_text
    assert d5.errors == ()


# --------------------------------------------------------------------------- #
# Garde-fou : fail_on_leak interrompt le document seul, jamais le run
# --------------------------------------------------------------------------- #
def test_fail_on_leak_interrupts_only_that_document(micro: object) -> None:
    profile = _profile_from_raw(lambda raw: _set(raw, ("stages", "validate", "fail_on_leak"), True))
    p = Pipeline(profile)
    docs, gold = micro
    # Le micro ne fuit plus : tous ses documents restent « ok ».
    assert [p.run(d, gold.get(d.doc_id)).status for d in docs] == ["ok"] * len(docs)

    # Seul le document qui fuit réellement bascule en « error ».
    leak_doc, leak_gold = _leak_case()
    leaked = p.run(leak_doc, leak_gold)
    assert leaked.status == "error"
    validate_trace = next(t for t in leaked.traces if t.stage == "VALIDATE")
    assert validate_trace.status == "error"
    assert "fail_on_leak" in (validate_trace.error or "")
    # Les étapes en aval restent tracées « skipped » — jamais une absence.
    for trace in leaked.traces[6:]:
        assert trace.status == "skipped", trace.stage
        assert "VALIDATE" in trace.decisions[0]["reason"]


# --------------------------------------------------------------------------- #
# Cas de fuite construit localement
# --------------------------------------------------------------------------- #
#: Un nom de personne est l'angle mort **permanent et légitime** d'un profil
#: déterministe sans NER : le gold le déclare DIRECT, aucun motif ni aucune
#: règle ne peut le trouver. C'est le seul cas de fuite honnête pour éprouver
#: le contrôle indépendant du détecteur — s'appuyer sur un identifiant que le
#: détecteur *devrait* trouver reviendrait à figer un défaut en test.
_LEAK_TEXT = "Le dossier a ete transmis a Camille Berthier hier."
_LEAK_NAME = "Camille Berthier"


def _leak_case() -> tuple[Document, tuple[Annotation, ...]]:
    start = _LEAK_TEXT.index(_LEAK_NAME)
    doc = Document(
        doc_id="leak:d1", dataset="leak", split="train", domain=Domain.HR,
        language="fr", text=_LEAK_TEXT,
    )
    gold = Annotation(
        annotation_id="leak:a1", doc_id="leak:d1",
        start=start, end=start + len(_LEAK_NAME), span_text=_LEAK_NAME,
        identifier_type=IdentifierType.DIRECT, qi_categories=("DIR_NAME",),
        expression_mode=ExpressionMode.EXPLICIT,
        granularity=Granularity.EXACT, stability=Stability.STABLE,
    )
    return doc, (gold,)


def test_gold_leak_is_detected_independently_of_the_detector() -> None:
    """Un nom que le détecteur ne sait pas voir doit quand même être signalé."""
    doc, gold = _leak_case()
    result = Pipeline("deterministic").run(doc, gold)

    assert _LEAK_NAME in result.anonymized_text, "le détecteur ne peut pas le masquer"
    assert result.status == "partial", "la fuite gold doit dégrader le statut"
    assert result.errors and result.errors[0].startswith("VALIDATE")
    trace = next(t for t in result.traces if t.stage == "VALIDATE")
    assert trace.status == "ok", "constat non fatal : le run continue"
    findings = trace.decisions[0]
    assert findings["kind"] == "findings"
    assert findings["leaked_direct"] >= 1


# --------------------------------------------------------------------------- #
# Garde-fou : une exception d'étape devient un statut « error » nommé
# --------------------------------------------------------------------------- #
def test_stage_exception_is_captured_never_escapes(
    micro: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = Pipeline("deterministic")
    docs, gold = micro

    def _explode(state: object) -> None:
        raise RuntimeError("explosion contrôlée")

    monkeypatch.setattr(p, "_stage_fuse", _explode)
    result = p.run(docs[0], gold.get(docs[0].doc_id))

    assert result.status == "error"
    assert result.errors == ("FUSE: explosion contrôlée",)
    assert result.traces[1].status == "error"
    assert result.traces[1].error == "FUSE: explosion contrôlée"
    # Tout ce qui suit FUSE est tracé « skipped » avec la raison.
    for trace in result.traces[2:]:
        assert trace.status == "skipped", trace.stage
        assert "FUSE" in trace.decisions[0]["reason"]


# --------------------------------------------------------------------------- #
# Garde-fou C4 : un document hors budget est exclu, jamais compté vide
# --------------------------------------------------------------------------- #
def test_budget_excludes_oversized_document(micro: object) -> None:
    p = Pipeline(_profile_from_raw(lambda raw: _set(raw, ("budgets", "max_document_chars"), 10)))
    docs, _ = micro
    result = p.run(docs[0])

    assert result.status == "error"
    assert result.errors[0].startswith("BUDGET")
    assert "contrainte C4" in result.errors[0]
    # Le texte n'est PAS anonymisé : exclusion, pas prédiction vide.
    assert result.anonymized_text == result.original_text
    assert result.annotations == ()
    assert result.decisions == ()
    assert result.risk is None
    assert len(result.traces) == 8
    assert all(t.status == "skipped" for t in result.traces)


# --------------------------------------------------------------------------- #
# Refus à la construction des capacités non implémentées (audit §12)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("key_path", "value", "needle"),
    [
        (("stages", "detect", "deterministic", "enabled"), False, "détecteur déterministe"),
        (("stages", "detect", "ner", "enabled"), True, "NER"),
        (("stages", "detect", "llm_reviewer", "enabled"), True, "relecteur LLM"),
        (("stages", "audit", "enabled"), True, "audit"),
        (("stages", "rewrite", "enabled"), True, "réécriture"),
        (("llm", "allow_remote"), True, "allow_remote"),
        (("stages", "assess", "estimator"), "copula", "naive"),
        (("stages", "fuse", "enabled"), False, "FUSE"),
        (("stages", "validate", "enabled"), False, "VALIDATE"),
    ],
)
def test_unimplemented_capability_refused_at_construction(
    key_path: tuple[str, ...],
    value: object,
    needle: str,
) -> None:
    profile = _profile_from_raw(lambda raw: _set(raw, key_path, value))
    with pytest.raises(PipelineCapabilityError, match=needle):
        Pipeline(profile)


# --------------------------------------------------------------------------- #
# Déterminisme bit-à-bit du profil strict (SPEC-10 §10)
# --------------------------------------------------------------------------- #
def test_strict_serialization_is_bit_to_bit_deterministic(micro: object) -> None:
    """La sérialisation passe par le **système**, pas par l'orchestrateur nu.

    ``serialize_pipeline_result`` refuse un résultat non estampillé : c'est
    ``SystemBase.run`` qui appose l'identité, et c'est bien cette frontière-là
    qu'on doit éprouver, puisque c'est elle qui écrit ``predictions.jsonl``.
    """
    from anonymisation.systems import SystemConfig, resolve_system

    pipeline = resolve_system("deterministic")(SystemConfig(policy_id="P2"))
    docs, gold = micro
    first = [
        json.dumps(
            serialize_pipeline_result(pipeline.run(d, gold.get(d.doc_id)), strict=True),
            ensure_ascii=False,
            sort_keys=True,
        )
        for d in docs
    ]
    second = [
        json.dumps(
            serialize_pipeline_result(pipeline.run(d, gold.get(d.doc_id)), strict=True),
            ensure_ascii=False,
            sort_keys=True,
        )
        for d in docs
    ]
    assert first == second  # replay bit-à-bit
    assert json.loads(first[0])["runtime_ms"] == 0.0

    # Les traces sérialisées en strict zéroisent la durée (horloge exclue).
    traces_a = [
        json.dumps(serialize_stage_trace(t, strict=True), ensure_ascii=False, sort_keys=True)
        for t in pipeline.run(docs[0]).traces
    ]
    traces_b = [
        json.dumps(serialize_stage_trace(t, strict=True), ensure_ascii=False, sort_keys=True)
        for t in pipeline.run(docs[0]).traces
    ]
    assert traces_a == traces_b
    assert all(json.loads(line)["duration_ms"] == 0.0 for line in traces_a)


# --------------------------------------------------------------------------- #
# S1-S3 (SPEC-07 §11) — monotonie risque/utilité
# --------------------------------------------------------------------------- #
# Jeu de référence : trois quasi-identifiants détectables (âge, discipline,
# ancienneté) sur un document synthétique.
S3_TEXT = "J'ai 45 ans, je suis diplômé d'informatique et je travaille depuis 2015."


def _s3_annotations() -> list[Annotation]:
    spec = [
        ("45 ans", "GEN_AGE", {"range": [45, 45], "level": 0}),
        (
            "informatique",
            "GEN_EDUCATION",
            {"discipline": "informatique", "level_edu": "master", "level": 0},
        ),
        ("depuis 2015", "HR_SENIORITY", None),
    ]
    return [
        Annotation(
            annotation_id=f"s3:a{i + 1}",
            doc_id="s3:doc",
            start=S3_TEXT.index(span),
            end=S3_TEXT.index(span) + len(span),
            span_text=span,
            identifier_type=IdentifierType.QUASI,
            qi_categories=(cat,),
            expression_mode=ExpressionMode.EXPLICIT,
            granularity=Granularity.EXACT,
            stability=Stability.STABLE,
            value_normalized=vn,
        )
        for i, (span, cat, vn) in enumerate(spec)
    ]


def _s3_states() -> list[_QiState]:
    return [
        _QiState(a.annotation_id, a.qi_categories[0], 0)
        for a in _s3_annotations()
    ]


def _decision_cost(decision: AnonymizationDecision) -> float:
    """Coût utilitaire d'une décision (proxy, table du moteur) ; la
    généralisation est facturée par niveau parcouru."""
    if decision.action is Action.KEEP:
        return 0.0
    if decision.action is Action.GENERALIZE:
        return DEFAULT_UTILITY_COST["GENERALIZE_PER_LEVEL"] * _levels_applied(decision)
    return DEFAULT_UTILITY_COST[decision.action.value]


def _levels_applied(decision: AnonymizationDecision) -> int:
    """Niveaux de généralisation réellement parcourus, recomputés avec la même
    hiérarchie que le moteur (pas de valeur par défaut silencieuse)."""
    ann = next(
        (a for a in _s3_annotations() if a.span_text == decision.original),
        None,
    )
    assert ann is not None and ann.value_normalized, decision
    current = dict(ann.value_normalized)
    for levels in range(1, 5):
        step = generalize(current, decision.qi_category)
        assert step is not None, f"hiérarchie épuisée pour {decision.qi_category}"
        surface, current = step
        if surface == decision.replacement:
            return levels
    raise AssertionError(
        f"replacement {decision.replacement!r} non atteint après 4 niveaux "
        f"pour {decision.qi_category}"
    )


def _utility_retention(decisions: list[AnonymizationDecision], n_qis: int) -> float:
    """Retenue d'utilité = 1 - coût total / coût maximal (tout supprimer)."""
    max_cost = n_qis * DEFAULT_UTILITY_COST["SUPPRESS"]
    return 1.0 - sum(_decision_cost(d) for d in decisions) / max_cost


def _final_risk(decisions: list[AnonymizationDecision]) -> float:
    """Risque final de la boucle de planification : le ``risk_after`` de la
    dernière décision appliquée (les KEEP ne portent pas de risque)."""
    for decision in reversed(decisions):
        if decision.risk_after is not None:
            return decision.risk_after
    return 0.0


def test_s1_non_anonymized_high_risk_full_utility() -> None:
    """S1 : texte non anonymisé → R_succ élevé, UtilityRetention = 1.0."""
    risk = NaiveRiskEstimator()(_s3_states())
    assert risk >= 0.2, f"risque initial {risk} censé être élevé"
    # Aucune décision appliquée → aucune perte d'utilité.
    assert _utility_retention([], 3) == 1.0


def test_s2_total_suppression_zero_risk_minimal_utility() -> None:
    """S2 : tout supprimé → R_succ ≈ 0, utilité minimale."""
    assert NaiveRiskEstimator()([]) == 0.0  # plus aucun QI → aucun risque
    suppressed = [
        AnonymizationDecision(
            start=a.start,
            end=a.end,
            original=a.span_text,
            action=Action.SUPPRESS,
            replacement="",
            qi_category=a.qi_categories[0],
            reason="test S2 : suppression totale",
        )
        for a in _s3_annotations()
    ]
    assert _utility_retention(suppressed, 3) == 0.0


def test_s3_stricter_policy_lower_risk_lower_utility() -> None:
    """S3 : politique plus stricte (P3) → R_succ strictement plus bas,
    utilité strictement plus basse, et jamais moins protectrice."""
    anns = _s3_annotations()
    policies = load_policy_set(POLICIES)
    p2 = PolicyEngine(policies.get("P2")).plan(anns, text=S3_TEXT)
    p3 = PolicyEngine(policies.get("P3")).plan(anns, text=S3_TEXT)

    assert _final_risk(p3) < _final_risk(p2)
    assert _utility_retention(p3, 3) < _utility_retention(p2, 3)

    by_ann_p2 = {a.annotation_id: None for a in anns}
    by_ann_p3 = {a.annotation_id: None for a in anns}
    for decision in p2:
        ann = next(a for a in anns if a.span_text == decision.original)
        by_ann_p2[ann.annotation_id] = decision.action
    for decision in p3:
        ann = next(a for a in anns if a.span_text == decision.original)
        by_ann_p3[ann.annotation_id] = decision.action
    for ann_id in by_ann_p2:
        assert _ACTION_RANK[by_ann_p3[ann_id]] >= _ACTION_RANK[by_ann_p2[ann_id]], (
            f"{ann_id} : P3 ne doit jamais être moins protectrice que P2"
        )


def test_transitive_overlaps_merge_into_one_safe_decision() -> None:
    """Un span long et deux spans internes ne doivent laisser aucun
    chevauchement résiduel à ``apply_decisions``."""
    text = "01234567890123456789"
    decisions = [
        AnonymizationDecision(
            start=0,
            end=10,
            original=text[0:10],
            action=Action.SUPPRESS,
            replacement="[X]",
            qi_category="DIR_NAME",
            reason="test",
        ),
        AnonymizationDecision(
            start=1,
            end=4,
            original=text[1:4],
            action=Action.SUPPRESS,
            replacement="[Y]",
            qi_category="DIR_NAME",
            reason="test",
        ),
        AnonymizationDecision(
            start=9,
            end=12,
            original=text[9:12],
            action=Action.SUPPRESS,
            replacement="[Z]",
            qi_category="DIR_NAME",
            reason="test",
        ),
    ]
    merged = _merge_overlapping(decisions, text)
    assert len(merged) == 1
    assert (merged[0].start, merged[0].end) == (0, 12)
    assert merged[0].original == text[:12]

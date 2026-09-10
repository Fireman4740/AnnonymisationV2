"""Tests spécifiques pour RegexOnlySystem et PatternDetector."""

from __future__ import annotations

import pytest

from anonymisation.capabilities import CAP_DECISIONS, CAP_SPANS
from anonymisation.detect import PatternDetector
from anonymisation.schema.models import Document, Domain
from anonymisation.systems import SystemConfig
from anonymisation.systems.base import SystemError_
from anonymisation.pipelines.regex_only.system import RegexOnlySystem


def test_pattern_detector_uses_no_rules():
    detector = PatternDetector()
    assert detector.name == "pattern_detector"
    assert len(detector.patterns) > 0
    # On vérifie sur un texte qui déclencherait une règle contextuelle mais pas un motif regex seul
    # ou simplement que detect s'exécute correctement
    candidates = detector.detect("Mon numéro est 0601020304 et mon email test@example.com", "fr")
    assert len(candidates) >= 1
    # Doit respecter l'invariant d'offsets
    text = "Mon numéro est 0601020304"
    for c in detector.detect(text, "fr"):
        assert text[c.start:c.end] == c.text


def test_regex_only_system_identity_and_capabilities():
    system = RegexOnlySystem(SystemConfig())
    ident = system.identity()
    assert ident.system_id == "regex-only-v1"
    assert ident.system_version == "1"
    assert system.capabilities == frozenset({CAP_SPANS, CAP_DECISIONS})
    assert system.uses_policy is False


def test_regex_only_system_rejects_policy():
    with pytest.raises(SystemError_, match="n'en consomme pas"):
        RegexOnlySystem(SystemConfig(policy_id="P2"))


def test_regex_only_system_produces_spans_and_decisions():
    system = RegexOnlySystem(SystemConfig())
    doc = Document(
        doc_id="test-doc-1",
        dataset="test_ds",
        split="test",
        domain=Domain.GENERIC,
        language="fr",
        text="Contactez moi par téléphone : 06 01 02 03 04 ou sur jean.dupont@societe.fr",
    )
    result = system.run(doc, gold_annotations=())
    assert len(result.annotations) >= 1
    assert len(result.decisions) == len(result.annotations)
    assert result.risk is None
    for dec in result.decisions:
        assert dec.action.value == "SUPPRESS"
        assert doc.text[dec.start:dec.end] == dec.original
    assert "[DIR_PHONE_SUPPRIME]" in result.anonymized_text

def test_pipeline_with_custom_detector():
    from anonymisation.pipeline.orchestrator import Pipeline

    detector = PatternDetector()
    pipeline = Pipeline("deterministic", detector=detector, policy_id="P0")
    doc = Document(
        doc_id="test-doc-2",
        dataset="test_ds",
        split="test",
        domain=Domain.GENERIC,
        language="fr",
        text="Voici mon email : contact@domain.fr",
    )
    res = pipeline.run(doc, ())
    assert res.status == "ok"

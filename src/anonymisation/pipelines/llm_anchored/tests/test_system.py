"""Comportements de confidentialité sur des données synthétiques, sans réseau."""
import json

from anonymisation.llm.client import LlmCompletion
from anonymisation.pipelines.llm_anchored.prompts import Finding
from anonymisation.pipelines.llm_anchored.system import LlmAnchoredSystem, locate_unique
from anonymisation.schema.models import Document, Domain
from anonymisation.systems.base import SystemConfig


def completion(entities):
    return LlmCompletion(content=json.dumps({'entities': entities}), backend='stub', model='stub',
                         cached=False, finish_reason='stop', latency_ms=1.0)


def document(text):
    return Document(doc_id='test', dataset='synthetic', split='test', domain=Domain.GENERIC,
                    language='fr', text=text)


def test_critic_is_blind_and_preserves_baseline_decisions(monkeypatch):
    system = LlmAnchoredSystem(SystemConfig(params={'backend': 'stub'}))
    monkeypatch.setattr(system._baseline._client, 'complete', lambda *a, **k: completion([
        {'span': 'Alice', 'category': 'DIR_NAME', 'action': 'SUPPRESS', 'replacement': ''}]))
    seen = []
    def critic(prompt, **kwargs):
        seen.append(prompt)
        return completion([{'span':'1981','category':'GEN_AGE','left':'née en ','right':'.'}])
    monkeypatch.setattr(system._critic, 'complete', critic)
    text = 'Alice est née en 1981.'
    result = system.run(document(text))
    assert result.status == 'ok', result.errors
    assert 'Alice' not in seen[0] and '[DIR_NAME_SUPPRIME]' in seen[0]
    assert 'Alice' not in result.anonymized_text and '1981' not in result.anonymized_text
    assert all(text[a.start:a.end] == a.span_text for a in result.annotations)
    assert any(d.original == 'Alice' for d in result.decisions)


def test_ambiguous_or_partial_word_is_not_silently_guessed():
    ambiguous = Finding(span='Paris', category='GEN_GEO', left='', right='')
    assert locate_unique('Paris et Paris', ambiguous) is None
    unique = Finding(span='Paris', category='GEN_GEO', left='à ', right='.')
    assert locate_unique('Paris puis à Paris.', unique) == (13, 18)
    assert locate_unique('Malice', Finding(span='Alice', category='DIR_NAME', left='', right='')) is None


def test_critic_cannot_replace_a_baseline_placeholder(monkeypatch):
    system = LlmAnchoredSystem(SystemConfig(params={'backend': 'stub'}))
    monkeypatch.setattr(system._baseline._client, 'complete', lambda *a, **k: completion([
        {'span':'Alice','category':'DIR_NAME','action':'SUPPRESS','replacement':''}]))
    monkeypatch.setattr(system._critic, 'complete', lambda *a, **k: completion([
        {'span':'[DIR_NAME_SUPPRIME]','category':'DIR_NAME','left':'','right':''}]))
    result = system.run(document('Alice est ici.'))
    assert result.status == 'partial'
    assert result.anonymized_text == '[DIR_NAME_SUPPRIME] est ici.'
    assert len(result.decisions) == 1


def test_critic_failure_is_an_error_not_a_silent_success(monkeypatch):
    from anonymisation.llm.client import LlmEmptyResponseError

    system = LlmAnchoredSystem(SystemConfig(params={'backend': 'stub'}))
    monkeypatch.setattr(system._baseline._client, 'complete', lambda *a, **k: completion([]))
    def failed(*args, **kwargs):
        raise LlmEmptyResponseError('truncated')
    monkeypatch.setattr(system._critic, 'complete', failed)
    result = system.run(document('Un exemple.'))
    assert result.status == 'error'
    assert any('LlmEmptyResponseError' in e for e in result.errors)


def test_disabled_critic_is_the_windowed_baseline(monkeypatch):
    system = LlmAnchoredSystem(SystemConfig(params={'backend': 'stub', 'critique': False}))
    monkeypatch.setattr(system._baseline._client, 'complete', lambda *a, **k: completion([
        {'span':'Alice','category':'DIR_NAME','action':'SUPPRESS','replacement':''}]))
    text = document('Alice est ici.')
    baseline = system._baseline.run(text)
    anchored = system.run(text)
    assert anchored.anonymized_text == baseline.anonymized_text
    assert anchored.decisions == baseline.decisions
    assert anchored.annotations == baseline.annotations
    assert anchored.identity.system_id == 'llm-anchored-v1'

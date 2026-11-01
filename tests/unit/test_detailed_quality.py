import hashlib
import json
from types import SimpleNamespace

import pytest

from anonymisation.judge import detailed_quality as judge
from anonymisation.llm.client import LlmCompletion
from anonymisation.metrics.detailed_quality import detailed_quality_metrics


class FakeJudge:
    def __init__(self, *, break_control=False):
        self.break_control = break_control
        self.prompts = []

    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if prompt.startswith(judge.INVENTION_PROMPT):
            data = json.loads(prompt[len(judge.INVENTION_PROMPT):])
            response = {'items': [{'id': x['id'], 'quotes': []} for x in data['candidates']]}
        elif prompt.startswith(judge.FACT_PROMPT):
            data = json.loads(prompt[len(judge.FACT_PROMPT):])
            response = {'facts': [{'id': x['id'], 'verdict': 'preserved' if i == 0 else 'uncertain'}
                                  for i, x in enumerate(data['facts'])]}
        else:
            is_read = prompt.startswith(judge.READ_PROMPT)
            prefix = judge.READ_PROMPT if is_read else judge.PAIR_PROMPT
            data = json.loads(prompt[len(prefix):])
            items = data['texts' if is_read else 'candidates']
            response = {'items': []}
            for item in items:
                empty = not item['text']
                identity = not is_read and item['text'] == data['source']
                answers = []
                for q in data['questions']:
                    answer = 'yes'
                    if empty and q in {'read_understandable', 'read_grammar', 'relevance_main'}:
                        answer = 'yes' if self.break_control else 'no'
                    elif not empty and not identity and q == 'read_references':
                        answer = 'na'
                    elif not empty and not identity and q == 'fidelity_invention':
                        answer = 'no'
                    answers.append({'question': q, 'answer': answer})
                response['items'].append({'id': item['id'], 'answers': answers})
        text = json.dumps(response)
        kwargs['validate'](text)
        return LlmCompletion(content=text, backend='stub', model='stub', cached=False,
                             finish_reason='stop', latency_ms=0)


def test_checklist_controls_na_and_invention_are_reported_separately():
    read, pair, fact, invention = FakeJudge(), FakeJudge(), FakeJudge(), FakeJudge()
    row = judge.assess_one('d', 'Alice a un rendez-vous mardi.',
                           '[PERSONNE] a un rendez-vous mardi.', [], [], read, pair, fact, invention)
    assert row['status'] == 'ok'
    assert 'Alice' not in read.prompts[0]
    metrics = detailed_quality_metrics([row], {'protocol': judge.PROTOCOL, 'judge': {'model': 'stub'}})
    assert metrics['quality_understandable']['value'] == 1
    assert metrics['quality_references']['value'] is None
    assert metrics['quality_no_contradiction']['value'] == 1
    assert metrics['quality_no_invention']['value'] == 0
    assert metrics['quality_fact_retention']['value'] is None


def test_failed_control_makes_all_metrics_unavailable():
    row = judge.assess_one('d', 'Une source.', 'Un candidat.', [], [], FakeJudge(break_control=True), FakeJudge(), FakeJudge(), FakeJudge())
    assert row['status'] == 'control_failed'
    scores = detailed_quality_metrics([row], {'protocol': judge.PROTOCOL, 'judge': {}})
    assert all(s['value'] is None for s in scores.values())


def test_facts_require_exact_source_and_uncertain_does_not_count_as_success():
    source = 'Rendez-vous mardi. Objet : réparation.'
    facts = [{'id': 'f1', 'start': 0, 'end': 17, 'text': 'Rendez-vous mardi'},
             {'id': 'f2', 'start': 19, 'end': 37, 'text': 'Objet : réparation'}]
    payload = {'protocol': 'nonprivate-facts-v1', 'study_id': 'study', 'documents': [
        {'doc_id': 'd', 'source_sha256': hashlib.sha256(source.encode()).hexdigest(), 'facts': facts}]}
    docs, predictions = {'d': SimpleNamespace(text=source)}, {'d': {}}
    assert judge.validate_facts(payload, docs, predictions)['d'] == facts
    row = judge.assess_one('d', source, 'Rendez-vous mardi. Objet : [MASQUÉ].', [], facts,
                           FakeJudge(), FakeJudge(), FakeJudge(), FakeJudge())
    metrics = detailed_quality_metrics([row], {'protocol': judge.PROTOCOL, 'judge': {}})
    assert metrics['quality_fact_retention']['value'] == 1
    assert metrics['quality_fact_retention']['details']['fact_count_uncertain'] == 1
    assert metrics['quality_fact_retention']['details']['fact_count_judged'] == 1
    payload['documents'][0]['source_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='source modifiée'):
        judge.validate_facts(payload, docs, predictions)


def test_unknown_or_repeated_question_is_rejected():
    payload = {'items': [{'id': 'A', 'answers': [{'question': 'wrong', 'answer': 'yes'}]},
                         {'id': 'B', 'answers': [{'question': 'wrong', 'answer': 'no'}]}]}
    with pytest.raises(ValueError, match='questions absentes'):
        judge._answers(judge.Batch.model_validate(payload), {'A', 'B'}, judge.READ_KEYS)


def test_invented_evidence_cannot_be_counted_as_a_fact_error():
    class FakeBadEvidence(FakeJudge):
        def complete(self, prompt, **kwargs):
            data = json.loads(prompt[len(judge.INVENTION_PROMPT):])
            response = json.dumps({'items': [{'id': x['id'], 'quotes': ['preuve absente']}
                                              for x in data['candidates']]})
            kwargs['validate'](response)
            return LlmCompletion(content=response, backend='stub', model='stub', cached=False,
                                 finish_reason='stop', latency_ms=0)
    row = judge.assess_one('d', 'La source.', 'Le candidat.', [], [], FakeJudge(), FakeJudge(),
                           FakeJudge(), FakeBadEvidence())
    assert row['status'] == 'error'

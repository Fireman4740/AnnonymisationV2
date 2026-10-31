"""Jugements locaux contrôlés, simulés sans réseau."""
import json

import pytest

from anonymisation.judge import local_quality as judge
from anonymisation.llm.client import LlmCompletion
from anonymisation.metrics.text_quality import local_quality_metrics


class FakeClient:
    def __init__(self, broken=False):
        self.broken=broken
        self.prompts=[]

    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if prompt.startswith(judge.READ_PROMPT):
            data=json.loads(prompt[len(judge.READ_PROMPT):])
            items=[{'id':x['id'],'score':2 if x['text'] else (1 if self.broken else 0)} for x in data['texts']]
        else:
            data=json.loads(prompt[len(judge.PAIR_PROMPT):])
            original=data['source']
            items=[{'id':x['id'], 'relevance':2 if x['text']==original else 1 if x['text'] else 0,
                    'faithfulness':2 if x['text']==original else 1 if x['text'] else 0} for x in data['candidates']]
        response=json.dumps({'items':items})
        kwargs['validate'](response)
        return LlmCompletion(content=response, backend='stub', model='stub', cached=False,
                             finish_reason='stop', latency_ms=0)


def test_quality_controls_and_blind_readability():
    read, pair = FakeClient(), FakeClient()
    row=judge.assess_one('d1','Alice doit remplacer son téléphone.','Une personne doit remplacer son téléphone.',read,pair)
    assert row['status']=='ok'
    assert (row['readability'],row['relevance'],row['faithfulness'])==(2,1,1)
    assert 'Alice' not in read.prompts[0]
    result=local_quality_metrics([row],{'protocol':judge.PROTOCOL,'judge':{'model':'stub'}})
    assert result['local_readability']['value']==1.0
    assert result['local_relevance']['value']==0.5
    assert result['local_faithfulness']['value']==0.5
    assert result['local_relevance']['status']=='diagnostic'


def test_failed_anchor_is_not_published_as_quality():
    row=judge.assess_one('d1','Une commande existe.','Une commande existe.',FakeClient(broken=True),FakeClient())
    assert row['status']=='control_failed'
    result=local_quality_metrics([row],{'protocol':judge.PROTOCOL,'judge':{'model':'stub'}})
    assert result['local_readability']['value'] is None
    assert result['local_readability']['status']=='unavailable'
    assert result['local_readability']['details']['control_failures']==1


def test_controls_must_not_be_silently_relabelled():
    row=judge.assess_one('d1','Texte original.','Texte.',FakeClient(broken=True),FakeClient())
    row['status']='ok'
    with pytest.raises(ValueError,match='contrôle échoué'):
        local_quality_metrics([row],{'protocol':judge.PROTOCOL,'judge':{'model':'stub'}})


def test_long_documents_are_aligned_and_weighted_without_losing_characters():
    original = ('Premier paragraphe. ' * 500) + 'Alice' + (' Dernier paragraphe.' * 500)
    start = original.index('Alice')
    candidate = original[:start] + '[PERSONNE]' + original[start + 5:]
    decisions = [{'start': start, 'end': start + 5, 'original': 'Alice',
                  'replacement': '[PERSONNE]', 'action': 'SUPPRESS',
                  'qi_category': 'DIR_NAME', 'reason': 'Nom personnel'}]
    chunks = judge._aligned_chunks('long', original, candidate, decisions)
    assert len(chunks) > 1
    assert ''.join(source for source, _ in chunks) == original
    assert ''.join(text for _, text in chunks) == candidate
    assert all(judge._fits('long', source, text) for source, text in chunks)
    row = judge.assess_one('long', original, candidate, FakeClient(), FakeClient(), decisions)
    assert row['status'] == 'ok' and row['chunks'] == len(chunks)
    assert 0.0 <= row['relevance'] <= 2.0
    assert local_quality_metrics([row], {'protocol':judge.PROTOCOL, 'judge':{'model':'stub'}})['local_relevance']['value'] is not None


def test_inconsistent_or_unbounded_replacement_is_reported_without_hanging():
    original = 'a' * 20_000
    bad = [{'start': 0, 'end': 20_000, 'original': original,
            'replacement': 'b' * 20_000, 'action': 'SUPPRESS',
            'qi_category': 'DIR_NAME', 'reason': 'Nom personnel'}]
    assert judge.assess_one('long', original, 'different', FakeClient(), FakeClient(), bad)['status'] == 'error'
    assert judge.assess_one('long', original, 'b' * 20_000, FakeClient(), FakeClient(), bad)['status'] == 'error'


def test_overlapping_windowed_decisions_are_merged_as_in_pipeline():
    original = ('texte ' * 1000) + 'Alice Martin' + (' texte' * 1000)
    start = original.index('Alice Martin')
    decisions = [
        {'start':start, 'end':start + len(s), 'original':s, 'replacement':'[PERSONNE]',
         'action':'SUPPRESS', 'qi_category':category, 'reason':'Protection'}
        for s, category in [('Alice', 'DIR_NAME'), ('Alice Martin', 'QUASI_NAME')]
    ]
    anonymized = original[:start] + '[DIR_NAME+QUASI_NAME_SUPPRIME]' + original[start + len('Alice Martin'):]
    chunks = judge._aligned_chunks('long', original, anonymized, decisions)
    assert len(chunks) > 1 and ''.join(part for _, part in chunks) == anonymized

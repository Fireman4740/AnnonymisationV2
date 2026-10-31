"""Le scoring de qualité ne remplace jamais des données absentes par des notes."""
import hashlib

import pytest

from anonymisation.metrics.text_quality import freeze_human_quality, human_quality_metrics


def payload():
    text = 'Bonjour [ANON].'
    prediction = {'doc_id': 'a', 'anonymized_text': text}
    ratings = [{'rater':'r1','readability':2,'relevance':1,'faithfulness':2},
               {'rater':'r2','readability':2,'relevance':2,'faithfulness':0}]
    data = {'rubric':'human-text-quality-v1','evaluator':'human','study_id':'study-1','rows':[
        {'doc_id':'a','anonymized_sha256':hashlib.sha256(text.encode()).hexdigest(),'ratings':ratings}]}
    return data, {'a': prediction}


def test_human_dimensions_are_distinct_and_normalized():
    data, predictions = payload()
    frozen = freeze_human_quality(data, predictions)
    result = human_quality_metrics(frozen['rows'], frozen['metadata'])
    assert result['human_readability']['value'] == 1.0
    assert result['human_relevance']['value'] == 0.75
    assert result['human_faithfulness']['value'] == 0.5
    assert result['human_readability']['details']['exact_rater_agreement'] == 1.0
    assert result['human_faithfulness']['details']['exact_rater_agreement'] == 0.0
    assert all(v['status'] == 'diagnostic' for v in result.values())


def test_quality_rejects_wrong_text_or_missing_reviewers():
    data, predictions = payload()
    data['rows'][0]['anonymized_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='empreinte'):
        freeze_human_quality(data, predictions)
    data, predictions = payload()
    data['rows'][0]['ratings'][1]['rater'] = 'r1'
    with pytest.raises(ValueError, match='distincts'):
        freeze_human_quality(data, predictions)
    data, predictions = payload()
    data['rows'][0]['ratings'][0]['relevance'] = True
    with pytest.raises(ValueError, match='entier'):
        freeze_human_quality(data, predictions)


def test_quality_rejects_unreviewed_documents_and_nonhuman_sources():
    data, predictions = payload()
    predictions['b'] = {'doc_id':'b','anonymized_text':'autre'}
    with pytest.raises(ValueError, match='omission'):
        freeze_human_quality(data, predictions)
    data, predictions = payload()
    data['evaluator'] = 'llm'
    with pytest.raises(ValueError, match='evaluator=human'):
        freeze_human_quality(data, predictions)

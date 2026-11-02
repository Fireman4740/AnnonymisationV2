import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from anonymisation.datasets.ingest import IngestionError
from anonymisation.datasets.quasileak import QuasiLeakAdapter
from anonymisation.metrics import quasileak_official
from anonymisation.metrics.quasileak_masks import group_mask_rate
from anonymisation.schema.taxonomy import Granularity, IdentifierType, Stability
from scripts.predict_quasileak_local import parse_response


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / 'QuasiLeak-Bench'
    root.mkdir()
    row = {'sample_id': 'test-1', 'document': 'clinical rotation and four-year tuition',
           'profile': {'profile_id': 'p1'},
           'context': {'context_id': 'c', 'recipient': 'support', 'purpose': 'assistance'},
           'policy': {'hide': ['education'], 'keep': ['age', 'gender', 'nationality', 'occupation'],
                      'neutral': ['income', 'relationship', 'health']},
           'gold': {'groups': [{'group_id': 'g1', 'attribute': 'education', 'cue_ids': ['s1', 's2'],
                                'distance': 'NEAR', 'secondary_attributes': []}],
                    'spans': [{'span_id': 's1', 'group_id': 'g1', 'text': 'clinical rotation', 'start': 0, 'end': 17},
                              {'span_id': 's2', 'group_id': 'g1', 'text': 'four-year tuition', 'start': 22, 'end': 39}],
                    'distractors': []}}
    data = root / 'quasileak_bench_data_full.jsonl'
    data.write_text(json.dumps(row) + '\n')
    manifest_path = root / 'split_manifest.json'
    manifest_path.write_text(json.dumps({'membership': {'train': [], 'validation': [], 'test': ['test-1']}}))
    monkeypatch.setenv('ANONV2_V1_DATASETS', str(tmp_path))
    mapping = SimpleNamespace(identifier_type=IdentifierType.QUASI, qi_categories=['GEN_EDUCATION'],
                              granularity=Granularity.COARSE, stability=Stability.STABLE)
    spec = SimpleNamespace(kind='local', path='QuasiLeak-Bench', path_env='ANONV2_V1_DATASETS',
                           files=[data.name, manifest_path.name], revision='fixture')
    manifest = SimpleNamespace(source=spec, integrity=SimpleNamespace(sha256=None), label_map={'education': mapping})
    return root, row, manifest


def test_adapter_preserves_hide_groups_without_leaking_gold(source, tmp_path):
    _, row, manifest = source
    adapter = QuasiLeakAdapter(manifest, tmp_path / 'raw')
    document = next(adapter.iter_documents('test'))
    annotations = list(adapter.iter_annotations('test'))
    assert document.author_id == 'p1'
    assert 'gold' not in document.meta and 'profile' not in document.meta
    assert document.meta['policy']['hide'] == ['education']
    assert [(a.start, a.end) for a in annotations] == [(0, 17), (22, 39)]
    assert all(a.meta['group_id'] == 'g1' and a.meta['policy'] == 'HIDE' for a in annotations)
    assert len(list(adapter.iter_profiles('test'))) == 1
    assert list(adapter.iter_documents('train')) == []
    assert row['document'][annotations[1].start:annotations[1].end] == annotations[1].span_text


def test_adapter_rejects_invalid_source_and_policy(source, tmp_path):
    root, row, manifest = source
    row['gold']['spans'][0]['end'] += 1
    (root / 'quasileak_bench_data_full.jsonl').write_text(json.dumps(row) + '\n')
    with pytest.raises(IngestionError, match='offsets'):
        list(QuasiLeakAdapter(manifest, tmp_path / 'raw').iter_documents('test'))


def test_group_mask_rate_is_a_distinct_conservative_proxy(source, tmp_path):
    _, row, manifest = source
    adapter = QuasiLeakAdapter(manifest, tmp_path / 'raw')
    document = next(adapter.iter_documents('test'))
    gold = list(adapter.iter_annotations('test'))
    def score(decisions):
        return group_mask_rate([{'doc_id': document.doc_id, 'decisions': decisions}],
                               {document.doc_id: gold}, {document.doc_id: document})
    assert score([])['value'] == 0
    assert score([{'start': 0, 'end': 8, 'action': 'SUPPRESS'}])['value'] == 0
    result = score([{'start': 0, 'end': 17, 'action': 'SUPPRESS'}])
    assert result['value'] == 1
    assert result['protocol'] == 'quasileak-mask-proxy-v1'
    assert 'pas P-GF1' in result['details']['limitation']


def test_official_scorer_requires_complete_predictions_and_frozen_sources(source, tmp_path, monkeypatch):
    root, _, _ = source
    dataset, manifest = root / 'quasileak_bench_data_full.jsonl', root / 'split_manifest.json'
    monkeypatch.setattr(quasileak_official, 'DATA_SHA256', hashlib.sha256(dataset.read_bytes()).hexdigest())
    monkeypatch.setattr(quasileak_official, 'SPLIT_SHA256', hashlib.sha256(manifest.read_bytes()).hexdigest())
    predictions = tmp_path / 'predictions.jsonl'
    predictions.write_text(json.dumps({'sample_id': 'test-1', 'evidence': [
        {'attribute': 'education', 'spans': [{'start': 0, 'end': 17}, {'start': 22, 'end': 39}]}]}) + '\n')
    result = quasileak_official.score_official(dataset, manifest, predictions, split='test')
    assert result['scores_0_100']['P-GF1'] == 100
    assert result['prediction_provenance'] == 'external-unverified'
    predictions.write_text(json.dumps({'sample_id': 'test-1', 'status': 'error'}) + '\n')
    with pytest.raises(ValueError, match='échouée'):
        quasileak_official.score_official(dataset, manifest, predictions, split='test')
    predictions.write_text('')
    with pytest.raises(ValueError, match='missing'):
        quasileak_official.score_official(dataset, manifest, predictions, split='test')
    dataset.write_text(dataset.read_text() + ' ')
    with pytest.raises(ValueError, match='release'):
        quasileak_official.score_official(dataset, manifest, predictions, split='test')


def test_local_parser_never_turns_bad_json_into_empty_evidence():
    assert parse_response('```json\n{"evidence": []}\n```') == {'evidence': []}
    with pytest.raises(ValueError):
        parse_response('{"evidence":')
    with pytest.raises(ValueError, match='dupliquée'):
        parse_response('{"evidence": [], "evidence": []}')


def test_local_predictor_and_official_score_without_network(source, tmp_path, monkeypatch):
    from anonymisation.llm.client import LlmCompletion
    from scripts import predict_quasileak_local as runner

    root, _, _ = source
    template = {'user': ('DOCUMENT\n\n```\nplaceholder\n```\n\nAUTHOR PROFILE\n\n'
                         '```json\n{}\n```\n\n* Hide: x\n* Keep: x\n* Neutral: x\n'),
                'messages': [{'role': 'system', 'content': 'Detector'}, {'role': 'user', 'content': 'placeholder'}]}
    (root / 'zero_shot_messages.json').write_text(json.dumps(template))
    monkeypatch.setattr(runner, 'DATA_SHA256', hashlib.sha256((root / 'quasileak_bench_data_full.jsonl').read_bytes()).hexdigest())
    monkeypatch.setattr(runner, 'SPLIT_SHA256', hashlib.sha256((root / 'split_manifest.json').read_bytes()).hexdigest())
    monkeypatch.setattr(runner, 'PROMPT_SHA256', hashlib.sha256((root / 'zero_shot_messages.json').read_bytes()).hexdigest())
    monkeypatch.setattr(runner.official, 'HERE', root)
    monkeypatch.setattr(quasileak_official, 'DATA_SHA256', runner.DATA_SHA256)
    monkeypatch.setattr(quasileak_official, 'SPLIT_SHA256', runner.SPLIT_SHA256)
    backend = SimpleNamespace(name='stub', kind='stub', model='stub')
    monkeypatch.setattr(runner, 'load_backends_config', lambda: SimpleNamespace(resolve=lambda name: backend))
    class FakeClient:
        def complete(self, prompt, **kwargs):
            assert 'TARGET CASE' in prompt and 'g1' not in prompt
            content = json.dumps({'evidence': [{'attribute': 'education', 'spans': [
                {'start': 0, 'end': 17}, {'start': 22, 'end': 39}]}]})
            kwargs['validate'](content)
            return LlmCompletion(content=content, backend='stub', model='stub', cached=False,
                                 finish_reason='stop', latency_ms=0)
    monkeypatch.setattr(runner.LlmClient, 'for_backend', lambda *args, **kwargs: FakeClient())
    selection = tmp_path / 'selected.json'
    selection.write_text(json.dumps(['test-1']))
    output = tmp_path / 'predictions.jsonl'
    assert runner.predict(root, selection, output, backend_name='stub') == 0
    scored = quasileak_official.score_official(root / 'quasileak_bench_data_full.jsonl', root / 'split_manifest.json',
                                              output, split='test', selection=selection)
    assert scored['scores_0_100']['P-GF1'] == 100
    assert scored['prediction_provenance'] == 'locked-local'
    output.write_text(output.read_text() + '\n')
    with pytest.raises(ValueError, match='modifiées'):
        quasileak_official.score_official(root / 'quasileak_bench_data_full.jsonl', root / 'split_manifest.json',
                                          output, split='test', selection=selection)


def test_ingest_predict_and_score_do_not_fabricate_official_group_predictions(source, tmp_path, monkeypatch):
    from anonymisation.cli import predict, score
    from anonymisation.datasets.ingest import ingest
    from anonymisation.datasets.manifest import load_manifest

    config = tmp_path / 'configs'
    config.mkdir()
    original = Path(__file__).resolve().parents[2] / 'configs/datasets/quasileak.yaml'
    text = original.read_text().replace('"2d70694af86ca0e5d4ca11df052be793b083fdcff66d02da9d9a659fb656ef5e"', 'null')
    (config / 'quasileak.yaml').write_text(text)
    loaded = load_manifest(config / 'quasileak.yaml')
    adapter = QuasiLeakAdapter(loaded.manifest, tmp_path / 'raw')
    pivot = tmp_path / 'processed'
    with pytest.raises(IngestionError, match='tronque chaque table'):
        ingest(adapter, loaded.manifest, split='test', limit=1, output_root=pivot)
    ingest(adapter, loaded.manifest, split='test', output_root=pivot, resolution=loaded.resolution)
    monkeypatch.setattr(predict, 'PROCESSED_ROOT', pivot)
    monkeypatch.setattr(predict, 'DATASETS_CONFIG', config)
    monkeypatch.setattr(score, 'PROCESSED_ROOT', pivot)
    monkeypatch.setattr(score, 'DATASETS_CONFIG', config)
    monkeypatch.setattr(predict, '_git_dirty', lambda root: False)
    root = tmp_path / 'QuasiLeak-Bench'
    monkeypatch.setattr(quasileak_official, 'DATA_SHA256',
                        hashlib.sha256((root / 'quasileak_bench_data_full.jsonl').read_bytes()).hexdigest())
    monkeypatch.setattr(quasileak_official, 'SPLIT_SHA256',
                        hashlib.sha256((root / 'split_manifest.json').read_bytes()).hexdigest())
    cards = {}
    for system in ('regex-only', 'oracle-mask'):
        run = tmp_path / system
        assert predict.cmd_predict('quasileak', 'test', None, 'deterministic', str(run), None, system=system) == 0
        assert score.cmd_score(run, 'quasileak-v1') == 0
        cards[system] = json.loads((run / 'scorecard.json').read_text())['diagnostic']
    regex, oracle = cards['regex-only'], cards['oracle-mask']
    assert regex['quasileak_group_mask_rate']['value'] == 0
    assert regex['quasileak_group_mask_rate']['details']['groups_total'] == 1
    # P-GF1 officiel via l'adaptateur D.8 : bornes 0 et 1, rappel pré-politique idem.
    assert (regex['quasileak_pgf1_d8']['value'], oracle['quasileak_pgf1_d8']['value']) == (0, 1)
    assert (regex['quasileak_er_pre_policy']['value'], oracle['quasileak_er_pre_policy']['value']) == (0, 1)
    assert oracle['quasileak_pgf1_d8']['protocol'] == 'quasileak-d8-span-adapter-v1'
    assert oracle['quasileak_pgf1_d8']['details']['attribute_table'] == 'strict'


def test_decision_export_groups_by_attribute_without_gold(tmp_path):
    from anonymisation.metrics.quasileak_export import category_to_attribute, export_run

    mapping = category_to_attribute({'education': SimpleNamespace(qi_categories=['GEN_EDUCATION']),
                                     'age': SimpleNamespace(qi_categories=['GEN_AGE'])})
    run = tmp_path / 'run'
    run.mkdir()
    decisions = [{'start': 22, 'end': 39, 'action': 'SUPPRESS', 'qi_category': 'GEN_EDUCATION'},
                 {'start': 0, 'end': 17, 'action': 'MASK', 'qi_category': 'GEN_EDUCATION'},
                 {'start': 40, 'end': 45, 'action': 'KEEP', 'qi_category': 'GEN_AGE'},
                 {'start': 50, 'end': 55, 'action': 'SUPPRESS', 'qi_category': 'DIR_EMAIL'}]
    rows = [{'doc_id': 'a', 'status': 'partial', 'decisions': decisions,
             'annotations': [{'meta': {'attribute': 'health'}}]},
            {'doc_id': 'b', 'status': 'ok', 'decisions': []}]
    (run / 'predictions.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    selection = tmp_path / 'ids.json'
    selection.write_text(json.dumps(['a', 'b']))
    out = tmp_path / 'groups.jsonl'
    lock = export_run(run, selection, out, mapping=mapping, dataset_sha256='d', split_sha256='s')
    exported = [json.loads(line) for line in out.read_text().splitlines()]
    assert exported == [{'sample_id': 'a', 'evidence': [{'attribute': 'education', 'spans': [
                            {'start': 0, 'end': 17}, {'start': 22, 'end': 39}]}]},
                        {'sample_id': 'b', 'evidence': []}]
    assert (lock['errors'], lock['groups'], lock['unmapped_decisions']) == (0, 1, 1)
    rows[1]['status'] = 'error'
    (run / 'predictions.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    assert export_run(run, selection, out, mapping=mapping, dataset_sha256='d', split_sha256='s')['errors'] == 1
    selection.write_text(json.dumps(['a']))
    with pytest.raises(ValueError, match='sélection'):
        export_run(run, selection, out, mapping=mapping, dataset_sha256='d', split_sha256='s')
    with pytest.raises(ValueError, match='rattaché'):
        category_to_attribute({'x': SimpleNamespace(qi_categories=['GEN_AGE']),
                               'y': SimpleNamespace(qi_categories=['GEN_AGE'])})


def test_d8_adapter_filters_by_supplied_policy_and_counts_pre_policy_spans(tmp_path):
    from anonymisation.metrics.quasileak_export import export_run, pre_policy_evidence_recall, pre_policy_inventory

    run = tmp_path / 'run'
    run.mkdir()
    disclosed = {'start': 0, 'end': 17, 'action': 'KEEP', 'qi_category': 'GEN_OCCUPATION',
                 'meta': {'disclosure': {'initial_action': 'SUPPRESS'}}}
    decisions = [disclosed, {'start': 22, 'end': 39, 'action': 'SUPPRESS', 'qi_category': 'GEN_EDUCATION'},
                 {'start': 40, 'end': 45, 'action': 'KEEP', 'qi_category': 'GEN_AGE'}]
    assert [d['action'] for d in pre_policy_inventory(decisions)] == ['SUPPRESS', 'SUPPRESS']
    (run / 'predictions.jsonl').write_text(json.dumps({'doc_id': 'a', 'status': 'ok', 'decisions': decisions}) + '\n')
    selection = tmp_path / 'ids.json'
    selection.write_text(json.dumps(['a']))
    mapping = {'GEN_OCCUPATION': 'occupation', 'GEN_EDUCATION': 'education'}
    out = tmp_path / 'groups.jsonl'
    lock = export_run(run, selection, out, mapping=mapping, dataset_sha256='d', split_sha256='s',
                      policies={'a': {'hide': ['education']}}, table='strict')
    assert json.loads(out.read_text())['evidence'] == [{'attribute': 'education',
                                                        'spans': [{'start': 22, 'end': 39}]}]
    assert (lock['groups'], lock['groups_filtered_by_policy'], lock['protocol']) == (
        1, 1, 'quasileak-d8-span-adapter-v1')
    # E_R pré-politique : le span remis en clair (occupation) compte encore dans l'inventaire.
    gold = {'sample_id': 'a', 'document': 'clinical rotation and four-year tuition xxxxx',
            'policy': {'hide': ['education']},
            'gold': {'groups': [{'attribute': 'education', 'cue_ids': ['s1', 's2']}],
                     'spans': [{'span_id': 's1', 'start': 0, 'end': 17}, {'span_id': 's2', 'start': 22, 'end': 39}]}}
    recall = pre_policy_evidence_recall(run, [gold])
    assert (recall['cues_found'], recall['cues_hide'], recall['value']) == (2, 2, 1.0)


def test_llm_grouping_never_invents_spans_and_hides_gold():
    from scripts.quasileak_llm_grouping import build_prompt, inventory, resolve

    row = {'document': 'clinical rotation and four-year tuition', 'profile': {'education': 'nursing'},
           'policy': {'hide': ['education'], 'keep': [], 'neutral': []},
           'gold': {'groups': [{'group_id': 'SECRET-GOLD'}]}}
    candidates = inventory([{'start': 22, 'end': 39, 'action': 'SUPPRESS', 'qi_category': 'X'},
                            {'start': 0, 'end': 17, 'action': 'MASK', 'qi_category': 'Y'},
                            {'start': 0, 'end': 17, 'action': 'SUPPRESS', 'qi_category': 'Z'}])
    assert candidates == [(0, 17), (22, 39)]
    prompt = build_prompt(row, candidates)
    assert 'SECRET-GOLD' not in prompt and '[1] "clinical rotation"' in prompt and 'nursing' in prompt
    groups = resolve([{'attribute': 'education', 'candidates': [1, 2]},
                      {'attribute': 'age', 'candidates': [1, 7]}, 'bad'], candidates)
    assert groups == [{'attribute': 'education', 'spans': [{'start': 0, 'end': 17}, {'start': 22, 'end': 39}]},
                      {'attribute': 'age', 'spans': []}, {'attribute': None, 'spans': []}]

from pathlib import Path

import pytest
import yaml

from anonymisation.datasets.manifest import load_manifest
from anonymisation.pipeline.traces import PipelineResult
from anonymisation.policy.disclosure import DisclosureError, Verdict, apply_disclosure, load_stage
from anonymisation.schema.models import Document, Domain
from anonymisation.transform.apply import apply_decisions
from anonymisation.transform.decisions import Action, AnonymizationDecision

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / 'configs/policy/disclosure.yaml'
TEXT = 'nurse aged 41 in Lyon, two kids'


def _decision(start, end, category, action=Action.SUPPRESS):
    return AnonymizationDecision(start=start, end=end, original=TEXT[start:end], action=action,
                                 replacement=f'[{category}]', qi_category=category, reason='test')


def _result(decisions, status='ok'):
    return PipelineResult(doc_id='d', original_text=TEXT, anonymized_text=apply_decisions(TEXT, decisions).anonymized_text,
                          annotations=(), decisions=tuple(decisions), risk=None, policy_id='', traces=(),
                          status=status)


def _doc(policy=None):
    meta = {} if policy is None else {'policy': policy}
    return Document(doc_id='d', dataset='quasileak', split='test', domain=Domain.GENERIC, text=TEXT, language='en', meta=meta)


POLICY = {'hide': ['age'], 'keep': ['occupation', 'gender', 'nationality', 'education'],
          'neutral': ['income', 'relationship', 'health']}
DECISIONS = [_decision(0, 5, 'GEN_OCCUPATION'), _decision(6, 13, 'GEN_AGE'),
             _decision(17, 21, 'GEN_GEO'), _decision(23, 31, 'GEN_FAMILY')]


def test_document_policy_keeps_keep_and_neutral_hides_hide_and_leaves_ungoverned():
    stage = load_stage('document', CONFIG)
    result, counts = apply_disclosure(_result(DECISIONS), _doc(POLICY), stage)
    actions = {d.qi_category: d.action for d in result.decisions}
    assert actions == {'GEN_OCCUPATION': Action.KEEP, 'GEN_AGE': Action.SUPPRESS,
                       'GEN_GEO': Action.SUPPRESS, 'GEN_FAMILY': Action.KEEP}
    assert result.anonymized_text == 'nurse [GEN_AGE] in [GEN_GEO], two kids'
    assert counts == {'KEEP': 1, 'HIDE': 1, 'UNGOVERNED': 1, 'NEUTRAL': 1, 'disclosed': 2}
    kept = next(d for d in result.decisions if d.qi_category == 'GEN_OCCUPATION')
    assert kept.meta['disclosure']['initial_action'] == 'SUPPRESS'
    # Offsets toujours sur le texte original.
    assert all(TEXT[d.start:d.end] == d.original for d in result.decisions)


def test_all_hide_control_is_a_no_op():
    original = _result(DECISIONS)
    result, counts = apply_disclosure(original, _doc(), load_stage('all-hide', CONFIG))
    assert result.decisions == original.decisions and result.anonymized_text == original.anonymized_text
    assert 'disclosed' not in counts


def test_missing_or_incomplete_policy_fails_loudly():
    stage = load_stage('document', CONFIG)
    with pytest.raises(DisclosureError, match='politique statique'):
        apply_disclosure(_result(DECISIONS), _doc(), stage)
    incomplete = {**POLICY, 'neutral': ['income']}
    with pytest.raises(DisclosureError, match='manquants'):
        apply_disclosure(_result(DECISIONS), _doc(incomplete), stage)
    with pytest.raises(DisclosureError, match='inconnue'):
        load_stage('absente', CONFIG)


def test_error_documents_untouched_and_free_rewrites_rejected():
    stage = load_stage('document', CONFIG)
    failed = _result(DECISIONS, status='error')
    assert apply_disclosure(failed, _doc(POLICY), stage)[0] is failed
    rewritten = _result(DECISIONS)
    rewritten = PipelineResult(**{**rewritten.__dict__, 'anonymized_text': 'réécrit librement'})
    with pytest.raises(DisclosureError, match='non reproductible'):
        apply_disclosure(rewritten, _doc(POLICY), stage)


def test_static_policy_requires_explicit_lists_and_neutral_action(tmp_path):
    data = yaml.safe_load(CONFIG.read_text())
    del data['policies']['all-hide']['neutral_action']
    path = tmp_path / 'disclosure.yaml'
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(DisclosureError, match='neutral_action'):
        load_stage('all-hide', path)


def test_attribute_table_matches_quasileak_manifest():
    data = yaml.safe_load(CONFIG.read_text())
    manifest = load_manifest(REPO / 'configs/datasets/quasileak.yaml', resolve_source=False).manifest
    assert {a: list(m.qi_categories) for a, m in manifest.label_map.items()} == data['attributes']


def test_verdict_vocabulary():
    policy = load_stage('document', CONFIG).policy_for(_doc(POLICY))
    assert policy.evaluate('GEN_AGE') is Verdict.HIDE
    assert policy.evaluate('DIR_EMAIL') is Verdict.UNGOVERNED

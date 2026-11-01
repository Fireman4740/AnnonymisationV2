"""Préparer et calibrer les jugements détaillés avec des évaluateurs humains.

L'export de revue peut contenir des données personnelles et reste explicite.
Le fichier de notes ne contient pas les textes. Aucun jugement humain n'est
fabriqué par ce programme.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from anonymisation.cli import score
from anonymisation.cli.evaluate import load_evaluation
from anonymisation.metrics.detailed_quality import QUESTION_METRICS
from anonymisation.schema.io import write_json

PROTOCOL = 'human-checklist-v1'


def _inputs(run):
    lock = score._read_json(run / score.LOCK_NAME)
    dataset, split = lock['run']['dataset'], lock['run']['split']
    inputs = score._verify_inputs(run, lock, dataset, split)
    predictions = score._read_predictions(run / score.PREDICTIONS_NAME)
    chosen = {p['doc_id']: p for p in predictions if p.get('status') in {'ok', 'partial'}}
    if not chosen or len(chosen) != sum(p.get('status') in {'ok', 'partial'} for p in predictions):
        raise ValueError('prédictions absentes ou dupliquées')
    if any(not isinstance(p.get('anonymized_text'), str) for p in chosen.values()):
        raise ValueError('texte anonymisé absent')
    return lock, inputs, chosen


def prepare(run, output, *, study_id, raters, review_out=None, readability_out=None, facts_out=None, facts_path=None):
    lock, _, predictions = _inputs(run)
    if not study_id.strip() or len(raters) < 2 or len(set(raters)) != len(raters) or any(not r.strip() for r in raters):
        raise ValueError('study_id et deux évaluateurs distincts requis')
    facts_by_doc = {}
    if facts_path is not None:
        from anonymisation.judge.detailed_quality import validate_facts
        docs, _ = score._load_gold(lock['run']['dataset'], lock['run']['split'])
        facts_by_doc = validate_facts(json.loads(facts_path.read_text(encoding='utf-8')), docs, predictions)
    rows = [{'doc_id': doc_id,
             'anonymized_sha256': hashlib.sha256(p['anonymized_text'].encode()).hexdigest(),
             'ratings': [{'rater': r, 'answers': {key: None for key in QUESTION_METRICS.values()},
                          'facts': {fact['id']: None for fact in facts_by_doc.get(doc_id, [])}}
                         for r in raters]} for doc_id, p in sorted(predictions.items())]
    write_json(output, {'protocol': PROTOCOL, 'study_id': study_id, 'rows': rows,
                        'fact_reference_sha256': hashlib.sha256(facts_path.read_bytes()).hexdigest() if facts_path else None})
    if readability_out is not None:
        write_json(readability_out, {'documents': [
            {'doc_id': doc_id, 'anonymized': predictions[doc_id]['anonymized_text']}
            for doc_id in sorted(predictions)]})
    if review_out is not None or facts_out is not None:
        docs, _ = score._load_gold(lock['run']['dataset'], lock['run']['split'])
        if not set(predictions) <= set(docs):
            raise ValueError('documents source manquants')
        if facts_out is not None:
            write_json(facts_out, {'protocol': 'nonprivate-facts-v1', 'study_id': study_id,
                'documents': [{'doc_id': doc_id, 'source_sha256': hashlib.sha256(docs[doc_id].text.encode()).hexdigest(),
                               'facts': []} for doc_id in sorted(predictions)]})
        if review_out is not None:
            write_json(review_out, {'sensitive_original_texts': True, 'documents': [
                {'doc_id': doc_id, 'original': docs[doc_id].text, 'anonymized': predictions[doc_id]['anonymized_text']}
                for doc_id in sorted(predictions)]})
    return len(rows)


def calibrate(run, ratings_path):
    lock, inputs, predictions = _inputs(run)
    evaluation = load_evaluation(run, lock, inputs, set(predictions))
    if not evaluation or 'detailed_quality' not in evaluation:
        raise ValueError('évaluation détaillée figée requise')
    data = json.loads(ratings_path.read_text(encoding='utf-8'))
    if data.get('protocol') != PROTOCOL or not isinstance(data.get('study_id'), str) or not data['study_id'].strip():
        raise ValueError('annotations humaines : protocole et study_id requis')
    if data.get('fact_reference_sha256') != evaluation['detailed_quality']['metadata'].get('fact_reference_sha256'):
        raise ValueError('annotations humaines : référence de faits différente')
    automatic = {r['doc_id']: r for r in evaluation['detailed_quality']['rows']}
    rows = data.get('rows')
    if not isinstance(rows, list) or len(rows) != len(predictions):
        raise ValueError('annotations humaines : couverture divergente')
    human = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'doc_id', 'anonymized_sha256', 'ratings'}:
            raise ValueError('annotations humaines : document invalide')
        doc_id = row['doc_id']
        if doc_id in human or doc_id not in predictions:
            raise ValueError('annotations humaines : document inconnu ou dupliqué')
        if row['anonymized_sha256'] != hashlib.sha256(predictions[doc_id]['anonymized_text'].encode()).hexdigest():
            raise ValueError('annotations humaines : texte anonymisé modifié')
        raters = row['ratings']
        if not isinstance(raters, list) or len(raters) < 2:
            raise ValueError('annotations humaines : deux évaluateurs requis')
        names = set()
        for r in raters:
            fact_ids = {f['id'] for f in automatic[doc_id].get('facts', [])}
            if (not isinstance(r, dict) or set(r) != {'rater', 'answers', 'facts'} or not isinstance(r['rater'], str)
                    or not r['rater'].strip() or r['rater'] in names or not isinstance(r['answers'], dict)
                    or set(r['answers']) != set(QUESTION_METRICS.values())
                    or any(v not in {'yes', 'no', 'na'} for v in r['answers'].values())
                    or not isinstance(r['facts'], dict)
                    or (automatic[doc_id].get('status') == 'ok' and set(r['facts']) != fact_ids)
                    or any(v not in {'preserved', 'omitted', 'contradicted', 'uncertain'} for v in r['facts'].values())):
                raise ValueError('annotations humaines : notes incomplètes ou évaluateur dupliqué')
            names.add(r['rater'])
        human[doc_id] = raters
    result = {}
    for key in QUESTION_METRICS.values():
        confusion = {'human_yes_judge_yes': 0, 'human_yes_judge_no': 0,
                     'human_no_judge_yes': 0, 'human_no_judge_no': 0}
        skipped = 0
        for doc_id, raters in human.items():
            votes = [r['answers'][key] for r in raters if r['answers'][key] != 'na']
            auto = automatic[doc_id]
            auto_votes = {c['answers'][key] for c in auto.get('chunks', []) if c['answers'][key] != 'na'}
            if len(votes) < 2 or votes.count('yes') == votes.count('no') or auto.get('status') != 'ok' or len(auto_votes) != 1:
                skipped += 1
                continue
            label = 'yes' if votes.count('yes') > votes.count('no') else 'no'
            confusion[f'human_{label}_judge_{next(iter(auto_votes))}'] += 1
        compared = sum(confusion.values())
        result[key] = {'confusion': confusion, 'compared': compared, 'excluded': skipped,
                       'agreement': (confusion['human_yes_judge_yes'] + confusion['human_no_judge_no']) / compared if compared else None}
    fact_labels = ('preserved', 'omitted', 'contradicted')
    fact_confusion = {f'human_{h}_judge_{j}': 0 for h in fact_labels for j in fact_labels}
    fact_excluded = 0
    for doc_id, raters in human.items():
        for item in automatic[doc_id].get('facts', []):
            votes = [r['facts'][item['id']] for r in raters if r['facts'][item['id']] != 'uncertain']
            counts = {label: votes.count(label) for label in fact_labels}
            majority = max(fact_labels, key=counts.get)
            if (automatic[doc_id].get('status') != 'ok' or item['verdict'] == 'uncertain'
                    or len(votes) < 2 or counts[majority] * 2 <= len(votes)):
                fact_excluded += 1
                continue
            fact_confusion[f"human_{majority}_judge_{item['verdict']}"] += 1
    fact_compared = sum(fact_confusion.values())
    fact_correct = sum(fact_confusion[f'human_{x}_judge_{x}'] for x in fact_labels)
    return {'protocol': 'checklist-human-agreement-v1', 'human_study_id': data['study_id'],
            'human_ratings_sha256': hashlib.sha256(ratings_path.read_bytes()).hexdigest(),
            'judge': evaluation['detailed_quality']['metadata']['judge'],
            'method': 'majorité humaine stricte parmi au moins deux notes applicables ; passages automatiques unanimes ; égalités exclues',
            'questions': result,
            'facts': {'confusion': fact_confusion, 'compared': fact_compared, 'excluded': fact_excluded,
                      'agreement': fact_correct / fact_compared if fact_compared else None}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--run', type=Path, required=True)
    prep.add_argument('--out', type=Path, required=True)
    prep.add_argument('--study-id', required=True)
    prep.add_argument('--raters', nargs='+', required=True)
    prep.add_argument('--review-out', type=Path)
    prep.add_argument('--readability-out', type=Path, help='Textes anonymisés seuls pour la lisibilité.')
    prep.add_argument('--facts-out', type=Path)
    prep.add_argument('--facts', type=Path, help='Référence de faits complétée et vérifiée.')
    cal = sub.add_parser('calibrate')
    cal.add_argument('--run', type=Path, required=True)
    cal.add_argument('--ratings', type=Path, required=True)
    cal.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare':
        count = prepare(args.run, args.out, study_id=args.study_id, raters=args.raters,
                        review_out=args.review_out, readability_out=args.readability_out,
                        facts_out=args.facts_out, facts_path=args.facts)
        print(f'{count} documents préparés ; annotations humaines à compléter.')
    else:
        write_json(args.out, calibrate(args.run, args.ratings))
        print('Calibration enregistrée.')


if __name__ == '__main__':
    main()

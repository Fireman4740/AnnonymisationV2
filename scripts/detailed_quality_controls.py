"""Préparer et évaluer des exemples dégradés pour calibrer le juge local.

Le fichier de cas contient des textes sources potentiellement personnels. Les
étiquettes attendues doivent être vérifiées par une personne avant évaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from anonymisation.cli import score
from anonymisation.judge.detailed_quality import freeze_detailed_quality, validate_facts
from anonymisation.metrics.detailed_quality import QUESTION_METRICS
from anonymisation.schema.io import write_json
from scripts.detailed_quality_human import _inputs

PROTOCOL = 'quality-controls-v1'


def prepare(run, facts_path, out):
    lock, _, predictions = _inputs(run)
    docs, _ = score._load_gold(lock['run']['dataset'], lock['run']['split'])
    reference = json.loads(facts_path.read_text(encoding='utf-8'))
    facts = validate_facts(reference, docs, predictions)
    cases = []
    for doc_id, entries in sorted(facts.items()):
        source = docs[doc_id].text
        for item in entries:
            start, end = item['start'], item['end']
            cases.append({'case_id': f'{doc_id}:{item["id"]}', 'source': source,
                'candidate': source[:start] + source[end:],
                'decisions': [{'start': start, 'end': end, 'original': source[start:end], 'replacement': '',
                    'action': 'SUPPRESS', 'qi_category': 'OTHER_QI', 'reason': 'contrôle synthétique'}],
                'facts': [item], 'expected_questions': {}, 'expected_facts': {},
                'reviewed': False})
    if not cases:
        raise ValueError('aucun fait à supprimer : compléter la référence')
    write_json(out, {'protocol': PROTOCOL, 'fact_reference_sha256': hashlib.sha256(facts_path.read_bytes()).hexdigest(),
                     'cases': cases})
    return len(cases)


def evaluate(path, *, backend, workers):
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('protocol') != PROTOCOL or not isinstance(data.get('cases'), list) or not data['cases']:
        raise ValueError('contrôles : protocole ou cas absents')
    docs, predictions, fact_docs, cases = {}, {}, [], {}
    for case in data['cases']:
        required = {'case_id', 'source', 'candidate', 'decisions', 'facts', 'expected_questions', 'expected_facts', 'reviewed'}
        if not isinstance(case, dict) or set(case) != required or case['reviewed'] is not True:
            raise ValueError('contrôles : tous les cas doivent être relus et complets')
        case_id, source, candidate = case['case_id'], case['source'], case['candidate']
        if (not isinstance(case_id, str) or not case_id or case_id in cases or not isinstance(source, str)
                or not source.strip() or not isinstance(candidate, str) or not isinstance(case['decisions'], list)
                or not isinstance(case['facts'], list) or not isinstance(case['expected_questions'], dict)
                or not isinstance(case['expected_facts'], dict)
                or not (case['expected_questions'] or case['expected_facts'])
                or set(case['expected_questions']) - set(QUESTION_METRICS.values())
                or any(v not in {'yes', 'no', 'na'} for v in case['expected_questions'].values())
                or any(v not in {'preserved', 'omitted', 'contradicted', 'uncertain'} for v in case['expected_facts'].values())
                or set(case['expected_facts']) - {f.get('id') for f in case['facts'] if isinstance(f, dict)}):
            raise ValueError('contrôles : cas ou attentes invalides')
        cases[case_id] = case
        docs[case_id] = SimpleNamespace(text=source)
        predictions[case_id] = {'anonymized_text': candidate, 'decisions': case['decisions']}
        fact_docs.append({'doc_id': case_id, 'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
                          'facts': case['facts']})
    frozen = freeze_detailed_quality(docs, predictions, backend_name=backend, workers=workers,
        facts_payload={'protocol': 'nonprivate-facts-v1', 'study_id': 'synthetic-controls', 'documents': fact_docs})
    question_counts, fact_counts = {'correct': 0, 'incorrect': 0, 'unavailable': 0}, {'correct': 0, 'incorrect': 0, 'unavailable': 0}
    for row in frozen['rows']:
        case = cases[row['doc_id']]
        facts = {f['id']: f['verdict'] for f in row.get('facts', [])}
        for q, expected in case['expected_questions'].items():
            values = {c['answers'][q] for c in row.get('chunks', [])}
            observed = next(iter(values)) if row['status'] == 'ok' and len(values) == 1 else None
            question_counts['unavailable' if observed is None else 'correct' if observed == expected else 'incorrect'] += 1
        for fid, expected in case['expected_facts'].items():
            observed = facts.get(fid) if row['status'] == 'ok' else None
            fact_counts['unavailable' if observed is None else 'correct' if observed == expected else 'incorrect'] += 1
    return {'protocol': 'quality-control-agreement-v1', 'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'judge': frozen['metadata']['judge'], 'cases': len(cases),
            'question_verdicts': question_counts, 'fact_verdicts': fact_counts,
            'case_errors': sum(row['status'] != 'ok' for row in frozen['rows']),
            'limitation': 'contrôles synthétiques relus ; ne remplacent pas une validation sur de vrais textes'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--run', type=Path, required=True)
    prep.add_argument('--facts', type=Path, required=True)
    prep.add_argument('--out', type=Path, required=True)
    assess = sub.add_parser('evaluate')
    assess.add_argument('--controls', type=Path, required=True)
    assess.add_argument('--backend', required=True)
    assess.add_argument('--workers', type=int, default=2)
    assess.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare':
        print(f'{prepare(args.run, args.facts, args.out)} contrôles générés ; revue humaine requise.')
    else:
        write_json(args.out, evaluate(args.controls, backend=args.backend, workers=args.workers))
        print('Évaluation des contrôles enregistrée.')


if __name__ == '__main__':
    main()

"""Agrégation hors ligne du juge détaillé et de références de faits externes."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from anonymisation.metrics.contracts import MetricDirection, MetricStatus, MetricValue
from anonymisation.metrics.uncertainty import bootstrap_interval, mean, with_interval

PROTOCOL = 'local-quality-checklist-v1'
QUESTION_METRICS = {
    'quality_understandable': 'read_understandable',
    'quality_grammar': 'read_grammar',
    'quality_references': 'read_references',
    'quality_main_information': 'relevance_main',
    'quality_no_contradiction': 'fidelity_contradiction',
    'quality_no_invention': 'fidelity_invention',
}
FACT_METRICS = {
    'quality_fact_retention': 'preserved',
    'quality_fact_omission': 'omitted',
    'quality_fact_contradiction': 'contradicted',
}
METRICS = frozenset((*QUESTION_METRICS, *FACT_METRICS, 'quality_errors_per_document'))


def _digest(values):
    return hashlib.sha256(json.dumps(sorted(values), ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def detailed_quality_metrics(rows: Sequence[Mapping[str, Any]], metadata: Mapping[str, Any]) -> dict[str, Any]:
    if metadata.get('protocol') != PROTOCOL or not isinstance(metadata.get('judge'), dict):
        raise ValueError('qualité détaillée : protocole ou juge manquant')
    seen, valid = set(), []
    for row in rows:
        doc_id, status = row.get('doc_id'), row.get('status')
        if not isinstance(doc_id, str) or doc_id in seen or status not in {'ok', 'error', 'control_failed'}:
            raise ValueError('qualité détaillée : document ou statut invalide')
        seen.add(doc_id)
        if status != 'ok':
            continue
        chunks, facts = row.get('chunks'), row.get('facts')
        if not isinstance(chunks, list) or not chunks or not isinstance(facts, list):
            raise ValueError('qualité détaillée : passages ou faits absents')
        for chunk in chunks:
            if (not isinstance(chunk, dict) or type(chunk.get('weight')) is not int or chunk['weight'] < 1
                    or type(chunk.get('invention_count')) is not int or chunk['invention_count'] < 0
                    or not isinstance(chunk.get('answers'), dict)
                    or set(chunk['answers']) != set(QUESTION_METRICS.values())
                    or any(v not in {'yes', 'no', 'na'} for v in chunk['answers'].values())):
                raise ValueError('qualité détaillée : réponses invalides')
        fact_ids = set()
        for fact in facts:
            if (not isinstance(fact, dict) or set(fact) != {'id', 'verdict'}
                    or not isinstance(fact['id'], str) or not fact['id'] or fact['id'] in fact_ids
                    or fact['verdict'] not in {'preserved', 'omitted', 'contradicted', 'uncertain'}):
                raise ValueError('qualité détaillée : verdict de fait invalide')
            fact_ids.add(fact['id'])
        valid.append(row)
    failed = len(rows) - len(valid)
    eligible = bool(valid) and failed / len(rows) <= .05
    base = {**metadata, 'documents_total': len(rows), 'documents_valid': len(valid),
            'control_failures': sum(r.get('status') == 'control_failed' for r in rows),
            'model_errors': sum(r.get('status') == 'error' for r in rows)}
    result = {}
    error_counts = [sum(c['invention_count'] for c in row['chunks']) for row in valid]
    error_value = mean(error_counts) if eligible else None
    error_details = {**base, 'detected_errors_total': sum(error_counts),
                     'denominator': 'documents valides',
                     'quality_applicability_sha256': _digest([row['doc_id'] for row in valid]),
                     'limitation': 'comptage par juge local de citations distinctes : inventions et contradictions confondues ; non exhaustif',
                     'reason': None if error_value is not None else 'contrôles/erreurs > 5 % ou aucun document valide'}
    error_block = MetricValue(name='quality_errors_per_document', value=error_value, protocol=PROTOCOL,
        protocol_version='1', status=MetricStatus.DIAGNOSTIC if error_value is not None else MetricStatus.UNAVAILABLE,
        direction=MetricDirection.MINIMIZE, unit='count', details=error_details).to_dict()
    result['quality_errors_per_document'] = with_interval(error_block,
        bootstrap_interval(error_counts, mean, unit='document') if error_value is not None else None)
    for name, question in QUESTION_METRICS.items():
        values, applicability = [], []
        applicable, total = 0, 0
        for row in valid:
            applicable_chunks = [c for c in row['chunks'] if c['answers'][question] != 'na']
            total += len(row['chunks'])
            applicable += len(applicable_chunks)
            if applicable_chunks:
                position, spans = 0, []
                for chunk in row['chunks']:
                    end = position + chunk['weight']
                    if chunk['answers'][question] != 'na':
                        if spans and spans[-1][1] == position:
                            spans[-1][1] = end
                        else:
                            spans.append([position, end])
                    position = end
                applicability.append((row['doc_id'], spans))
                values.append(sum(c['weight'] * (c['answers'][question] == 'yes') for c in applicable_chunks)
                              / sum(c['weight'] for c in applicable_chunks))
        value = mean(values) if eligible and values else None
        details = {**base, 'question_id': question, 'documents_applicable': len(values),
                   'quality_applicability_sha256': _digest(applicability),
                   'chunks_applicable': applicable, 'chunks_total': total,
                   'denominator': 'passages applicables pondérés par longueur, puis documents applicables',
                   'reason': None if value is not None else 'contrôles/erreurs > 5 % ou aucun passage applicable'}
        block = MetricValue(name=name, value=value, protocol=PROTOCOL, protocol_version='1',
            status=MetricStatus.DIAGNOSTIC if value is not None else MetricStatus.UNAVAILABLE,
            direction=MetricDirection.MAXIMIZE, details=details).to_dict()
        result[name] = with_interval(block, bootstrap_interval(values, mean, unit='document') if value is not None else None)
    for name, verdict in FACT_METRICS.items():
        counts = [{k: sum(f['verdict'] == k for f in row['facts'])
                   for k in ('preserved', 'omitted', 'contradicted', 'uncertain')} for row in valid]
        total = sum(sum(c[k] for k in ('preserved', 'omitted', 'contradicted')) for c in counts)
        numerator = sum(c[verdict] for c in counts)
        value = numerator / total if eligible and total else None
        def statistic(sample, target=verdict):
            denom = sum(sum(c[k] for k in ('preserved', 'omitted', 'contradicted')) for c in sample)
            return sum(c[target] for c in sample) / denom if denom else None
        details = {**base, 'fact_count_total': total + sum(c['uncertain'] for c in counts),
                   'quality_applicability_sha256': _digest([(row['doc_id'], fact['id']) for row in valid
                                                            for fact in row['facts'] if fact['verdict'] != 'uncertain']),
                   'fact_count_judged': total, 'fact_count_uncertain': sum(c['uncertain'] for c in counts),
                   'fact_count_matching': numerator, 'denominator': 'faits jugés, hors incertains',
                   'reason': None if value is not None else 'référence de faits absente, aucun fait jugé ou contrôles/erreurs > 5 %'}
        block = MetricValue(name=name, value=value, protocol=PROTOCOL, protocol_version='1',
            status=MetricStatus.DIAGNOSTIC if value is not None else MetricStatus.UNAVAILABLE,
            direction=MetricDirection.MAXIMIZE if verdict == 'preserved' else MetricDirection.MINIMIZE,
            details=details).to_dict()
        result[name] = with_interval(block, bootstrap_interval(counts, statistic, unit='document') if value is not None else None)
    return result

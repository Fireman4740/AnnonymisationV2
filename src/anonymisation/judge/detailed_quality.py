"""Évaluation locale décomposée, versionnée et distincte des notes globales.

Les questions fermées s'inspirent de BinEval (Cho et al., 2026). Les faits
optionnels sont fournis et vérifiés séparément ; aucun fait produit par le
juge n'est présenté comme une référence humaine.
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from anonymisation.judge.local_quality import (
    MAX_PROMPT_BYTES,
    SYSTEM,
    _aligned_chunks,
    _blind,
    _client,
    _complete,
)
from anonymisation.llm.config import load_backends_config
from anonymisation.pipelines.llm_contextual.system import assert_local_backend
from anonymisation.schema.io import sha256_file

PROTOCOL = 'local-quality-checklist-v1'
QUESTIONS = {
    'read_understandable': 'Le texte est-il globalement compréhensible ?',
    'read_grammar': 'Les phrases sont-elles grammaticalement compréhensibles ?',
    'read_references': 'Les références entre personnes ou objets restent-elles compréhensibles ?',
    'relevance_main': 'La fonction et les informations principales non privées sont-elles conservées ?',
    'fidelity_contradiction': 'Le texte évite-t-il de contredire les faits non privés de la source ?',
    'fidelity_invention': 'Le texte évite-t-il d’inventer des faits non privés absents de la source ?',
}
READ_KEYS = tuple(k for k in QUESTIONS if k.startswith('read_'))
PAIR_KEYS = tuple(k for k in QUESTIONS if not k.startswith('read_'))
READ_PROMPT = ('Évalue séparément chaque texte sans source. Réponds yes, no ou na par question. '
               'Pour un texte vide, read_understandable et read_grammar valent no. '
               'na signifie que la question ne s’applique pas, jamais une incertitude.\n')
PAIR_PROMPT = ('Compare chaque candidat à la source. Réponds yes, no ou na par question. '
               'La suppression ou généralisation d’une identité privée inutile n’est pas une erreur. '
               'Pour le candidat vide relevance_main vaut no. Le texte identique est fidèle. '
               'na signifie que la question ne s’applique pas, jamais une incertitude.\n')
FACT_PROMPT = ('Pour chaque fait non privé fourni, compare candidat et source. '
               'Réponds preserved, omitted, contradicted ou uncertain. '
               'Une généralisation compatible est preserved ; un manque de preuve est uncertain. '
               'Ne retourne aucun texte des documents.\n')
INVENTION_PROMPT = ('Pour chaque candidat, identifie les affirmations factuelles non privées inventées '
                    'ou contradictoires par rapport à la source. Ignore les noms remplacés et les '
                    'généralisations compatibles. Pour chaque erreur retourne une citation exacte '
                    'et distincte du candidat ; sans erreur retourne une liste vide.\n')


class StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)


class Verdict(StrictModel):
    question: str
    answer: Literal['yes', 'no', 'na']


class Candidate(StrictModel):
    id: Literal['A', 'B', 'C']
    answers: list[Verdict]


class Batch(StrictModel):
    items: list[Candidate] = Field(min_length=2, max_length=3)

    @model_validator(mode='after')
    def unique(self):
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError('candidats dupliqués')
        for item in self.items:
            if len({answer.question for answer in item.answers}) != len(item.answers):
                raise ValueError('questions dupliquées')
        return self


class FactVerdict(StrictModel):
    id: str
    verdict: Literal['preserved', 'omitted', 'contradicted', 'uncertain']


class FactBatch(StrictModel):
    facts: list[FactVerdict]


class InventionCandidate(StrictModel):
    id: Literal['A', 'B', 'C']
    quotes: list[str]


class InventionBatch(StrictModel):
    items: list[InventionCandidate] = Field(min_length=3, max_length=3)


def _answers(batch, labels, keys):
    if {item.id for item in batch.items} != set(labels):
        raise ValueError('candidats absents ou supplémentaires')
    out = {}
    for item in batch.items:
        answers = {v.question: v.answer for v in item.answers}
        if set(answers) != set(keys):
            raise ValueError('questions absentes ou supplémentaires')
        out[item.id] = answers
    return out


def _detailed_fits(doc_id, source, candidate):
    read_views, _ = _blind(doc_id, {'candidate': candidate, 'empty': ''})
    pair_views, _ = _blind(doc_id, {'candidate': candidate, 'empty': '', 'identity': source})
    read = READ_PROMPT + json.dumps({'questions': {k: QUESTIONS[k] for k in READ_KEYS},
        'texts': [{'id': k, 'text': v} for k, v in read_views.items()]}, ensure_ascii=False)
    candidates = [{'id': k, 'text': v} for k, v in pair_views.items()]
    pair = PAIR_PROMPT + json.dumps({'source': source, 'questions': {k: QUESTIONS[k] for k in PAIR_KEYS},
                                   'candidates': candidates}, ensure_ascii=False)
    invent = INVENTION_PROMPT + json.dumps({'source': source, 'candidates': candidates}, ensure_ascii=False)
    return max(len((SYSTEM + prompt).encode('utf-8')) for prompt in (read, pair, invent)) <= MAX_PROMPT_BYTES


def validate_facts(payload, documents, predictions):
    """Valide une référence externe non privée ancrée à la source exacte."""
    if not isinstance(payload, dict) or payload.get('protocol') != 'nonprivate-facts-v1':
        raise ValueError('faits : protocole nonprivate-facts-v1 requis')
    if not isinstance(payload.get('study_id'), str) or not payload['study_id'].strip():
        raise ValueError('faits : study_id requis')
    entries = payload.get('documents')
    if not isinstance(entries, list):
        raise ValueError('faits : documents requis')
    facts_by_doc = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'doc_id', 'source_sha256', 'facts'}:
            raise ValueError('faits : document mal formé')
        doc_id = entry['doc_id']
        if doc_id in facts_by_doc or doc_id not in predictions or doc_id not in documents:
            raise ValueError('faits : document dupliqué ou inconnu')
        source = documents[doc_id].text
        if entry['source_sha256'] != hashlib.sha256(source.encode()).hexdigest():
            raise ValueError('faits : source modifiée')
        if not isinstance(entry['facts'], list):
            raise ValueError('faits : liste requise')
        seen = set()
        for fact in entry['facts']:
            if not isinstance(fact, dict) or set(fact) != {'id', 'start', 'end', 'text'}:
                raise ValueError('faits : id, start, end et text requis')
            fid, start, end, text = fact['id'], fact['start'], fact['end'], fact['text']
            if (not isinstance(fid, str) or not fid.strip() or fid in seen
                    or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(source) or text != source[start:end]):
                raise ValueError('faits : référence dupliquée ou non ancrée')
            seen.add(fid)
        facts_by_doc[doc_id] = entry['facts']
    if set(facts_by_doc) != set(predictions):
        raise ValueError('faits : couverture des documents différente')
    return facts_by_doc


def _judge_chunk(doc_id, source, candidate, read_client, pair_client, invention_client):
    views, ids = _blind(doc_id, {'candidate': candidate, 'empty': ''})
    read_payload = {'questions': {k: QUESTIONS[k] for k in READ_KEYS},
                    'texts': [{'id': k, 'text': v} for k, v in views.items()]}
    read = _answers(_complete(read_client, READ_PROMPT + json.dumps(read_payload, ensure_ascii=False), Batch), views, READ_KEYS)
    views, pair_ids = _blind(doc_id, {'candidate': candidate, 'empty': '', 'identity': source})
    pair_payload = {'source': source, 'questions': {k: QUESTIONS[k] for k in PAIR_KEYS},
                    'candidates': [{'id': k, 'text': v} for k, v in views.items()]}
    pair = _answers(_complete(pair_client, PAIR_PROMPT + json.dumps(pair_payload, ensure_ascii=False), Batch), views, PAIR_KEYS)
    empty_read, empty_pair, identity = read[ids['empty']], pair[pair_ids['empty']], pair[pair_ids['identity']]
    invent = _complete(invention_client, INVENTION_PROMPT + json.dumps(
        {'source': source, 'candidates': [{'id': k, 'text': v} for k, v in views.items()]},
        ensure_ascii=False), InventionBatch)
    if len({x.id for x in invent.items}) != len(views) or {x.id for x in invent.items} != set(views):
        raise ValueError('erreurs factuelles : candidats absents ou dupliqués')
    inventions = {}
    for item in invent.items:
        if len(set(item.quotes)) != len(item.quotes) or any(len(q.strip()) < 4 or q not in views[item.id] for q in item.quotes):
            raise ValueError('erreur factuelle non ancrée ou dupliquée')
        inventions[item.id] = len(item.quotes)
    passed = (empty_read['read_understandable'] == 'no' and empty_read['read_grammar'] == 'no'
              and empty_pair['relevance_main'] == 'no'
              and all(v == 'yes' for v in identity.values())
              and inventions[pair_ids['empty']] == 0 and inventions[pair_ids['identity']] == 0
              and (candidate != source or inventions[pair_ids['candidate']] == 0)
              and (candidate != '' or inventions[pair_ids['candidate']] == 0))
    return {'answers': {**read[ids['candidate']], **pair[pair_ids['candidate']]}, 'control_passed': passed,
            'invention_count': inventions[pair_ids['candidate']]}


def assess_one(doc_id, source, candidate, decisions, facts, read_client, pair_client, fact_client, invention_client):
    from anonymisation.llm.client import LlmBackendUnavailableError, LlmEmptyResponseError
    from anonymisation.pipelines.llm_contextual.prompts import StructuredResponseError
    try:
        if not source.strip():
            raise ValueError('source vide')
        chunks = _aligned_chunks(doc_id, source, candidate, decisions, fits=_detailed_fits)
        judged = [_judge_chunk(f'{doc_id}:{i}', a, b, read_client, pair_client, invention_client)
                  for i, (a, b) in enumerate(chunks)]
        # Source facts are aligned to a single chunk; no guessed cross-boundary mapping.
        cursor, fact_results = 0, []
        for a, b in chunks:
            contained = [f for f in facts if cursor <= f['start'] and f['end'] <= cursor + len(a)]
            batches = []
            for f in contained:
                if not batches:
                    batches.append([])
                trial = batches[-1] + [{'id': f['id'], 'text': f['text']}]
                prompt = FACT_PROMPT + json.dumps({'source': a, 'candidate': b, 'facts': trial}, ensure_ascii=False)
                if len((SYSTEM + prompt).encode('utf-8')) > MAX_PROMPT_BYTES or len(trial) > 20:
                    if not batches[-1]:
                        raise ValueError('fait trop long pour le juge')
                    batches.append([{'id': f['id'], 'text': f['text']}])
                    prompt = FACT_PROMPT + json.dumps({'source': a, 'candidate': b, 'facts': batches[-1]}, ensure_ascii=False)
                    if len((SYSTEM + prompt).encode('utf-8')) > MAX_PROMPT_BYTES:
                        raise ValueError('fait trop long pour le juge')
                else:
                    batches[-1] = trial
            for batch in batches:
                data = {'source': a, 'candidate': b, 'facts': batch}
                result = _complete(fact_client, FACT_PROMPT + json.dumps(data, ensure_ascii=False), FactBatch)
                if len(result.facts) != len(batch) or {x.id for x in result.facts} != {x['id'] for x in batch}:
                    raise ValueError('faits : réponses absentes ou dupliquées')
                fact_results.extend({'id': x.id, 'verdict': x.verdict} for x in result.facts)
            cursor += len(a)
        judged_ids = {x['id'] for x in fact_results}
        fact_results.extend({'id': f['id'], 'verdict': 'uncertain'} for f in facts if f['id'] not in judged_ids)
        return {'doc_id': doc_id, 'status': 'ok' if all(x['control_passed'] for x in judged) else 'control_failed',
                'chunks': [{'weight': len(a), 'answers': x['answers'], 'invention_count': x['invention_count']}
                           for (a, _), x in zip(chunks, judged, strict=True)],
                'facts': fact_results}
    except (ValueError, StructuredResponseError, LlmEmptyResponseError, LlmBackendUnavailableError) as exc:
        return {'doc_id': doc_id, 'status': 'error', 'error': type(exc).__name__}


def freeze_detailed_quality(documents, predictions, *, backend_name, workers, facts_payload=None):
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 4:
        raise ValueError('qualité détaillée : workers doit être entre 1 et 4')
    if not predictions or set(predictions) - documents.keys():
        raise ValueError('qualité détaillée : documents manquants')
    facts = validate_facts(facts_payload, documents, predictions) if facts_payload is not None else {}
    cfg = load_backends_config()
    backend = cfg.resolve(backend_name)
    assert_local_backend(backend)
    read, pair, fact, invention = (_client(cfg, backend, Batch), _client(cfg, backend, Batch),
                                    _client(cfg, backend, FactBatch), _client(cfg, backend, InventionBatch))
    def task(doc_id):
        candidate = predictions[doc_id].get('anonymized_text')
        if not isinstance(candidate, str):
            return {'doc_id': doc_id, 'status': 'error', 'error': 'texte anonymisé absent'}
        return assess_one(doc_id, documents[doc_id].text, candidate, predictions[doc_id].get('decisions'),
                          facts.get(doc_id, []), read, pair, fact, invention)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(task, sorted(predictions)))
    return {'rows': rows, 'metadata': {'protocol': PROTOCOL,
        'judge': {'backend': backend.name, 'model': backend.model, 'temperature': 0.0,
                  'prompt_sha256': hashlib.sha256((SYSTEM + READ_PROMPT + PAIR_PROMPT + FACT_PROMPT + INVENTION_PROMPT + json.dumps(QUESTIONS, sort_keys=True)).encode()).hexdigest(),
                  'module_sha256': sha256_file(Path(__file__))},
        'fact_study_id': facts_payload.get('study_id') if facts_payload else None,
        'facts_available': facts_payload is not None,
        'limitation': 'juge local non calibré ; questions générales et inventaire externe distincts ; contexte long découpé'}}

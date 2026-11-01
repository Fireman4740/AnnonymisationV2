"""Détecteur Qwen local avec invite zéro-shot officielle QuasiLeak-Bench.

Ne pas exécuter contre une API distante. Les échecs sont écrits explicitement
et empêchent le scorer de les traiter comme des listes de groupes vides.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from anonymisation.llm.client import LlmClient, LlmError
from anonymisation.llm.config import load_backends_config
from anonymisation.metrics.quasileak_official import DATA_SHA256, SOURCE_COMMIT, SPLIT_SHA256
from anonymisation.metrics.vendor import quasileak_render as official
from anonymisation.pipelines.llm_contextual.system import assert_local_backend
from anonymisation.schema.io import atomic_write, sha256_file, write_json

RENDER_SHA256 = '86a98e19d920e0ea45bf1d366414fb8b2b661f01329cf4e7bac57e844b6d4735'
PROMPT_SHA256 = '0b78281e3ddb2216f108cbccdab88aea313107574c2e8543b28b221f1dca2806'


def parse_response(content):
    """Reprend la lecture objet/markdown du parseur officiel, sans inventer de groupe."""
    text = content.strip()
    if text.startswith('```'):
        match = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```', text, flags=re.S | re.I)
        if not match:
            raise ValueError('bloc JSON incomplet')
        text = match.group(1)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('clé JSON dupliquée')
            result[key] = value
        return result
    def reject(value):
        raise ValueError(f'constante JSON interdite : {value}')
    payload = json.loads(text, object_pairs_hook=unique, parse_constant=reject)
    if not isinstance(payload, dict) or not isinstance(payload.get('evidence'), list):
        raise ValueError('réponse sans liste evidence')
    return payload


def predict(root: Path, selection: Path, out: Path, *, backend_name: str, max_tokens: int = 8192):
    dataset, manifest, template = (root / 'quasileak_bench_data_full.jsonl', root / 'split_manifest.json',
                                   root / 'zero_shot_messages.json')
    checks = ((dataset, DATA_SHA256), (manifest, SPLIT_SHA256), (template, PROMPT_SHA256),
              (Path(official.__file__), RENDER_SHA256))
    if any(sha256_file(path) != expected for path, expected in checks):
        raise ValueError('source, invite ou renderer officiel modifié')
    ids = json.loads(selection.read_text(encoding='utf-8'))
    members = set(json.loads(manifest.read_text(encoding='utf-8'))['membership']['test'])
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 50 or not all(isinstance(x, str) for x in ids)
            or len(set(ids)) != len(ids) or set(ids) - members):
        raise ValueError('sélection : 1 à 50 identifiants uniques du test officiel requis')
    if not 1 <= max_tokens <= 32768:
        raise ValueError('max_tokens doit être compris entre 1 et 32768')
    cfg = load_backends_config()
    backend = cfg.resolve(backend_name)
    assert_local_backend(backend)
    client = LlmClient.for_backend(backend_name, config=cfg)
    rows = {r['sample_id']: r for r in official.read_jsonl(dataset) if r['sample_id'] in set(ids)}
    if set(rows) != set(ids):
        raise ValueError('sélection absente des données')
    # Une tentative interrompue ne doit jamais laisser un ancien fichier scoré.
    out.unlink(missing_ok=True)
    out.with_suffix(out.suffix + '.lock.json').unlink(missing_ok=True)
    official.HERE = root
    result = []
    for doc_id in ids:
        messages = official.render(rows[doc_id], shots=0)
        if len(messages) != 2 or [x['role'] for x in messages] != ['system', 'user']:
            raise ValueError('invite officielle zéro-shot inattendue')
        try:
            response = client.complete(messages[1]['content'], system=messages[0]['content'],
                                       temperature=0.0, max_tokens=max_tokens, validate=parse_response)
            item = {'sample_id': doc_id, 'evidence': parse_response(response.content)['evidence']}
        except (LlmError, ValueError) as exc:
            item = {'sample_id': doc_id, 'status': 'error', 'error': type(exc).__name__}
        result.append(item)
        with atomic_write(out) as stream:
            for row in result:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        print(f'QUASILEAK_PROGRESS {len(result)}/{len(ids)}', flush=True)
    failed = sum(x.get('status') == 'error' for x in result)
    write_json(out.with_suffix(out.suffix + '.lock.json'), {
        'protocol': 'quasileak-zero-shot-local-v1', 'source_commit': SOURCE_COMMIT,
        'dataset_sha256': DATA_SHA256, 'split_manifest_sha256': SPLIT_SHA256,
        'selection_sha256': sha256_file(selection), 'prompt_sha256': PROMPT_SHA256,
        'renderer_sha256': RENDER_SHA256, 'backend': backend.name, 'model': backend.model,
        'temperature': 0.0, 'max_tokens': max_tokens, 'shots': 0,
        'predictions_sha256': sha256_file(out), 'documents': len(ids), 'errors': failed})
    return failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--backend', default='qwen_local_box')
    parser.add_argument('--max-tokens', type=int, default=8192)
    args = parser.parse_args()
    raise SystemExit(1 if predict(args.root, args.selection, args.out, backend_name=args.backend,
                                  max_tokens=args.max_tokens) else 0)


if __name__ == '__main__':
    main()

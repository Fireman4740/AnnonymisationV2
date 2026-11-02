"""Sélection reproductible de profils distincts dans un split officiel QuasiLeak."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from anonymisation.metrics.quasileak_official import DATA_SHA256, SPLIT_SHA256
from anonymisation.schema.io import sha256_file, write_json


def select(root: Path, count: int, seed: int, split: str = 'test', exclude_ids: frozenset[str] = frozenset()):
    if type(count) is not int or not 1 <= count <= 50:
        raise ValueError('la sélection doit contenir entre 1 et 50 documents')
    data, manifest = root / 'quasileak_bench_data_full.jsonl', root / 'split_manifest.json'
    if sha256_file(data) != DATA_SHA256 or sha256_file(manifest) != SPLIT_SHA256:
        raise ValueError('source QuasiLeak non vérifiée')
    members = set(json.loads(manifest.read_text())['membership'][split])
    by_profile, ordered, excluded_profiles = {}, [], set()
    with data.open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if row['sample_id'] in exclude_ids:
                excluded_profiles.add(row['profile']['profile_id'])
    if len(excluded_profiles) != len(exclude_ids):
        raise ValueError('exclusion : identifiants inconnus ou plusieurs documents par profil')
    with data.open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            # Holdout : aucun profil commun avec une sélection déjà utilisée.
            if row['sample_id'] in members and row['profile']['profile_id'] not in excluded_profiles:
                by_profile.setdefault(row['profile']['profile_id'], []).append(row['sample_id'])
                ordered.append(row['sample_id'])
    if len(by_profile) < count:
        raise ValueError(f'nombre insuffisant de profils {split} distincts')
    rng = random.Random(seed)
    profiles = sorted(by_profile)
    selected = rng.sample(profiles, count)
    ids = {rng.choice(sorted(by_profile[profile])) for profile in selected}
    return [doc_id for doc_id in ordered if doc_id in ids]


def pivot_manifest(root: Path, selected, split: str = 'test'):
    import hashlib

    wanted = set(selected)
    rows = []
    with (root / 'quasileak_bench_data_full.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            item = json.loads(line)
            if item['sample_id'] in wanted:
                rows.append({'doc_id': item['sample_id'],
                             'text_sha256': hashlib.sha256(item['document'].encode()).hexdigest()})
    if [r['doc_id'] for r in rows] != selected:
        raise ValueError('ordre ou contenu de la sélection divergent')
    return {'datasets': {'quasileak': {split: rows}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--count', type=int, default=50)
    parser.add_argument('--seed', type=int, default=20261016)
    parser.add_argument('--split', choices=('train', 'validation', 'test'), default='test')
    parser.add_argument('--exclude-profiles-of', type=Path, help='Sélection JSON dont les profils sont exclus.')
    parser.add_argument('--pivot-out', type=Path, help='Manifeste optionnel pour anonv2 predict.')
    args = parser.parse_args()
    exclude = frozenset(json.loads(args.exclude_profiles_of.read_text())) if args.exclude_profiles_of else frozenset()
    items = select(args.root, args.count, args.seed, args.split, exclude)
    write_json(args.out, items)
    if args.pivot_out:
        write_json(args.pivot_out, pivot_manifest(args.root, items, args.split))
    print(f'{len(items)} documents {args.split}, chacun issu d’un profil distinct.')


if __name__ == '__main__':
    main()

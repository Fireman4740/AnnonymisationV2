"""Dérive une sous-cohorte figée de N documents par dataset depuis une sous-cohorte parente.

Méthode : budget réparti en tourniquet entre splits puis entre strates du
parent ; dans chaque strate, rang par sha256("graine:doc_id") ; ordre source
du parent conservé. Aucun pivot n'est relu : seules les lignes
{doc_id, text_sha256} du parent sont reprises. Les sous-cohortes 5 et 50
existantes ont été produites avant ce script et n'en sont pas reproductibles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from anonymisation.schema.io import sha256_file, write_json


def stratum_of(key: str, doc_id: str, strata: list[str]) -> str:
    if strata == ['all']:
        return 'all'
    # Strates explicites du parent : niveau RAT-Bench (L1..L3), source SPIA (TAB, PANORAMA).
    token = doc_id.split(':')[1].split('-')[0]
    if token not in strata:
        raise ValueError(f'{key} : strate introuvable pour {doc_id!r} (strates {strata})')
    return token


def round_robin(capacities: dict[str, int], budget: int) -> dict[str, int]:
    given = {name: 0 for name in capacities}
    while budget and any(given[n] < capacities[n] for n in capacities):
        for name in capacities:
            if budget and given[name] < capacities[name]:
                given[name] += 1
                budget -= 1
    return given


def derive(parent_path: Path, count: int, seed: str) -> dict:
    parent = json.loads(parent_path.read_text(encoding='utf-8'))
    datasets, stratification = {}, {}
    for key, splits in parent['datasets'].items():
        strata = {split: list(parent['stratification'][key][split]) for split in splits}
        split_budget = round_robin({s: len(rows) for s, rows in splits.items()},
                                   min(count, sum(len(r) for r in splits.values())))
        datasets[key], stratification[key] = {}, {}
        for split, rows in splits.items():
            groups: dict[str, list[dict]] = {name: [] for name in strata[split]}
            for row in rows:
                groups[stratum_of(key, row['doc_id'], strata[split])].append(row)
            budget = round_robin({n: len(g) for n, g in groups.items()}, split_budget[split])
            chosen = set()
            for name, group in groups.items():
                ranked = sorted(group, key=lambda r: hashlib.sha256(f'{seed}:{r["doc_id"]}'.encode()).hexdigest())
                chosen |= {r['doc_id'] for r in ranked[:budget[name]]}
            datasets[key][split] = [r for r in rows if r['doc_id'] in chosen]
            stratification[key][split] = {n: b for n, b in budget.items() if b}
    return {'datasets': datasets, 'documents_per_dataset': count,
            'parent_subset_sha256': sha256_file(parent_path), 'sampling_seed': seed, 'schema_version': '1',
            'selection': 'sha256 ranking within the frozen parent; round-robin budgets across splits and strata; '
                         'source order preserved',
            'source_cohort_id': parent['source_cohort_id'], 'source_manifest_sha256': parent['source_manifest_sha256'],
            'stratification': stratification}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--count', type=int, required=True)
    parser.add_argument('--seed', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    write_json(args.out, derive(args.parent, args.count, args.seed))
    print(f'sous-cohorte {args.count} écrite : {args.out}')


if __name__ == '__main__':
    main()

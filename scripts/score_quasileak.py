"""Score des groupes prédis avec le programme officiel QuasiLeak-Bench.

Exemple : python scripts/score_quasileak.py --root /cache/QuasiLeak-Bench
--predictions predictions.jsonl --split test --selection ids.json --out scores.json
"""
from __future__ import annotations

import argparse
from pathlib import Path

from anonymisation.metrics.quasileak_official import score_official
from anonymisation.schema.io import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--split', choices=('train', 'validation', 'test'), required=True)
    parser.add_argument('--selection', type=Path, help='JSON : liste explicite de sample_id du split.')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = score_official(args.root / 'quasileak_bench_data_full.jsonl', args.root / 'split_manifest.json',
                            args.predictions, split=args.split, selection=args.selection)
    write_json(args.out, result)
    print(f"QuasiLeak : {result['scores_0_100']['N_docs']} documents, statut {result['status']}.")


if __name__ == '__main__':
    main()

"""Acquiert la release officielle QuasiLeak-Bench v1.0.1, hors de Git."""
from __future__ import annotations

import argparse
import hashlib
import io
import tempfile
import urllib.request
import zipfile
from pathlib import Path

COMMIT = '75987cdf029fac5fecce160bea218b458ed46dbb'
BASE = f'https://raw.githubusercontent.com/Yufannnn/QuasiLeak-Bench/{COMMIT}/data/'
ZIP_SHA = '4d1fb4730776c949a5513cc9628fbd706a4d587ec6044cf59b489c06a77bc480'
FILES = {
    'quasileak_bench_data_full.jsonl': '9af4c3e4fc59f664d124448e81e514012b8608bfa3ee6ba0faba9c6b9b27a965',
    'split_manifest.json': '34bbb26ebde1096f8c71f457caa7e81b78080a6f11c3494df67a6ffda4e6fc4a',
    'zero_shot_messages.json': '0b78281e3ddb2216f108cbccdab88aea313107574c2e8543b28b221f1dca2806',
}


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def fetch(root: Path):
    target = root / 'QuasiLeak-Bench'
    if all((target / name).is_file() and _digest((target / name).read_bytes()) == digest
           for name, digest in FILES.items()):
        return target
    with urllib.request.urlopen(BASE + 'quasileak_bench_data.zip', timeout=120) as response:
        archive = response.read()
    if _digest(archive) != ZIP_SHA:
        raise ValueError('archive QuasiLeak : empreinte inattendue')
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        # Lecture ciblée : aucun chemin de l'archive n'est extrait directement.
        data = zf.read('quasileak_bench_data_full.jsonl')
    with urllib.request.urlopen(BASE + 'splits/split_manifest.json', timeout=60) as response:
        manifest = response.read()
    with urllib.request.urlopen(f'https://raw.githubusercontent.com/Yufannnn/QuasiLeak-Bench/{COMMIT}/prompts/zero_shot_messages.json', timeout=60) as response:
        prompt = response.read()
    outputs = {'quasileak_bench_data_full.jsonl': data, 'split_manifest.json': manifest,
               'zero_shot_messages.json': prompt}
    if any(_digest(outputs[name]) != digest for name, digest in FILES.items()):
        raise ValueError('données QuasiLeak : empreinte inattendue')
    target.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        with tempfile.NamedTemporaryFile(dir=target, delete=False) as tmp:
            tmp.write(content)
            temp = Path(tmp.name)
        temp.replace(target / name)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    print(f'Source QuasiLeak vérifiée : {fetch(args.root)}')


if __name__ == '__main__':
    main()

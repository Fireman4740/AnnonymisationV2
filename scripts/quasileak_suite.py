"""Suite QuasiLeak-Bench sur la sélection figée de 50 documents de test.

Deux tâches distinctes, rapportées séparément et jamais fusionnées :
1. anonymiseurs du banc → scorecard pivot `quasileak-v1` (diagnostic
   `quasileak_group_mask_rate`, proxy, pas P-GF1) ;
2. détecteur natif Qwen local, invite zéro-shot officielle → scorer officiel
   (P-GF1 etc., statut `sampled` : 50 documents, pas les 1 000 du test).
Toute erreur du détecteur natif bloque le score officiel (C3/C4).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from anonymisation.cli.main import main as cli
from anonymisation.schema.io import write_json

CONFIG = Path('configs/evaluation/quasileak_suite.json')
PROFILES = {'llm-windowed': 'llm_windowed', 'llm-anchored': 'llm_anchored'}


def command(args: list[str]) -> int:
    print('COMMAND', ' '.join(args), flush=True)
    return cli(args)


def _errors(path: Path) -> tuple[int, int]:
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    return sum(r.get('status') == 'error' for r in rows), len(rows)


def _anonymizers(cfg: dict, failures: list[str]) -> list[dict]:
    results = []
    for variant in cfg['systems']:
        system = variant['system']
        directory = Path('runs') / f'quasileak-{system}'
        args = ['predict', '--dataset', 'quasileak', '--split', 'test', '--system', system,
                '--profile', PROFILES.get(system, 'deterministic'), '--out', str(directory),
                '--selection-manifest', cfg['pivot_selection']]
        for name, value in sorted(variant.get('params', {}).items()):
            args += ['--param', f'{name}={value}']
        if command(args):
            failures.append(f'{system}:predict')
            continue
        code = command(['score', '--run', str(directory), '--protocol', 'quasileak-v1'])
        card_path = directory / 'scorecard.json'
        if code not in (0, 1) or not card_path.is_file():
            failures.append(f'{system}:score')
            continue
        card = json.loads(card_path.read_text(encoding='utf-8'))
        entry = {'system': system, 'publishable': card['publishable'],
                 'blockers': card['publication_blockers'],
                 'quasileak_group_mask_rate': card['diagnostic']['quasileak_group_mask_rate']}
        results.append(entry)
        print('QUASILEAK_ANONYMIZER', json.dumps(entry, ensure_ascii=False, sort_keys=True), flush=True)
    return results


def _native(cfg: dict, root: Path, failures: list[str]) -> dict | None:
    from predict_quasileak_local import predict

    out = Path('runs/quasileak-native/predictions.jsonl')
    out.parent.mkdir(parents=True, exist_ok=True)
    predict(root, Path(cfg['selection']), out, backend_name=cfg['detector_backend'],
            max_tokens=cfg['detector_max_tokens'])
    failed, total = _errors(out)
    if failed:
        # Le scorer officiel refuse toute ligne en erreur : rapporter, ne pas scorer.
        failures.append(f'native:errors={failed}/{total}')
        return {'errors': failed, 'documents': total}
    scores = Path('runs/quasileak-native/scores.json')
    if command(['quasileak-score', '--root', str(root), '--predictions', str(out), '--split', 'test',
                '--selection', cfg['selection'], '--out', str(scores)]):
        failures.append('native:score')
        return None
    result = json.loads(scores.read_text(encoding='utf-8'))
    print('QUASILEAK_OFFICIAL', json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return result


def run_suite() -> int:
    from fetch_quasileak import fetch

    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    root = fetch(Path(os.environ['ANONV2_V1_DATASETS']))
    if command(['datasets', 'ingest', 'quasileak', '--split', 'test']):
        return 2
    failures: list[str] = []
    summary = {'purpose': cfg['purpose'], 'documents': 50, 'status_note': 'sampled, 50/1000 test',
               'anonymizers': _anonymizers(cfg, failures),
               'native_detector': _native(cfg, root, failures), 'failures': failures}
    write_json(Path('runs/quasileak-summary.json'), summary)
    print('FINAL_SUMMARY', json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 1 if failures else 0

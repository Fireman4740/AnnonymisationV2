"""Suite QuasiLeak-Bench sur une sélection figée (validation ou test, ≤ 50 documents).

Trois mesures, rapportées séparément et jamais fusionnées :
1. anonymiseurs du banc → scorecard `quasileak-v1`, dont le P-GF1 officiel via
   l'adaptateur de l'annexe D.8 (`quasileak_pgf1_d8`) et l'E_R pré-politique ;
2. variante D.8 « + regroupement LLM » (reçoit le profil : rapportée à part) ;
3. détecteur natif Qwen, invite zéro-shot officielle (reçoit aussi le profil).
Toute erreur bloque le score officiel concerné (C3/C4). Sur validation, la
suite applique en plus la règle de décision de table écrite dans la config.
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


def _llm_grouping(cfg: dict, root: Path, directory: Path, failures: list[str], name: str) -> dict:
    from quasileak_llm_grouping import group_run

    from anonymisation.metrics import quasileak_official as official

    out = directory / 'quasileak_llm_groups.jsonl'
    lock = group_run(root, directory, Path(cfg['selection']), out, backend_name=cfg['grouping_backend'])
    if lock['errors']:
        failures.append(f'{name}:llm_grouping_errors={lock["errors"]}')
        return {'lock': lock, 'official': None}
    result = official.score_official(root / 'quasileak_bench_data_full.jsonl', root / 'split_manifest.json',
                                     out, split=cfg['split'], selection=Path(cfg['selection']))
    write_json(directory / 'quasileak_llm_grouping_official.json', result)
    return {'lock': lock, 'official': result, 'receives_profile': True}


def _anonymizers(cfg: dict, root: Path, failures: list[str]) -> list[dict]:
    results = []
    for variant in cfg['systems']:
        system, disclosure = variant['system'], variant.get('disclosure_policy')
        name = system + (f'+{disclosure}' if disclosure else '')
        directory = Path('runs') / f'quasileak-{cfg["split"]}-{name}'
        args = ['predict', '--dataset', 'quasileak', '--split', cfg['split'], '--system', system,
                '--profile', PROFILES.get(system, 'deterministic'), '--out', str(directory),
                '--selection-manifest', cfg['pivot_selection']]
        if disclosure:
            args += ['--disclosure-policy', disclosure]
        for param, value in sorted(variant.get('params', {}).items()):
            args += ['--param', f'{param}={value}']
        if command(args):
            failures.append(f'{name}:predict')
            continue
        code = command(['score', '--run', str(directory), '--protocol', 'quasileak-v1'])
        card_path = directory / 'scorecard.json'
        if code not in (0, 1) or not card_path.is_file():
            failures.append(f'{name}:score')
            continue
        card = json.loads(card_path.read_text(encoding='utf-8'))
        diagnostic = card['diagnostic']
        entry = {'system': name, 'publishable': card['publishable'], 'blockers': card['publication_blockers'],
                 'disclosure': json.loads((directory / 'manifest.lock.json').read_text())['disclosure'],
                 **{k: diagnostic[k] for k in ('quasileak_group_mask_rate', 'quasileak_pgf1_d8',
                                               'quasileak_er_pre_policy')}}
        if diagnostic['quasileak_pgf1_d8']['value'] is None:
            failures.append(f'{name}:pgf1_d8_unavailable')
        if variant.get('llm_grouping'):
            try:
                entry['d8_llm_grouping'] = _llm_grouping(cfg, root, directory, failures, name)
            except (OSError, ValueError, KeyError) as exc:
                failures.append(f'{name}:llm_grouping')
                entry['d8_llm_grouping'] = {'error': f'{type(exc).__name__}: {exc}'}
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
    if command(['quasileak-score', '--root', str(root), '--predictions', str(out), '--split', cfg['split'],
                '--selection', cfg['selection'], '--out', str(scores)]):
        failures.append('native:score')
        return None
    result = json.loads(scores.read_text(encoding='utf-8'))
    print('QUASILEAK_OFFICIAL', json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return result


def table_decision(cfg: dict, anonymizers: list[dict]) -> dict | None:
    """Applique la règle de choix de table fixée dans la config avant le run."""
    rule = cfg.get('table_decision_rule')
    if rule is None:
        return None
    by_name = {a['system']: a['quasileak_pgf1_d8']['value'] for a in anonymizers}
    comparisons = []
    for system in rule['systems']:
        baseline = by_name.get(f"{system}+{rule['baseline_policy']}")
        candidate = by_name.get(f"{system}+{rule['candidate_policy']}")
        if baseline is None or candidate is None:
            raise ValueError(f'règle de table : scores manquants pour {system}')
        comparisons.append({'system': system, 'baseline': baseline, 'candidate': candidate,
                            'candidate_not_worse': candidate >= baseline})
    adopt = all(c['candidate_not_worse'] for c in comparisons)
    return {'rule': rule, 'comparisons': comparisons,
            'selected_table': rule['candidate_table'] if adopt else rule['baseline_table']}


def run_suite() -> int:
    from fetch_quasileak import fetch

    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    root = fetch(Path(os.environ['ANONV2_V1_DATASETS']))
    if command(['datasets', 'ingest', 'quasileak', '--split', cfg['split']]):
        return 2
    failures: list[str] = []
    anonymizers = _anonymizers(cfg, root, failures)
    native = _native(cfg, root, failures) if cfg.get('native_detector') else None
    summary = {'purpose': cfg['purpose'], 'split': cfg['split'], 'status_note': 'sampled',
               'documents': len(json.loads(Path(cfg['selection']).read_text(encoding='utf-8'))),
               'anonymizers': anonymizers, 'native_detector': native,
               'table_decision': None if failures else table_decision(cfg, anonymizers), 'failures': failures}
    write_json(Path(f"runs/quasileak-{cfg['split']}-summary.json"), summary)
    print('FINAL_SUMMARY', json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 1 if failures else 0

"""Attend que le serveur Qwen partagé ait de la capacité pour le pilote."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

METRICS_URL = 'http://127.0.0.1:18020/metrics'


def parse_metrics(content: str) -> dict[str,float]:
    values = {}
    for key in ('num_requests_running', 'num_requests_waiting', 'kv_cache_usage_perc'):
        found = re.findall(r'^vllm:' + key + r'(?:\{[^\n]*\})?\s+([0-9.eE+-]+)\s*$',content,re.MULTILINE)
        if not found:
            raise ValueError(f'métrique serveur absente : {key}')
        nums = [float(x) for x in found]
        values[key] = max(nums) if key == 'kv_cache_usage_perc' else sum(nums)
    return values


def admissible(values: dict[str,float], settings: dict) -> bool:
    return (values['num_requests_running'] <= settings['max_running']
            and values['num_requests_waiting'] <= settings['max_queued']
            and values['kv_cache_usage_perc'] <= settings['max_kv_usage'])


def main() -> None:
    settings = json.loads(Path('configs/evaluation/campaign.json').read_text())['qwen_admission']
    if not 1 <= settings['poll_s'] <= 60 or settings['max_wait_s'] < 1:
        raise ValueError('qwen_admission : délais invalides')
    deadline = time.monotonic() + settings['max_wait_s']
    while True:
        try:
            with urllib.request.urlopen(METRICS_URL,timeout=5) as response:
                values = parse_metrics(response.read().decode())
            print('QWEN_ADMISSION', json.dumps({'metrics':values,'ready':admissible(values,settings)},sort_keys=True),flush=True)
            if admissible(values,settings):
                return
        except (OSError,ValueError,urllib.error.URLError) as exc:
            print('QWEN_ADMISSION',json.dumps({'ready':False,'error':type(exc).__name__}),flush=True)
        if time.monotonic() >= deadline:
            raise RuntimeError('serveur Qwen indisponible ou saturé après le délai d’attente ; aucune campagne modèle lancée')
        time.sleep(settings['poll_s'])


if __name__ == '__main__':
    main()

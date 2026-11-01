"""Attend que le serveur Qwen partagé ait de la capacité pour le pilote."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from anonymisation.llm.config import load_backends_config

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


def fetch_metrics(api_key: str | None) -> dict[str, float]:
    """La clé reste en mémoire et n'est envoyée qu'au serveur local."""
    headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
    request = urllib.request.Request(METRICS_URL, headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        return parse_metrics(response.read().decode())


def main() -> None:
    campaign = json.loads(Path('configs/evaluation/campaign.json').read_text())
    settings = campaign['qwen_admission']
    if not 1 <= settings['poll_s'] <= 60 or settings['max_wait_s'] < 1:
        raise ValueError('qwen_admission : délais invalides')
    api_key = load_backends_config().resolve(campaign['anonymizer_backend']).resolve_api_key()
    deadline = time.monotonic() + settings['max_wait_s']
    while True:
        try:
            values = fetch_metrics(api_key)
            print('QWEN_ADMISSION', json.dumps({'metrics':values,'ready':admissible(values,settings)},sort_keys=True),flush=True)
            if admissible(values,settings):
                return
        except urllib.error.HTTPError as exc:
            print('QWEN_ADMISSION', json.dumps({'ready':False,'error':'HTTPError','status':exc.code}),flush=True)
            if exc.code in (401, 403):
                raise RuntimeError('accès aux métriques Qwen refusé : vérifier la clé API locale') from exc
        except (OSError,ValueError,urllib.error.URLError) as exc:
            print('QWEN_ADMISSION',json.dumps({'ready':False,'error':type(exc).__name__}),flush=True)
        if time.monotonic() >= deadline:
            raise RuntimeError('serveur Qwen indisponible ou saturé après le délai d’attente ; aucune campagne modèle lancée')
        time.sleep(settings['poll_s'])


if __name__ == '__main__':
    main()

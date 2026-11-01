"""La campagne n'ajoute pas de requête à une file saturée."""
import json
import urllib.error
from types import SimpleNamespace

import pytest

from scripts import wait_local_qwen
from scripts.wait_local_qwen import admissible, fetch_metrics, parse_metrics


def test_admission_waits_for_queue_and_kv_capacity():
    values = parse_metrics('vllm:num_requests_running{engine="0"} 3\n'
        'vllm:num_requests_waiting{engine="0"} 61\n'
        'vllm:kv_cache_usage_perc{engine="0"} 0.91\n')
    settings={'max_running':4,'max_queued':2,'max_kv_usage':0.8}
    assert not admissible(values,settings)
    values['num_requests_waiting']=0
    values['kv_cache_usage_perc']=0.5
    assert admissible(values,settings)


def test_missing_metrics_never_assume_server_is_ready():
    with pytest.raises(ValueError,match='absente'):
        parse_metrics('vllm:num_requests_running 0\n')


def test_metrics_request_uses_local_bearer_token_without_logging_it(monkeypatch, capsys):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return (b'vllm:num_requests_running 0\n'
                    b'vllm:num_requests_waiting 0\n'
                    b'vllm:kv_cache_usage_perc 0\n')

    def open_request(request, timeout):
        assert request.full_url == 'http://127.0.0.1:18020/metrics'
        assert request.get_header('Authorization') == 'Bearer test-secret'
        assert timeout == 5
        return Response()

    monkeypatch.setattr('urllib.request.urlopen', open_request)
    assert fetch_metrics('test-secret')['num_requests_waiting'] == 0
    assert 'test-secret' not in capsys.readouterr().out


def test_authentication_failure_is_reported_immediately(monkeypatch, tmp_path, capsys):
    config = tmp_path / 'configs/evaluation/campaign.json'
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({'anonymizer_backend':'qwen_local_box',
        'qwen_admission':{'poll_s':30, 'max_wait_s':86400}}))
    monkeypatch.chdir(tmp_path)
    backend = SimpleNamespace(resolve_api_key=lambda: 'test-secret')
    monkeypatch.setattr(wait_local_qwen, 'load_backends_config',
                        lambda: SimpleNamespace(resolve=lambda name: backend))
    def reject(_key):
        raise urllib.error.HTTPError('http://127.0.0.1:18020/metrics', 401, 'Unauthorized', {}, None)
    monkeypatch.setattr(wait_local_qwen, 'fetch_metrics', reject)
    with pytest.raises(RuntimeError, match='clé API'):
        wait_local_qwen.main()
    assert 'test-secret' not in capsys.readouterr().out

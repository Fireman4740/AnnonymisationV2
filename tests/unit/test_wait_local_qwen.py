"""La campagne n'ajoute pas de requête à une file saturée."""
import pytest

from scripts.wait_local_qwen import admissible, parse_metrics


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

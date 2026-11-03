import importlib.util
import json
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts/evaluation_smoke.py"
_SPEC = importlib.util.spec_from_file_location("evaluation_smoke", _PATH)
smoke = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(smoke)


def test_committed_selector_is_valid():
    assert json.loads((_PATH.parents[1] / "configs/evaluation/active_suite.json").read_text())["suite"] in smoke.SUITES


def test_selector_never_guesses(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "ACTIVE_SUITE", tmp_path / "active_suite.json")
    with pytest.raises(SystemExit, match="illisible"):
        smoke.active_suite()
    (tmp_path / "active_suite.json").write_text('{"suite": "autre"}')
    with pytest.raises(SystemExit, match="inconnue"):
        smoke.active_suite()
    (tmp_path / "active_suite.json").write_text('{"suite": "campaign"}')
    assert smoke.active_suite() == "campaign"

"""Le lock de ``predict`` fige le modèle, les prompts et les paramètres réels (H-0).

Avant correctif, ``models`` et ``prompts`` étaient écrits en dur à ``[]`` : un
run ``llm-full`` publiait une reproductibilité « sans modèle ni prompt », et
seule l'empreinte des paramètres (pas leurs valeurs) était conservée.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from anonymisation.cli import predict
from anonymisation.pipelines.llm_full.system import LlmFullSystem
from anonymisation.systems import SystemConfig, resolve_system


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_llm_system_lock_records_model_prompt_digest_and_params() -> None:
    pipe = LlmFullSystem(SystemConfig(
        params={"backend": "stub", "max_output_tokens": 8192}, repo_root=predict.REPO_ROOT,
    ))

    block = predict._system_reproducibility(pipe)

    assert block["models"] == [m.to_dict() for m in pipe.models()]
    assert block["models"][0]["name"]
    prompt_file = Path(predict.REPO_ROOT, "src/anonymisation/pipelines/llm_full/prompts.py")
    assert block["prompts"] == [{
        "ref": "anonymisation.pipelines.llm_full.prompts:build_anonymization_prompt",
        "sha256": _sha(prompt_file),
    }]
    assert block["params"]["backend"] == "stub"
    assert block["params"]["max_output_tokens"] == 8192
    assert block["llm_config"]["sha256"] == _sha(predict.REPO_ROOT / "configs/llm/backends.yaml")


def test_offline_system_lock_declares_no_model_and_no_llm_config() -> None:
    system_cls = resolve_system("passthrough")
    pipe = system_cls(system_cls.contract_config())

    block = predict._system_reproducibility(pipe)

    assert block["models"] == [] and block["prompts"] == []
    assert block["params"] == {}
    assert "llm_config" not in block

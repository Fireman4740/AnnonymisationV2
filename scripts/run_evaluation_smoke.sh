#!/usr/bin/env bash
# Contrat fixe : acquisition RAT-Bench, campagne multi-corpus et scoring hors ligne.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
  echo 'uv absent : utiliser un environnement vérifié ; ce contrat exige uv.lock.' >&2
  exit 2
fi
export ANONV2_V1_DATASETS="${ANONV2_V1_DATASETS:-$HOME/.cache/anonymisation-v2/datasets}"
export ANONV2_LLM_CACHE_DIR="${ANONV2_LLM_CACHE_DIR:-$HOME/.cache/anonymisation-v2/llm}"
uv run --isolated --no-project --with huggingface-hub --with gdown --with pandas --with pyarrow \
  python scripts/fetch_ratbench.py --root "$ANONV2_V1_DATASETS"
# `tab_eval` : évaluateur TAB ORIGINAL (spaCy + en_core_web_md épinglés).
uv sync --locked --python 3.11 --extra datasets --extra metrics --extra attack --extra tab_eval
uv run --locked --extra datasets --extra metrics --extra attack --extra tab_eval \
  python -m anonymisation.pipelines.llm_anchored.preflight
uv run --locked --extra datasets --extra metrics --extra attack --extra tab_eval \
  python scripts/evaluation_smoke.py

#!/usr/bin/env bash
# Contrat fixe : acquisition officielle, deux ancres, attaque et juge gratuits.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
  echo 'uv absent : utiliser un environnement vérifié ; ce contrat exige uv.lock.' >&2
  exit 2
fi
export ANONV2_V1_DATASETS="${ANONV2_V1_DATASETS:-$HOME/.cache/anonymisation-v2/datasets}"
uv run --isolated --no-project --with huggingface-hub --with gdown --with pandas --with pyarrow \
  python scripts/fetch_ratbench.py --root "$ANONV2_V1_DATASETS"
uv sync --locked --python 3.11 --extra datasets --extra metrics --extra attack
uv run --locked --extra datasets --extra metrics --extra attack python scripts/evaluation_smoke.py

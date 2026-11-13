#!/usr/bin/env bash
# Job: the wrong cases of the shipped file at the shipped setting, with their readings (WSL).
set -euo pipefail
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
python3 scripts/lm-domain/dump_errors.py --shim "$HOME/lmdom/bin/libduo_shim.so" --lm "$HOME/lmdom/bin/lm_score" \
  --model "$HOME/lmft/models/smollm2-lora-seed1.Q4_K_M.gguf" --result build/lm-domain/results/ship --rule shipped \
  --data build/lm-domain/data --sets dev github_select --out build/lm-domain/audit/ship-errors.jsonl

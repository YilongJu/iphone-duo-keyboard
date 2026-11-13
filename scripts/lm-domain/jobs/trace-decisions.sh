#!/usr/bin/env bash
# Job: the corrections of some scored arms on the selection sets, for the parity study (WSL).
# Usage: trace-decisions.sh ARM=MODEL_FILE [ARM=MODEL_FILE ...]
set -euo pipefail
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
for pair in "$@"; do
  arm="${pair%%=*}"; model="${pair#*=}"; model="${model/#\~/$HOME}"
  if [ -f "build/lm-domain/parity-study/$arm/corrections.jsonl.gz" ]; then continue; fi
  python3 scripts/lm-domain/trace_decisions.py --shim "$HOME/lmdom/bin/libduo_shim.so" --lm "$HOME/lmdom/bin/lm_score" \
    --model "$model" --result "build/lm-domain/results/$arm" --data build/lm-domain/data --out "build/lm-domain/parity-study/$arm"
done

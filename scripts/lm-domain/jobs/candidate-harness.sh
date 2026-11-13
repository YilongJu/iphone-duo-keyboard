#!/usr/bin/env bash
# Job: types the dev cases through the harness of the keyboard workflow with the candidate file
# at its own setting (WSL). check_candidate_harness.py pins the counts of this run.
set -euo pipefail
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
nice -n 10 python3 scripts/lm-keyboard/harness_trace.py --shim "$HOME/lmdom/bin/libduo_shim.so" --lm "$HOME/lmdom/bin/lm_score" \
  --model "$HOME/lmdom/models/dom-s100-seed1.Q4_K_M.gguf" --out build/lm-domain/candidate-harness --setting 1.5 1 4 2 1 --lead 0.5

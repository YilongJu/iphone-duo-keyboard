#!/usr/bin/env bash
# Runs eval_extra.py in WSL at the lowest priority, for one arm that evaluate.py has finished.
# Usage, inside WSL: eval_extra.sh OUT_NAME RUN_DIR MODEL_PATH THREADS [eval_extra.py options ...]
#   RUN_DIR holds result.json and lm-scores.jsonl of evaluate.py. The output goes to
#   ~/lmedit/extra/OUT_NAME.
set -euo pipefail
out_name="$1"; run_dir="$2"; model="$3"; threads="$4"; shift 4
here="$(cd "$(dirname "$0")" && pwd)"
finetune_root=/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune
out="$HOME/lmedit/extra/$out_name"
mkdir -p "$out"
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib" PYTHONDONTWRITEBYTECODE=1
nice -n 19 python3 -B "$here/eval_extra.py" --finetune "$finetune_root" --shim "$HOME/lmft/bin/libduo_shim.so" \
  --lm "$HOME/lmft/bin/lm_score" --model "$model" --threads "$threads" --run "$run_dir" --out "$out" "$@" \
  > "$out/extra.log" 2>&1
grep -E '^(tuned|common|weight candidate)' "$out/extra.log" | cut -c1-300

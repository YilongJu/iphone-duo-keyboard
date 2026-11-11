#!/usr/bin/env bash
# Scores one converted arm with evaluate.py of the fine-tune, in WSL at the lowest priority: the
# tuning split picks the setting, then dev scores the arm at that setting. The dev grid is
# skipped, because dev picks nothing in docs/lm-weight-edit-design.md.
# Usage, inside WSL: eval_edit.sh NAME MODEL_FILE THREADS
#   MODEL_FILE is a file under ~/lmedit/models.
set -euo pipefail
name="$1"; model="$2"; threads="$3"
finetune_root=/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib" PYTHONDONTWRITEBYTECODE=1
mkdir -p "$HOME/lmedit/results"
nice -n 19 python3 -B "$finetune_root/scripts/lm-finetune/evaluate.py" --shim "$HOME/lmft/bin/libduo_shim.so" \
  --lm "$HOME/lmft/bin/lm_score" --model "$HOME/lmedit/models/$model" --prompt-format typed \
  --threads "$threads" --data "$finetune_root/build/lm-finetune/data" --skip-dev-grid \
  --name "$name" --out "$HOME/lmedit/results/$name" > "$HOME/lmedit/results/$name.log" 2>&1
grep -E '^(control|tuned)' "$HOME/lmedit/results/$name.log"

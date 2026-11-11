#!/usr/bin/env bash
# Reads the held-out set of the second fine-tuning round once, with its read_holdout.py, for the
# arms of holdout-plan.json. It runs from that round's worktree and writes only to ~/lmedit/holdout.
# Usage, inside WSL: read_holdout.sh WORKERS
set -euo pipefail
workers="$1"
edit_root=/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit
cd /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune2
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib" PYTHONDONTWRITEBYTECODE=1
mkdir -p "$HOME/lmedit"
nice -n 19 python3 -B scripts/lm-finetune2/read_holdout.py --plan "$edit_root/scripts/lm-weight-edit/holdout-plan.json" \
  --shim "$HOME/lmft/bin/libduo_shim.so" --lm "$HOME/lmft/bin/lm_score" --models "$HOME/lmedit/models" --models "$HOME/lmft/models" \
  --data build/lm-finetune2/data --threads 2 --workers "$workers" --out "$HOME/lmedit/holdout" > "$HOME/lmedit/holdout.log" 2>&1
tail -15 "$HOME/lmedit/holdout.log" | cut -c1-300

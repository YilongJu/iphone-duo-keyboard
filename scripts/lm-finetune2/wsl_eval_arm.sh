#!/usr/bin/env bash
# Runs evaluate2.py for one arm in WSL at low priority.
# Usage: wsl_eval_arm.sh NAME MODEL_FILE_OR_- FORMAT_OR_- [extra arguments of evaluate2.py]
# The engine shim, lm_score and llama.cpp b4846 are the builds of round 1 in ~/lmft.
set -euo pipefail
name="$1"; model="$2"; format="$3"; shift 3
root=/mnt/d/Github/iphone-duo-keyboard/build/worktrees
cd "$root/lm-finetune2"
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
model_arguments=()
if [ "$model" != "-" ]; then
  model_arguments=(--lm "$HOME/lmft/bin/lm_score" --model "$model" --prompt-format "$format")
fi
mkdir -p "$HOME/lmft2/results"
# One scoring job at a time: a later job waits for the lock file.
flock "$HOME/lmft2/eval.lock" nice -n 19 python3 scripts/lm-finetune2/evaluate2.py --shim "$HOME/lmft/bin/libduo_shim.so" "${model_arguments[@]}" \
  --threads 2 --round1 "$root/lm-finetune" --data build/lm-finetune2/data --name "$name" \
  --out "$HOME/lmft2/results/$name" "$@" > "$HOME/lmft2/results/$name.log" 2>&1
grep -E '^(tuned|ship) ' "$HOME/lmft2/results/$name.log" | cut -c1-600

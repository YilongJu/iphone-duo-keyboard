#!/usr/bin/env bash
# Copies the result.json of every finished evaluation from WSL into build/lm-weight-edit/results,
# with the fine-tune's own dev results that the comparison cites, and the Q3_K_M file sizes.
# Usage, inside WSL: copy_results.sh
set -euo pipefail
out=/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit/build/lm-weight-edit/results
mkdir -p "$out/finetune"
for f in "$HOME"/lmedit/results/*/result.json; do
  name=$(basename "$(dirname "$f")"); mkdir -p "$out/$name"; cp "$f" "$(dirname "$f")/tuned.dev.jsonl" "$out/$name/"
done
for name in stock-typed stock-converted lora-seed1 lora-seed2 full-seed1 full-seed2 smollm2-stock smollm2-lora-seed1; do
  f="$HOME/lmft/results/$name/result.json"
  if [ -f "$f" ]; then mkdir -p "$out/finetune/$name"; cp "$f" "$(dirname "$f")/tuned.dev.jsonl" "$out/finetune/$name/"; fi
done
stat -c '%n %s' "$HOME"/lmedit/models/*.Q3_K_M.gguf "$HOME"/lmft/models/*.gguf > "$out/gguf-sizes.txt"
ls "$out" "$out/finetune"

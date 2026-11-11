#!/usr/bin/env bash
# Copies the result.json and the predictions of every finished evaluation from WSL into
# build/lm-weight-edit/results, with the fine-tune's own dev results that the comparison cites,
# the output of eval_extra.py into build/lm-weight-edit/extra, and the Q3_K_M file sizes.
# Usage, inside WSL: copy_results.sh
set -euo pipefail
root=/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit/build/lm-weight-edit
out="$root/results"
mkdir -p "$out/finetune" "$root/extra"
copy_run() {  # copy_run SOURCE_DIR TARGET_DIR
  mkdir -p "$2"
  cp "$1/result.json" "$1"/tuned.*.jsonl "$1"/control.dev.jsonl "$1"/control.published_dev.jsonl "$2/"
}
for f in "$HOME"/lmedit/results/*/result.json; do
  copy_run "$(dirname "$f")" "$out/$(basename "$(dirname "$f")")"
done
for name in stock-typed stock-converted lora-seed1 lora-seed2 full-seed1 full-seed2 smollm2-stock smollm2-lora-seed1; do
  if [ -f "$HOME/lmft/results/$name/result.json" ]; then copy_run "$HOME/lmft/results/$name" "$out/finetune/$name"; fi
done
for f in "$HOME"/lmedit/extra/*/extra.json; do
  [ -e "$f" ] || continue
  name=$(basename "$(dirname "$f")"); mkdir -p "$root/extra/$name"
  cp "$(dirname "$f")"/extra.json "$(dirname "$f")"/*.jsonl "$root/extra/$name/"
done
stat -c '%n %s' "$HOME"/lmedit/models/*.Q3_K_M.gguf "$HOME"/lmft/models/*.gguf > "$out/gguf-sizes.txt"
ls "$out" | wc -l; ls "$root/extra" | wc -l

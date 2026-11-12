#!/usr/bin/env bash
# Applies the pick of docs/lm-finetune2-design.md to the selection scores of every SmolLM2 fine-tune,
# each at its clean-text setting. The arms stand in the order of Table 2 of the design.
# Usage, in WSL: bash scripts/lm-finetune2/wsl_pick.sh
set -euo pipefail
cd /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune2
arms=()
for name in smollm2-lora-seed1-calibrated smollm2-lora-seed2 smollm2-lora-seed3 smollm2-lora-mix-seed1 smollm2-lora-mix-seed2 \
            smollm2-lora-mix-seed3 smollm2-lora-mix-hinge-seed1 smollm2-full-mix-seed1 smollm2-lora-clean-seed1; do
  arms+=(--arm "$name:tuned")
done
nice -n 19 python3 scripts/lm-finetune2/summarize2.py pick --round1 ../lm-finetune --data build/lm-finetune2/data \
  --results "$HOME/lmft2/results" --ship smollm2-lora-seed1-calibrated:ship "${arms[@]}" --out "$HOME/lmft2/pick" > "$HOME/lmft2/pick.log" 2>&1
mkdir -p scripts/lm-finetune2/reports
cp "$HOME/lmft2/pick/pick.md" "$HOME/lmft2/pick/pick.json" scripts/lm-finetune2/reports/
tail -n 45 "$HOME/lmft2/pick/pick.md"

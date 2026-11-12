#!/usr/bin/env bash
# Writes holdout-plan.json from the tuned settings and the pick. Usage, in WSL: bash scripts/lm-finetune2/wsl_plan.sh
set -euo pipefail
cd /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune2
arms=()
for name in smollm2-lora-seed2 smollm2-lora-seed3 smollm2-lora-mix-seed1 smollm2-lora-mix-seed2 smollm2-lora-mix-seed3 \
            smollm2-lora-mix-hinge-seed1 smollm2-full-mix-seed1 smollm2-lora-clean-seed1; do
  arms+=(--arm "$name")
done
for name in smollm2-lora-seed2 smollm2-lora-seed3 smollm2-lora-mix-seed1 smollm2-lora-mix-seed2 smollm2-lora-mix-seed3; do
  arms+=(--at-ship-setting "$name")
done
python3 scripts/lm-finetune2/make_holdout_plan.py --round1-models "$HOME/lmft/models" --models "$HOME/lmft2/models" \
  --results "$HOME/lmft2/results" --pick "$HOME/lmft2/pick/pick.json" --data build/lm-finetune2/data "${arms[@]}" \
  --out scripts/lm-finetune2/holdout-plan.json

#!/usr/bin/env bash
# Job: converts the two weight averages, and runs the parity check for them and for the model
# files of rounds 1 and 2 that this round scores (Git Bash).
set -uo pipefail
bash scripts/lm-domain/post_arm.sh soup-mix
bash scripts/lm-domain/post_arm.sh soup-r1
r1=../lm-finetune/build/lm-finetune/models
r2=../lm-finetune2/build/lm-finetune2/models
bash scripts/lm-domain/parity_reference.sh ship "$r1/smollm2-lora-seed1/hf" '~/lmft/models/smollm2-lora-seed1.f16.gguf' '~/lmft/models/smollm2-lora-seed1.Q4_K_M.gguf'
for seed in 1 2 3; do
  bash scripts/lm-domain/parity_reference.sh "mix-seed$seed" "$r2/smollm2-lora-mix-seed$seed/hf" "~/lmft2/models/smollm2-lora-mix-seed$seed.f16.gguf" "~/lmft2/models/smollm2-lora-mix-seed$seed.Q4_K_M.gguf"
done

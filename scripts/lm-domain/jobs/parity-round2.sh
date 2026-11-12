#!/usr/bin/env bash
# Job: the parity check of two more model files of round 2 that this round scores (Git Bash).
set -uo pipefail
r2=../lm-finetune2/build/lm-finetune2/models
bash scripts/lm-domain/parity_reference.sh full-mix-seed1 "$r2/smollm2-full-mix-seed1/hf" '~/lmft2/models/smollm2-full-mix-seed1.f16.gguf' '~/lmft2/models/smollm2-full-mix-seed1.Q4_K_M.gguf'
bash scripts/lm-domain/parity_reference.sh mix-hinge-seed1 "$r2/smollm2-lora-mix-hinge-seed1/hf" '~/lmft2/models/smollm2-lora-mix-hinge-seed1.f16.gguf' '~/lmft2/models/smollm2-lora-mix-hinge-seed1.Q4_K_M.gguf'

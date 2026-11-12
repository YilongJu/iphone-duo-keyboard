#!/usr/bin/env bash
# Prints the Hugging Face folder of an arm: a model of round 1 or 2 in its own worktree, or a
# model of this round. Usage: hf_folder.sh ARM
case "$1" in
  ship) echo "../lm-finetune/build/lm-finetune/models/smollm2-lora-seed1/hf" ;;
  mix-seed1|mix-seed2|mix-seed3) echo "../lm-finetune2/build/lm-finetune2/models/smollm2-lora-$1/hf" ;;
  full-mix-seed1) echo "../lm-finetune2/build/lm-finetune2/models/smollm2-full-mix-seed1/hf" ;;
  mix-hinge-seed1) echo "../lm-finetune2/build/lm-finetune2/models/smollm2-lora-mix-hinge-seed1/hf" ;;
  *) echo "build/lm-domain/models/$1/hf" ;;
esac

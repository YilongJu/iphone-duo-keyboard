#!/usr/bin/env bash
# Converts one trained arm of round 2 the way the phone runs it (llama.cpp b4846, f16, then Q4_K_M),
# checks its tokens and scores against lm_score, and starts its tuning in WSL.
# Usage, from Git Bash at the root of the lm-finetune2 worktree: bash scripts/lm-finetune2/post_arm.sh NAME
set -euo pipefail
name="$1"
root=/d/Github/iphone-duo-keyboard/build/worktrees
round1="$root/lm-finetune"
cd "$root/lm-finetune2"
export UV_PROJECT_ENVIRONMENT="$root/lm-finetune2/build/lm-finetune2/venv"
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
out="build/lm-finetune2/models/$name"
nice -n 10 uv run --project scripts/lm-finetune python "$round1/build/lm-finetune/llama-convert/convert_hf_to_gguf.py" "$out/hf" \
  --outtype f16 --outfile "$out/model-f16.gguf" > "$out/convert.log" 2>&1
wsl_out="/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune2/$out"
wsl.exe -d Ubuntu -- bash -lc "mkdir -p ~/lmft2/models && nice -n 19 ~/lmft/quantize-build/bin/llama-quantize $wsl_out/model-f16.gguf ~/lmft2/models/$name.Q4_K_M.gguf Q4_K_M 2 > $wsl_out/quantize.log 2>&1 && cp $wsl_out/model-f16.gguf ~/lmft2/models/$name.f16.gguf && sha256sum ~/lmft2/models/$name.Q4_K_M.gguf && ls -l ~/lmft2/models/$name.Q4_K_M.gguf"
parity="build/lm-finetune2/parity/$name"
nice -n 10 uv run --project scripts/lm-finetune python scripts/lm-finetune/check_parity.py prepare --data "$round1/build/lm-finetune/data" \
  --prompt-format typed --model-dir "$out/hf" --out "$parity" > "$out/parity-prepare.log" 2>&1
wsl_parity="/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune2/$parity"
wsl.exe -d Ubuntu -- bash -lc "export LD_LIBRARY_PATH=~/lmft/llama/lib; nice -n 19 ~/lmft/bin/lm_score ~/lmft2/models/$name.Q4_K_M.gguf 2 tokens < $wsl_parity/requests.tsv > $wsl_parity/llama-tokens.txt 2> $wsl_parity/lm-tokens-stderr.txt && head -n 500 $wsl_parity/requests.tsv | nice -n 19 ~/lmft/bin/lm_score ~/lmft2/models/$name.f16.gguf 2 > $wsl_parity/llama-scores.txt 2> $wsl_parity/lm-scores-stderr.txt"
# A score difference over the limit is written down, and the tuning still runs on the quantized file.
uv run --project scripts/lm-finetune python scripts/lm-finetune/check_parity.py compare --out "$parity" 2>&1 | tail -3 || echo "$name: the parity check did not pass"
wsl.exe -d Ubuntu -- bash -lc "bash /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune2/scripts/lm-finetune2/wsl_eval_arm.sh $name ~/lmft2/models/$name.Q4_K_M.gguf typed --also ship=1.0,0,4,2,1"
echo "$name: converted, checked, tuned"

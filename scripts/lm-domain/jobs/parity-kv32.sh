#!/usr/bin/env bash
# Job: for some arms, scores the first 500 parity requests of the domain lists on an F32 GGUF with
# a copy of lm_score whose key and value cache holds 32-bit floats and whose flash attention is
# off (the copy of scripts/lm-finetune2/wsl_kv_test.sh, in ~/lmft2/kv-test). The job tests whether
# the 16-bit cache of llama.cpp explains the part of the difference that the F32 file leaves (Git Bash).
# Usage: parity-kv32.sh ARM [ARM ...]
set -uo pipefail
python="build/lm-domain/venv/Scripts/python.exe"
wsl_root="/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-domain"
for arm in "$@"; do
  hf="$(bash scripts/lm-domain/hf_folder.sh "$arm")"
  "$python" build/lm-domain/llama-convert/convert_hf_to_gguf.py "$hf" --outtype f32 --outfile "build/lm-domain/f32/$arm.f32.gguf" > "build/lm-domain/f32/$arm.convert.log" 2>&1
  for lists in everyday domain; do
    wsl.exe -d Ubuntu -- bash -lc "set -e; export LD_LIBRARY_PATH=~/lmft/llama/lib; cd $wsl_root; head -n 500 build/lm-domain/parity/$arm/$lists/requests.tsv | ~/lmft2/kv-test/lm_score_kv32_plain build/lm-domain/f32/$arm.f32.gguf 2 > build/lm-domain/parity/$arm/$lists/llama-scores-f32-kv32.txt 2> /dev/null; head -n 500 build/lm-domain/parity/$arm/$lists/requests.tsv | ~/lmft2/kv-test/lm_score_kv16_plain build/lm-domain/f32/$arm.f32.gguf 2 > build/lm-domain/parity/$arm/$lists/llama-scores-f32-kv16-plain.txt 2> /dev/null"
  done
  rm -f "build/lm-domain/f32/$arm.f32.gguf"
  echo "$arm: scored with the 32-bit cache"
done

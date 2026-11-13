#!/usr/bin/env bash
# Job: for every arm with a parity folder, converts the model to an F32 GGUF and scores the first
# 500 parity requests of each list set with lm_score on that file (Git Bash). The F32 file is
# deleted after its scores are written. parity_report.py reads llama-scores-f32.txt.
set -uo pipefail
python="build/lm-domain/venv/Scripts/python.exe"
wsl_root="/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-domain"
mkdir -p build/lm-domain/f32
for folder in build/lm-domain/parity/*/; do
  arm="$(basename "$folder")"
  if [ -f "$folder/everyday/llama-scores-f32.txt" ] && [ -f "$folder/domain/llama-scores-f32.txt" ]; then continue; fi
  hf="$(bash scripts/lm-domain/hf_folder.sh "$arm")"
  "$python" build/lm-domain/llama-convert/convert_hf_to_gguf.py "$hf" --outtype f32 --outfile "build/lm-domain/f32/$arm.f32.gguf" > "build/lm-domain/f32/$arm.convert.log" 2>&1 || { echo "$arm: the conversion did not work"; continue; }
  for lists in everyday domain; do
    wsl.exe -d Ubuntu -- bash -lc "set -e; export LD_LIBRARY_PATH=~/lmft/llama/lib; cd $wsl_root; head -n 500 build/lm-domain/parity/$arm/$lists/requests.tsv | ~/lmdom/bin/lm_score build/lm-domain/f32/$arm.f32.gguf 2 > build/lm-domain/parity/$arm/$lists/llama-scores-f32.part 2> /dev/null; mv build/lm-domain/parity/$arm/$lists/llama-scores-f32.part build/lm-domain/parity/$arm/$lists/llama-scores-f32.txt"
  done
  rm -f "build/lm-domain/f32/$arm.f32.gguf"
  echo "$arm: scored on the F32 file"
done

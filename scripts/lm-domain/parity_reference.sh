#!/usr/bin/env bash
# Runs the parity check of check_parity.py for a model file of an earlier round, on the everyday
# lists and on the domain lists of this round, as post_arm.sh does for an arm of this round.
# Usage, from Git Bash at the root of the worktree:
#   bash scripts/lm-domain/parity_reference.sh NAME HF_FOLDER F16_FILE_IN_WSL Q4_FILE_IN_WSL
set -euo pipefail
name="$1"; hf="$2"; f16="$3"; quantized="$4"
root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
python="$root/build/lm-domain/venv/Scripts/python.exe"
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
wsl_root="/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-domain"
for lists in everyday domain; do
  parity="build/lm-domain/parity/$name/$lists"
  if [ -f "$parity/parity.json" ]; then continue; fi
  mkdir -p "$parity"
  "$python" scripts/lm-finetune/check_parity.py prepare --data "build/lm-domain/data/parity-lists/$lists" \
    --prompt-format typed --model-dir "$hf" --out "$parity" > "$parity/prepare.log" 2>&1
  wsl.exe -d Ubuntu -- bash -lc "set -e; export LD_LIBRARY_PATH=~/lmft/llama/lib; cd $wsl_root; nice -n 15 ~/lmdom/bin/lm_score $quantized 2 tokens < $parity/requests.tsv > $parity/llama-tokens.txt 2> $parity/lm-tokens-stderr.txt; head -n 500 $parity/requests.tsv | nice -n 15 ~/lmdom/bin/lm_score $f16 2 > $parity/llama-scores.txt 2> $parity/lm-scores-stderr.txt"
  "$python" scripts/lm-finetune/check_parity.py compare --out "$parity" 2>&1 | tail -2 || echo "$name: the parity check on the $lists lists did not pass"
done
echo "$name: checked"

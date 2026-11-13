#!/usr/bin/env bash
# Job: the PyTorch scores with float32 weights and with weights rounded to 16-bit floats, for the
# parity lists of every arm with a parity folder (Git Bash, GPU under the lock).
set -uo pipefail
python="build/lm-domain/venv/Scripts/python.exe"
for folder in build/lm-domain/parity/*/; do
  arm="$(basename "$folder")"
  hf="$(bash scripts/lm-domain/hf_folder.sh "$arm")"
  for lists in everyday domain; do
    if [ -f "$folder/$lists/torch-rounded16.jsonl" ]; then continue; fi
    "$python" scripts/lm-domain/parity_study.py rounded --model-dir "$hf" --lists "build/lm-domain/data/parity-lists/$lists" --out "$folder/$lists" 2>&1 | tail -1
  done
done

#!/usr/bin/env bash
# Job: the word tables and the next-token blocks of one model file, for the three text sets of
# one half (docs/prediction-strip-benchmark-design.md). The job is safe to start again: a text
# half goes on after the blocks it finished.
#
# Usage, in WSL, from the repository root:
#   bash scripts/prediction-strip/benchmark/job_blocks.sh NAME MODEL.gguf [HALF] [WORKERS]
# From Windows, detached:
#   powershell -File scripts/lm-domain/detach.ps1 -Name blocks-NAME -Where wsl \
#     -Script scripts/prediction-strip/benchmark/job_blocks.sh -Arguments "NAME MODEL.gguf dev 6"
#
# PREDSTRIP_LM and PREDSTRIP_LLAMA_LIB name the scorer and the folder of the llama.cpp libraries.
set -euo pipefail
name="$1"
model="${2/#\~/$HOME}"
half="${3:-dev}"
workers="${4:-6}"
lm="${PREDSTRIP_LM:-$HOME/predstrip/bin/lm_score}"
export LD_LIBRARY_PATH="${PREDSTRIP_LLAMA_LIB:-$HOME/lmft/llama/lib}"
uv="$(command -v uv || echo /snap/bin/uv)"
here=scripts/prediction-strip/benchmark

if [ ! -f "build/prediction-strip/bench/tables/$name/tables.npz" ]; then
  "$uv" run --quiet --with numpy python "$here/tables.py" --lm "$lm" --model "$model" --name "$name"
fi
for text_set in technical everyday mobile; do
  nice -n 10 "$uv" run --quiet --with numpy python "$here/blocks.py" --lm "$lm" --model "$model" --name "$name" \
    --set "$text_set" --half "$half" --workers "$workers"
done

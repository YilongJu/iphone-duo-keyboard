#!/usr/bin/env bash
# Job: the word order M+R with the shipped model, for the three text sets of one half
# (rescore.py). The three sets run one after the other, each with 6 scorer processes.
#
# Usage, in WSL, from the repository root:
#   bash scripts/prediction-strip/benchmark/job_rescore.sh RULE FIRST_WORD [HALF]
set -euo pipefail
rule="$1"
first_word="$2"
half="${3:-dev}"
lm="${PREDSTRIP_LM:-$HOME/predstrip/bin/lm_score}"
export LD_LIBRARY_PATH="${PREDSTRIP_LLAMA_LIB:-$HOME/lmft/llama/lib}"
uv="$(command -v uv || echo /snap/bin/uv)"
here=scripts/prediction-strip/benchmark
model="$HOME/lmdom/models/dom-s100-seed1.Q4_K_M.gguf"
for text_set in everyday mobile technical; do
  if [ ! -f "build/prediction-strip/bench/places/shipped.$text_set.$half.rescored.$rule-$first_word.npy" ]; then
    nice -n 10 "$uv" run --quiet --with numpy python "$here/rescore.py" --lm "$lm" --model "$model" --name shipped \
      --set "$text_set" --half "$half" --rule "$rule" --first-word "$first_word" --cli build/prediction-strip/duo_cli --workers 6
  fi
done

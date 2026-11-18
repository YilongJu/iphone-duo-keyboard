#!/usr/bin/env bash
# Job: the blocks and the places of the other model files of the benchmark, one after the other,
# and the blocks of the texts of the first measurement for the pipeline check.
# The job is safe to start again: each part skips the work that is already done.
#
# Usage, in WSL, from the repository root:
#   bash scripts/prediction-strip/benchmark/job_rest.sh
set -euo pipefail
lm="${PREDSTRIP_LM:-$HOME/predstrip/bin/lm_score}"
export LD_LIBRARY_PATH="${PREDSTRIP_LLAMA_LIB:-$HOME/lmft/llama/lib}"
uv="$(command -v uv || echo /snap/bin/uv)"
here=scripts/prediction-strip/benchmark
shipped="$HOME/lmdom/models/dom-s100-seed1.Q4_K_M.gguf"

# The texts of the first measurement, read by the shipped model.
python3 "$here/check_pipeline.py" --write-contexts
if [ ! -f build/prediction-strip/bench/places/legacy.done ]; then
  nice -n 10 "$uv" run --quiet --with numpy python "$here/blocks.py" --lm "$lm" --model "$shipped" --name shipped \
    --set legacy --half dev --contexts build/prediction-strip/bench/legacy-contexts.txt --workers 6
  mkdir -p build/prediction-strip/bench/places
  touch build/prediction-strip/bench/places/legacy.done
fi

for pair in "base135 $HOME/modelspeed/gguf/smollm2-135m.Q4_K_M.gguf" "smol360 $HOME/modelspeed/gguf/smollm2-360m.Q4_K_M.gguf" \
            "qwen05 $HOME/modelspeed/gguf/qwen2.5-0.5b.Q4_K_M.gguf"; do
  set -- $pair
  if [ ! -f "build/prediction-strip/bench/places/$1.mobile.dev.npy" ]; then
    bash "$here/job_blocks.sh" "$1" "$2" dev 6
    bash "$here/job_places.sh" "$1" dev
  fi
done

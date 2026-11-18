#!/usr/bin/env bash
# Job: the predicted-word measurement on the dev stream, in WSL (scripts/prediction-strip/README.md).
# The job is safe to start again: a shard goes on after its last whole sentence.
#
# Start it detached, from Windows:
#   powershell -File scripts/lm-domain/detach.ps1 -Name prediction-strip-dev -Where wsl -Script scripts/prediction-strip/run_dev.sh
# The log is build/lm-domain/logs/prediction-strip-dev.log.
#
# PREDSTRIP_LM, PREDSTRIP_MODEL and PREDSTRIP_LLAMA_LIB name the scorer, the model file and the
# folder of the llama.cpp libraries. PREDSTRIP_WORKERS sets the count of scorer processes.
set -euo pipefail
lm="${PREDSTRIP_LM:-$HOME/predstrip/bin/lm_score}"
model="${PREDSTRIP_MODEL:-$HOME/lmdom/models/dom-s100-seed1.Q4_K_M.gguf}"
export LD_LIBRARY_PATH="${PREDSTRIP_LLAMA_LIB:-$HOME/lmft/llama/lib}"
workers="${PREDSTRIP_WORKERS:-6}"
uv="$(command -v uv || echo /snap/bin/uv)"
out=build/prediction-strip

expected="8c0835e0eeb4787b853b4223facc14612d4d1b6c4bd7e33f7ad1ff9fc167dec8"
actual="$(sha256sum "$model" | cut -d' ' -f1)"
if [ "$actual" != "$expected" ]; then
  echo "error: $model has the SHA-256 value $actual, and the shipped file has $expected" >&2
  exit 1
fi

"$uv" run --quiet --with numpy python scripts/prediction-strip/build_tables.py --lm "$lm" --model "$model" --out "$out/tables"
mkdir -p "$out/ranks"
pids=()
for shard in $(seq 0 $((workers - 1))); do
  nice -n 10 "$uv" run --quiet --with numpy python scripts/prediction-strip/measure.py --lm "$lm" --model "$model" \
    --threads 2 --tables "$out/tables" --shard "$shard/$workers" --out "$out/ranks/shard-$shard.jsonl" \
    > "$out/ranks/shard-$shard.log" 2>&1 &
  pids+=("$!")
done
failed=0
for pid in "${pids[@]}"; do
  wait "$pid" || failed=1
done
if [ "$failed" -ne 0 ]; then
  echo "error: a shard did not end well; see $out/ranks/shard-*.log" >&2
  exit 1
fi
tail -n 1 "$out"/ranks/shard-*.log

#!/usr/bin/env bash
# Job: the places of the written word for the engine's order and the model orders of one model
# file, in the three text sets of one half. The three sets run side by side.
#
# Usage, in WSL, from the repository root:
#   bash scripts/prediction-strip/benchmark/job_places.sh NAME [HALF]
set -euo pipefail
name="$1"
half="${2:-dev}"
uv="$(command -v uv || echo /snap/bin/uv)"
here=scripts/prediction-strip/benchmark
cli=build/prediction-strip/duo_cli
if [ ! -x "$cli" ]; then
  gcc -std=c11 -O2 -Wall -Wextra -Werror -I Engine Engine/duo_engine.c Engine/duo_cli.c -lm -o "$cli"
fi
pids=()
for text_set in technical everyday mobile; do
  nice -n 10 "$uv" run --quiet --with numpy python "$here/places.py" --name "$name" --set "$text_set" --half "$half" \
    --cli "$cli" &
  pids+=("$!")
done
failed=0
for pid in "${pids[@]}"; do
  wait "$pid" || failed=1
done
if [ "$failed" -ne 0 ]; then
  echo "error: a text set did not end well" >&2
  exit 1
fi

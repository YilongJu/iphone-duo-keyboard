#!/usr/bin/env bash
# Job: types the dev cases of this branch through the harness of the keyboard workflow with the
# shipped file at the shipped setting (WSL), and compares the keyboard's scorer with lm_score on
# every request. The job builds the engine shim, lm_score and the keyboard's scorer from this
# branch, against the llama.cpp b4846 build of $HOME/lmft/llama. The steps equal the job
# "harness" of .github/workflows/lm-keyboard.yml.
# Usage: shipped-harness.sh MODEL_FILE [OUT]
set -euo pipefail
model="${1/#\~/$HOME}"
out="${2:-build/lm-keyboard/local-harness}"
llama="$HOME/lmft/llama"
export LD_LIBRARY_PATH="$llama/lib"
mkdir -p "$out/bin"
gcc -std=c11 -O2 -Wall -Wextra -Werror -shared -fPIC -I Engine \
  Engine/duo_engine.c scripts/lm-rerank/engine_shim.c -lm -o "$out/bin/libduo_shim.so"
gcc -std=c11 -O2 -Wall -Wextra -Werror -I "$llama/include" scripts/lm-rerank/lm_score.c \
  -L "$llama/lib" -lllama -lggml -lggml-cpu -lggml-base -lm -o "$out/bin/lm_score"
gcc -std=c11 -O2 -Wall -Wextra -Werror -I "$llama/include" -I LanguageModel \
  LanguageModel/duo_lm_scorer.c scripts/lm-keyboard/scorer_cli.c \
  -L "$llama/lib" -lllama -lggml -lggml-cpu -lggml-base -lm -o "$out/bin/scorer_cli"
sha256sum "$model" | tee "$out/model-sha256.txt"
lscpu | grep -E 'Model name' | tee "$out/runner.txt"
if [ ! -f "$out/result.json" ]; then
  nice -n 10 python3 scripts/lm-keyboard/harness_trace.py --shim "$out/bin/libduo_shim.so" --lm "$out/bin/lm_score" \
    --model "$model" --out "$out"
fi
"$out/bin/lm_score" "$model" 4 < "$out/requests.tsv" 2> "$out/lm_score.log" | tail -n +2 > "$out/lm_score.answers"
"$out/bin/scorer_cli" "$model" 2 < "$out/requests.tsv" > "$out/scorer_cli.answers" 2> "$out/scorer_cli.log"
{
  echo "requests: $(wc -l < "$out/requests.tsv")"
  echo "lm_score answers: $(wc -l < "$out/lm_score.answers"), scorer_cli answers: $(wc -l < "$out/scorer_cli.answers")"
  if cmp -s "$out/lm_score.answers" "$out/scorer_cli.answers"; then
    echo "the answers are the same byte for byte, 5 decimals each"
  else
    echo "the answers differ in $(diff "$out/lm_score.answers" "$out/scorer_cli.answers" | grep -c '^<') lines"
  fi
  cat "$out/scorer_cli.log"
} | tee "$out/scorer-check.txt"
cmp "$out/lm_score.answers" "$out/scorer_cli.answers"

#!/usr/bin/env bash
# Job: the desktop part of the speed test of docs/model-speed-design.md. Each run reads the 486
# requests of Shared/model-speed-requests.tsv in order, at 2 threads, with the keyboard's reuse of
# the cache. The runs go one at a time, so each run is alone on the machine.
# Usage, from the repository root in WSL, after jobs/convert.sh: speed.sh
# A finished run (its .summary file) is kept, so the job can start again after a restart.
set -euo pipefail
work="${MODEL_SPEED_WORK:-$HOME/modelspeed}"
out="$work/out"
requests="Shared/model-speed-requests.tsv"
mkdir -p "$out" "$work/tokens" "$work/bin"
old="$HOME/lmft/llama"
new="$work/llama-b12017"

build() {
  local name="$1" prefix="$2" flags="$3"
  gcc -std=c11 -O2 -Wall -Wextra -Werror $flags -I "$prefix/include" -I LanguageModel LanguageModel/duo_lm_scorer.c \
    scripts/model-speed/speed_cli.c -L "$prefix/lib" -lllama -lggml -lggml-cpu -lggml-base -lm -o "$work/bin/$name"
}
build speed_cli-b4846 "$old" ""
build speed_cli-b12017 "$new" "-DDUO_LLAMA_MEMORY_API"

# run NAME VERSION MODEL [environment]
run() {
  local name="$1" version="$2" model="$3" setting="${4:-}"
  if [ -s "$out/$name.summary" ]; then echo "kept $name"; return 0; fi
  local lib="$old/lib"
  [ "$version" = b12017 ] && lib="$new/lib"
  env LD_LIBRARY_PATH="$lib" $setting "$work/bin/speed_cli-$version" "$model" 2 cpu "$requests" "$out/$name" \
    2> "$out/$name.log" || { echo "FAILED $name: $(tail -n 2 "$out/$name.log")"; return 0; }
  echo "done $name"
}

models=$(python3 -c "import json; print(' '.join(m['name'] for m in json.load(open('scripts/model-speed/models.json'))['models']))")
for name in $models; do
  if [ ! -s "$work/tokens/$name.tokens" ]; then
    LD_LIBRARY_PATH="$new/lib" "$work/bin/speed_cli-b12017" "$work/gguf/$name.Q8_0.gguf" 2 tokens "$requests" \
      "$work/tokens/$name"
  fi
  run "$name.Q8_0.b12017" b12017 "$work/gguf/$name.Q8_0.gguf"
done
run "shipped.Q4_K_M.b4846" b4846 "$HOME/kvreuse/model.gguf"
run "shipped.Q4_K_M.b12017" b12017 "$HOME/kvreuse/model.gguf"
for name in $models; do
  for type in Q4_K_M Q4_0; do
    run "$name.$type.b4846" b4846 "$work/gguf/$name.$type.gguf"
    run "$name.$type.b12017" b12017 "$work/gguf/$name.$type.gguf"
    run "$name.$type.b12017-norepack" b12017 "$work/gguf/$name.$type.gguf" DUO_LM_NO_REPACK=1
  done
done
echo "all speed runs ended"

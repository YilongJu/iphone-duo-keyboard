#!/usr/bin/env bash
# Scores the probe requests of probe.py with lm_score and with the keyboard's scorer, each built
# with several step and call sizes, and prints the table of differences.
#
# Usage, from the repository root:
#   run.sh mac   OUT    on the macOS runner, against the macOS part of Vendor/llama.xcframework
#   run.sh linux OUT    on Linux, against build/lm-rerank/llama of build_on_linux.sh llama
set -euo pipefail
cd "$(dirname "$0")/../../.."
kind="$1"
out="$2"
mkdir -p "$out/bin"
model=Shared/smollm2-lora-domain-s100-seed1.Q4_K_M.gguf
python3 scripts/lm-keyboard/scorer-probe/probe.py requests "$out/requests.tsv"

if [ "$kind" = mac ]; then
  fw="$PWD/Vendor/llama.xcframework/macos-arm64_x86_64"
  build_lm_score() { clang -std=c11 -O2 -Wall -Wextra "$@" -I "$fw/llama.framework/Headers" scripts/lm-rerank/lm_score.c \
    -F "$fw" -framework llama -Wl,-rpath,"$fw" -o "$out/bin/$name"; }
  build_scorer() { clang -std=c11 -O2 -Wall -Wextra -Werror "$@" -I LanguageModel -F "$fw" LanguageModel/duo_lm_scorer.c \
    scripts/lm-keyboard/scorer_cli.c -framework llama -Wl,-rpath,"$fw" -o "$out/bin/$name"; }
  threads=2
  { sysctl -n machdep.cpu.brand_string; } > "$out/runner.txt"
else
  lib="$PWD/build/lm-rerank/llama"
  export LD_LIBRARY_PATH="$lib/lib"
  build_lm_score() { gcc -std=c11 -O2 -Wall -Wextra "$@" -I "$lib/include" scripts/lm-rerank/lm_score.c \
    -L "$lib/lib" -lllama -lggml -lggml-cpu -lggml-base -lm -o "$out/bin/$name"; }
  build_scorer() { gcc -std=c11 -O2 -Wall -Wextra -Werror "$@" -I "$lib/include" -I LanguageModel LanguageModel/duo_lm_scorer.c \
    scripts/lm-keyboard/scorer_cli.c -L "$lib/lib" -lllama -lggml -lggml-cpu -lggml-base -lm -o "$out/bin/$name"; }
  threads=4
  lscpu | grep -E 'Model name' > "$out/runner.txt"
fi

for size in 512 31 32 64; do name="lm_score-u$size"; build_lm_score -DUBATCH_SIZE=$size; done
for size in 31 32 64 256; do name="scorer-c$size"; build_scorer -DCALL_TOKENS=$size; done

"$out/bin/lm_score-u512" "$model" "$threads" tokens < "$out/requests.tsv" 2>/dev/null | tail -n +2 > "$out/tokens.txt"
for size in 512 31 32 64; do
  "$out/bin/lm_score-u$size" "$model" "$threads" < "$out/requests.tsv" 2>/dev/null | tail -n +2 > "$out/lm_score-u$size.answers"
done
"$out/bin/lm_score-u512" "$model" 1 < "$out/requests.tsv" 2>/dev/null | tail -n +2 > "$out/lm_score-u512-threads1.answers"
for size in 31 32 64 256; do
  "$out/bin/scorer-c$size" "$model" "$threads" < "$out/requests.tsv" 2>/dev/null > "$out/scorer-c$size.answers"
done
"$out/bin/scorer-c31" "$model" 1 < "$out/requests.tsv" 2>/dev/null > "$out/scorer-c31-threads1.answers"
wc -l "$out"/*.answers "$out/tokens.txt"
python3 scripts/lm-keyboard/scorer-probe/probe.py compare "$out" | tee "$out/table.md"

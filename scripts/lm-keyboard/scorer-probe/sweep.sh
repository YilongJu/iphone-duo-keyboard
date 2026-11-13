#!/usr/bin/env bash
# The second probe on the macOS runner (sweep.py): the keyboard's scorer built with calls of 2 to
# 33 tokens and of 256 tokens, on the sweep requests, and with calls of 31 and 256 tokens on all
# requests of run 43142371994. Every answer has full precision (scorer_cli ... full).
#
# Usage, from the repository root, on the macOS runner:  sweep.sh OUT
set -euo pipefail
cd "$(dirname "$0")/../../.."
out="$1"
mkdir -p "$out/bin"
model=Shared/smollm2-lora-domain-s100-seed1.Q4_K_M.gguf
fw="$PWD/Vendor/llama.xcframework/macos-arm64_x86_64"
here=scripts/lm-keyboard/scorer-probe

build_scorer() {
  clang -std=c11 -O2 -Wall -Wextra -Werror -DCALL_TOKENS="$1" -I LanguageModel -F "$fw" LanguageModel/duo_lm_scorer.c \
    scripts/lm-keyboard/scorer_cli.c -framework llama -Wl,-rpath,"$fw" -o "$out/bin/scorer-c$1"
}
clang -std=c11 -O2 -Wall -Wextra -I "$fw/llama.framework/Headers" scripts/lm-rerank/lm_score.c \
  -F "$fw" -framework llama -Wl,-rpath,"$fw" -o "$out/bin/lm_score"

python3 "$here/sweep.py" requests "$out/sweep.tsv"
"$out/bin/lm_score" "$model" 1 tokens < "$out/sweep.tsv" 2>/dev/null | tail -n +2 > "$out/sweep.tokens"
for size in $(seq 2 33) 256; do
  build_scorer "$size"
  "$out/bin/scorer-c$size" "$model" 2 full < "$out/sweep.tsv" 2>/dev/null > "$out/sweep-c$size.answers"
done
python3 "$here/sweep.py" calls "$out" | tee "$out/calls.md"

gunzip -c "$here/inputs/requests-43142371994-mac.tsv.gz" > "$out/all.tsv"
"$out/bin/lm_score" "$model" 1 tokens < "$out/all.tsv" 2>/dev/null | tail -n +2 > "$out/all.tokens"
# The two builds run side by side on 1 thread each. The thread count does not move a number (probe.py).
"$out/bin/scorer-c31" "$model" 1 full < "$out/all.tsv" 2> "$out/all-c31.log" > "$out/all-c31.answers" &
"$out/bin/scorer-c256" "$model" 1 full < "$out/all.tsv" 2> "$out/all-c256.log" > "$out/all-c256.answers" &
wait
python3 "$here/sweep.py" all "$out" | tee "$out/all.md"

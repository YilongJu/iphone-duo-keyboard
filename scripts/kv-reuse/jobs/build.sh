#!/usr/bin/env bash
# Builds the engine shim and kv_replay into $KV/bin (default $HOME/kvreuse), against the
# llama.cpp b4846 build of $HOME/lmft/llama (scripts/lm-rerank/build_on_linux.sh llama), and
# copies the shipped model file next to them. kv_replay-min1 reads windows with calls of one token
# (MIN_UNREAD_TOKENS 1 in LanguageModel/duo_lm_scorer.c). Run it from the repository root in WSL.
set -euo pipefail
kv="${KV:-$HOME/kvreuse}"
llama="$HOME/lmft/llama"
mkdir -p "$kv/bin"
gcc -std=c11 -O2 -Wall -Wextra -Werror -shared -fPIC -I Engine \
  Engine/duo_engine.c scripts/lm-rerank/engine_shim.c -lm -o "$kv/bin/libduo_shim.so"
for variant in "" "-min1"; do
  flags=""
  [ "$variant" = "-min1" ] && flags="-DMIN_UNREAD_TOKENS=1"
  gcc -std=c11 -O2 -Wall -Wextra -Werror $flags -I "$llama/include" -I LanguageModel \
    LanguageModel/duo_lm_scorer.c scripts/kv-reuse/kv_replay.c \
    -L "$llama/lib" -lllama -lggml -lggml-cpu -lggml-base -lm -o "$kv/bin/kv_replay$variant"
done
model=Shared/smollm2-lora-domain-s100-seed1.Q4_K_M.gguf
[ -f "$kv/model.gguf" ] || cp "$model" "$kv/model.gguf"
sha256sum "$kv/model.gguf" | tee "$kv/model-sha256.txt"
grep -q 8c0835e0eeb4787b853b4223facc14612d4d1b6c4bd7e33f7ad1ff9fc167dec8 "$kv/model-sha256.txt"
lscpu | grep -E 'Model name' | tee "$kv/runner.txt"
git rev-parse HEAD > "$kv/commit.txt" 2>/dev/null || echo "git does not run here" > "$kv/commit.txt"
echo built

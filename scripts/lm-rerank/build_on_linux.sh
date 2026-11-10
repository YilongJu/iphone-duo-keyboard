#!/usr/bin/env bash
# Builds the programs of the re-ranking measurement on Linux, into build/lm-rerank/:
#   libduo_shim.so    the engine for rerank.py
#   readings_check    the check of duo_english_readings, with the memory checks of the compiler
#   lm_score          the language-model scorer, against llama.cpp b4846 (with "llama")
#   probe_cli         the language model test of LanguageModel/duo_lm_probe.c (with "llama")
#
# Usage: build_on_linux.sh [llama]
set -euo pipefail
cd "$(dirname "$0")/../.."
work="build/lm-rerank"
mkdir -p "$work"

gcc -std=c11 -O2 -Wall -Wextra -Werror -shared -fPIC -I Engine \
  Engine/duo_engine.c scripts/lm-rerank/engine_shim.c -lm -o "$work/libduo_shim.so"
gcc -std=c11 -O1 -g -Wall -Wextra -Wpedantic -Werror -fsanitize=address,undefined -I Engine \
  Engine/duo_engine.c scripts/lm-rerank/readings_check.c -lm -o "$work/readings_check"
echo "built the engine shim and the readings check"

if [ "${1:-}" != "llama" ]; then
  exit 0
fi

# The commit of tag b4846 in https://github.com/azooKey/llama.cpp, as in
# scripts/language-model-test/run_on_linux.sh and the framework in the app.
llama_commit="10131b23ee0dbd9d03dfc618cec9fe3402919277"
if [ ! -d "$work/llama.cpp/.git" ]; then
  git init --quiet "$work/llama.cpp"
  git -C "$work/llama.cpp" remote add origin https://github.com/azooKey/llama.cpp
fi
git -C "$work/llama.cpp" fetch --quiet --depth 1 origin "$llama_commit"
git -C "$work/llama.cpp" checkout --quiet --detach FETCH_HEAD
cmake -S "$work/llama.cpp" -B "$work/llama-build" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON \
  -DCMAKE_INSTALL_LIBDIR=lib -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=OFF \
  -DLLAMA_BUILD_COMMON=OFF -DLLAMA_CURL=OFF > "$work/cmake-configure.log"
cmake --build "$work/llama-build" --parallel > "$work/cmake-build.log"
cmake --install "$work/llama-build" --prefix "$PWD/$work/llama" > "$work/cmake-install.log"

gcc -std=c11 -O2 -Wall -Wextra -Werror -I "$work/llama/include" scripts/lm-rerank/lm_score.c \
  -L "$work/llama/lib" -lllama -lggml -lggml-cpu -lggml-base -lm -o "$work/lm_score"
gcc -std=c11 -O2 -Wall -Wextra -Werror -I "$work/llama/include" -I LanguageModel \
  LanguageModel/duo_lm_probe.c scripts/language-model-test/probe_cli.c \
  -L "$work/llama/lib" -lllama -lggml -lggml-cpu -lggml-base -lm -o "$work/probe_cli"
echo "built lm_score and probe_cli against llama.cpp $llama_commit"

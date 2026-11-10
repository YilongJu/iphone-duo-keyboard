#!/usr/bin/env bash
# Runs the language model test of LanguageModel/duo_lm_probe.c on Linux. The script builds
# llama.cpp from the commit that the framework in the app was built from, compiles the test
# against that build, and runs the test on the model file that ships.
#
# The run proves three things without a Mac: the test compiles against this version of
# llama.cpp, the model file loads, and the two ways to score the candidates agree. The times
# belong to the Linux machine. The memory lines are empty, because they need iOS.
#
# Usage, from any folder, after "bash scripts/ci/fetch_language_model.sh model":
#   bash scripts/language-model-test/run_on_linux.sh
# The result lines go to build/language-model-test/result.txt.
set -euo pipefail
cd "$(dirname "$0")/../.."

# The commit of tag b4846 in https://github.com/azooKey/llama.cpp.
llama_commit="10131b23ee0dbd9d03dfc618cec9fe3402919277"
model="Shared/distilgpt2.Q3_K_M.gguf"
work="build/language-model-test"
mkdir -p "$work"

if [ ! -f "$model" ]; then
  echo "error: $model is missing, run scripts/ci/fetch_language_model.sh model first" >&2
  exit 1
fi

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

gcc -std=c11 -O2 -Wall -Wextra -Werror -I "$work/llama/include" -I LanguageModel \
  LanguageModel/duo_lm_probe.c scripts/language-model-test/probe_cli.c \
  -L "$work/llama/lib" -lllama -lggml -lggml-base -lm -o "$work/probe_cli"

LD_LIBRARY_PATH="$PWD/$work/llama/lib" "$work/probe_cli" "$model" | tee "$work/result.txt"

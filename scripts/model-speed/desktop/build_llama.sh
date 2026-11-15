#!/usr/bin/env bash
# Builds llama.cpp at a release tag on Linux, for the processor only, and installs it.
# Usage: build_llama.sh TAG OUT_DIR
#   TAG      a release of https://github.com/ggml-org/llama.cpp, such as b12017
#   OUT_DIR  the source goes to OUT_DIR/src-TAG and the install to OUT_DIR/llama-TAG
# The build also keeps the tools llama-quantize and the converter script of that release.
set -euo pipefail
tag="$1"
out="$2"
src="$out/src-$tag"
prefix="$out/llama-$tag"
if [ ! -d "$src/.git" ]; then
  git clone --quiet --depth 1 --branch "$tag" https://github.com/ggml-org/llama.cpp "$src"
fi
cmake -S "$src" -B "$src/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" \
  -DBUILD_SHARED_LIBS=ON -DCMAKE_INSTALL_LIBDIR=lib -DGGML_NATIVE=ON -DGGML_OPENMP=OFF -DGGML_CUDA=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=OFF -DLLAMA_BUILD_APP=OFF -DLLAMA_CURL=OFF \
  -DLLAMA_BUILD_TOOLS=ON > "$out/build-$tag.log" 2>&1
cmake --build "$src/build" --config Release -j 8 >> "$out/build-$tag.log" 2>&1
cmake --install "$src/build" >> "$out/build-$tag.log" 2>&1
mkdir -p "$prefix/bin"
install -m 755 "$src/build/bin/llama-quantize" "$prefix/bin/"
test -x "$prefix/bin/llama-quantize"
echo "built llama.cpp $tag into $prefix"

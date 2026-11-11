#!/usr/bin/env bash
# Downloads the two files of the language model that are too large for the repository: the
# llama.cpp framework and the model file. Each file has a fixed address and must match a
# fixed SHA-256 value. A file that is already in place and matches is kept.
#
# Usage: fetch_language_model.sh [framework] [model]
# Without an argument the script fetches both. Run it before "xcodegen generate", because
# XcodeGen adds the model to both targets only when the file is in Shared/.
set -euo pipefail
cd "$(dirname "$0")/../.."

# llama.cpp at release b4846, built and signed by the azooKey project for its own keyboard
# extension. The same file and SHA-256 value are in the Package.swift of
# https://github.com/azooKey/AzooKeyKanaKanjiConverter.
framework_url="https://github.com/azooKey/llama.cpp/releases/download/b4846/signed-llama.xcframework.zip"
framework_sha256="db3b13169df8870375f212e6ac21194225f1c85f7911d595ab64c8c790068e0a"
framework_dir="Vendor"

# SmolLM2-135M with a LoRA fine-tune for the re-ranker in the typed format, merged and stored with
# weights of about 4 bits (Q4_K_M). scripts/lm-finetune on the branch engine/lm-finetune trained
# it, and the release lm-finetune-smollm2-lora-v1 of this repository holds the file.
model_url="https://github.com/YilongJu/iphone-duo-keyboard/releases/download/lm-finetune-smollm2-lora-v1/smollm2-lora-typed-seed1.Q4_K_M.gguf"
model_sha256="fe82c0b617bdf19cf72b92148edbf9406c7547396ca7fac477485884431c07bb"
model_path="Shared/smollm2-lora-typed-seed1.Q4_K_M.gguf"

sha256_of() {
  shasum -a 256 "$1" | cut -d ' ' -f 1
}

# Downloads <address> to <path> and stops when the file does not match <SHA-256 value>.
download() {
  local url="$1" path="$2" expected="$3" part actual
  if [ -f "$path" ] && [ "$(sha256_of "$path")" = "$expected" ]; then
    echo "kept $path"
    return 0
  fi
  mkdir -p "$(dirname "$path")"
  part=$(mktemp)
  curl --fail --location --silent --show-error --retry 3 --output "$part" "$url"
  actual=$(sha256_of "$part")
  if [ "$actual" != "$expected" ]; then
    rm -f "$part"
    echo "error: $url has the SHA-256 value $actual, expected $expected" >&2
    exit 1
  fi
  mv "$part" "$path"
  echo "fetched $path ($(wc -c < "$path" | tr -d ' ') bytes)"
}

fetch_framework() {
  download "$framework_url" "$framework_dir/signed-llama.xcframework.zip" "$framework_sha256"
  rm -rf "$framework_dir/llama.xcframework"
  unzip -q "$framework_dir/signed-llama.xcframework.zip" -d "$framework_dir"
  test -f "$framework_dir/llama.xcframework/ios-arm64/llama.framework/llama"
  echo "unpacked $framework_dir/llama.xcframework"
}

fetch_model() {
  download "$model_url" "$model_path" "$model_sha256"
}

if [ "$#" -eq 0 ]; then
  set -- framework model
fi
for part in "$@"; do
  case "$part" in
    framework) fetch_framework ;;
    model) fetch_model ;;
    *)
      echo "usage: fetch_language_model.sh [framework] [model]" >&2
      exit 2
      ;;
  esac
done

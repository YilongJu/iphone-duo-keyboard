#!/usr/bin/env bash
# Downloads one model file of the re-ranking comparison into build/lm-rerank/models/. Each file
# has a fixed address at a fixed commit of its Hugging Face repository and must match a fixed
# SHA-256 value. A file already in place that matches is kept.
#
# Usage: fetch_models.sh NAME     (prints the path of the file on its last line)
#        fetch_models.sh --list   (prints the names)
set -euo pipefail
cd "$(dirname "$0")/../.."

# name | file | repository | commit | SHA-256
models="
distilgpt2-q3|distilgpt2.Q3_K_M.gguf|mradermacher/distilgpt2-GGUF|524d576d63aa026274d5a1ee42414edf7f61e7c7|a0fdd02371cf4b318445575ab917cd3cf4abf494e09c24f760f777eb641b2b85
distilgpt2-q4|distilgpt2.Q4_K_M.gguf|mradermacher/distilgpt2-GGUF|524d576d63aa026274d5a1ee42414edf7f61e7c7|eab60071574f8187637ab2bef8b76a8081580dd35558f4ad40ca5ac4666b35b9
gpt2-q4|gpt2.Q4_K_M.gguf|mradermacher/gpt2-GGUF|0cda0c2b1459ccd32256c6ddde9d230934112c1c|371425b33a2f6ec683ba1746cc288703da48584641d521176f35866059f13946
smollm2-135m-q4|SmolLM2-135M.Q4_K_M.gguf|mradermacher/SmolLM2-135M-GGUF|bf92313aa80eb55329ae75ccce3743101784c802|127c52bae983b2d0de09c60d6292743e3239e44239bbe8ccb8cf3241513ff5a0
smollm2-360m-q4|SmolLM2-360M.Q4_K_M.gguf|mradermacher/SmolLM2-360M-GGUF|630c4866d716e28f45a516ed00e2882149726c13|4ac7aa712c43fe7d07ed910298b5eaab932292692954abd8e0703307724e4e04
qwen2.5-0.5b-q4|Qwen2.5-0.5B.Q4_K_M.gguf|mradermacher/Qwen2.5-0.5B-GGUF|87d752690ccba5de5aa9eb4045cc0e930899b0ef|8d20785a927eb0f0a2a56cf5a959dc65b44a52d1eb6b65d5061de5f87d0e15ef
qwen3-0.6b-q4|Qwen3-0.6B-Base.Q4_K_M.gguf|mradermacher/Qwen3-0.6B-Base-GGUF|b8b11a6dbbb14c739e25018f3f77abac860c28f4|1c728e4fe4abb28cde33b59cd66396e62b2ef755f53db44cdb54e9655b863782
"

if [ "${1:-}" = "--list" ]; then
  echo "$models" | grep '|' | cut -d '|' -f 1
  exit 0
fi
name="${1:?usage: fetch_models.sh NAME}"
row=$(echo "$models" | grep "^$name|" || true)
if [ -z "$row" ]; then
  echo "error: unknown model $name" >&2
  exit 2
fi
IFS='|' read -r _ file repository commit expected <<< "$row"
path="build/lm-rerank/models/$file"
mkdir -p "$(dirname "$path")"
if [ -f "$path" ] && [ "$(sha256sum "$path" | cut -d ' ' -f 1)" = "$expected" ]; then
  echo "kept $path"
else
  part=$(mktemp)
  curl --fail --location --silent --show-error --retry 3 --output "$part" \
    "https://huggingface.co/$repository/resolve/$commit/$file"
  actual=$(sha256sum "$part" | cut -d ' ' -f 1)
  if [ "$actual" != "$expected" ]; then
    rm -f "$part"
    echo "error: $file has the SHA-256 value $actual, expected $expected" >&2
    exit 1
  fi
  mv "$part" "$path"
  echo "fetched $path ($(wc -c < "$path" | tr -d ' ') bytes)"
fi
echo "$path"

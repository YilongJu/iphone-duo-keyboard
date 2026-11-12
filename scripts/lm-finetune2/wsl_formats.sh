#!/usr/bin/env bash
# Scores two SmolLM2 fine-tunes in several file formats on the tuning and selection sets:
# `ship` (smollm2-lora-seed1 of round 1) and smollm2-lora-mix-seed1, each as f16, Q8_0, Q5_K_M and
# Q4_K_M with an importance matrix. The plain Q4_K_M files already have their scores.
# Each format gets its own setting from the tuning sets (evaluate2.py). The held-out set is not read.
# Usage, in WSL: bash scripts/lm-finetune2/wsl_formats.sh
set -euo pipefail
root=/mnt/d/Github/iphone-duo-keyboard/build/worktrees
cd "$root/lm-finetune2"
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
out="$HOME/lmft2/formats"
mkdir -p "$out"
quantize="$HOME/lmft/quantize-build/bin/llama-quantize"
declare -A f16=( [ship]="$HOME/lmft/models/smollm2-lora-seed1.f16.gguf" [mix]="$HOME/lmft2/models/smollm2-lora-mix-seed1.f16.gguf" )

# The importance matrix tool of the same llama.cpp commit, in a build folder of round 2.
if [ ! -x "$HOME/lmft2/imatrix-build/bin/llama-imatrix" ]; then
  nice -n 19 cmake -S "$HOME/lmft/llama.cpp" -B "$HOME/lmft2/imatrix-build" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=ON -DLLAMA_BUILD_SERVER=OFF -DLLAMA_BUILD_COMMON=ON -DLLAMA_CURL=OFF > "$out/imatrix-configure.log"
  nice -n 19 cmake --build "$HOME/lmft2/imatrix-build" --target llama-imatrix --parallel 4 > "$out/imatrix-build.log" 2>&1
fi
# The calibration text: 3,000 training lists of round 2 in the typed format, each with its target.
# imatrix_text.py writes the file on Windows, where the tokenizer is installed.
cp build/lm-finetune2/imatrix-text.txt "$out/imatrix-text.txt"

for arm in ship mix; do
  cp --update=none "${f16[$arm]}" "$out/fmt-$arm-f16.gguf"
  for format in Q8_0 Q5_K_M; do
    [ -f "$out/fmt-$arm-$format.gguf" ] || nice -n 19 "$quantize" "${f16[$arm]}" "$out/fmt-$arm-$format.gguf" "$format" 2 > "$out/quantize-$arm-$format.log" 2>&1
  done
  if [ ! -f "$out/fmt-$arm-Q4_K_M-imatrix.gguf" ]; then
    nice -n 19 "$HOME/lmft2/imatrix-build/bin/llama-imatrix" -m "${f16[$arm]}" -f "$out/imatrix-text.txt" -o "$out/imatrix-$arm.dat" \
      -t 4 --chunks 100 > "$out/imatrix-$arm.log" 2>&1
    nice -n 19 "$quantize" --imatrix "$out/imatrix-$arm.dat" "${f16[$arm]}" "$out/fmt-$arm-Q4_K_M-imatrix.gguf" Q4_K_M 2 > "$out/quantize-$arm-imatrix.log" 2>&1
  fi
done
cp --update=none "$HOME/lmft/models/smollm2-lora-seed1.Q4_K_M.gguf" "$out/fmt-ship-Q4_K_M.gguf"
cp --update=none "$HOME/lmft2/models/smollm2-lora-mix-seed1.Q4_K_M.gguf" "$out/fmt-mix-Q4_K_M.gguf"
ls -l "$out"/*.gguf > "$out/sizes.txt"
sha256sum "$out"/*.gguf > "$out/sha256.txt"

# The model time per request of each file, one file at a time, on the first 500 parity requests.
requests="build/lm-finetune2/parity/smollm2-lora-mix-seed1/requests.tsv"
: > "$out/timing.txt"
for file in "$out"/fmt-*.gguf; do
  for round in 1 2; do
    head -n 500 "$requests" | nice -n 19 "$HOME/lmft/bin/lm_score" "$file" 2 2>&1 > /dev/null | grep "tokens read" | sed "s|^|$(basename "$file") run $round: |" >> "$out/timing.txt"
  done
done

# The tuning and the selection scores of each new format, all at the same time.
for arm in ship mix; do
  for format in f16 Q8_0 Q5_K_M Q4_K_M-imatrix; do
    bash scripts/lm-finetune2/wsl_eval_arm.sh "fmt-$arm-$format" "$out/fmt-$arm-$format.gguf" typed > "$out/eval-$arm-$format.log" 2>&1 &
  done
done
wait
echo "formats done"

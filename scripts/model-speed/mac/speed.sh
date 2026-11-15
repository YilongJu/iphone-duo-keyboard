#!/usr/bin/env bash
# The llama.cpp part of the speed test on the macOS runner, for .github/workflows/model-speed.yml.
# Usage, from the repository root: speed.sh WORK_DIR
#   WORK_DIR holds bin/speed_cli-b4846, bin/speed_cli-b12017 and gguf/*.gguf of the release.
# Each run reads the 486 requests of Shared/model-speed-requests.tsv at 2 threads, as on the
# desktop (scripts/model-speed/desktop/jobs/speed.sh). A run that fails writes its reason into
# its .log file and the others go on: llama.cpp b4846 cannot load Qwen3, and the
# GPU of the runner is a paravirtual device.
set -euo pipefail
work="$1"
out="$work/out"
requests="Shared/model-speed-requests.tsv"
mkdir -p "$out"

run() {
  local name="$1" version="$2" device="$3" model="$4" setting="${5:-}"
  if env $setting "$work/bin/speed_cli-$version" "$model" 2 "$device" "$requests" "$out/$name" 2> "$out/$name.log"; then
    echo "done $name"
  else
    echo "FAILED $name: $(tail -n 1 "$out/$name.log")"
  fi
}

run shipped.Q4_K_M.b4846 b4846 cpu Shared/smollm2-lora-domain-s100-seed1.Q4_K_M.gguf
run shipped.Q4_K_M.b12017 b12017 cpu Shared/smollm2-lora-domain-s100-seed1.Q4_K_M.gguf
run shipped.Q4_K_M.b4846-gpu b4846 gpu Shared/smollm2-lora-domain-s100-seed1.Q4_K_M.gguf
run shipped.Q4_K_M.b12017-gpu b12017 gpu Shared/smollm2-lora-domain-s100-seed1.Q4_K_M.gguf
for file in "$work"/gguf/*.gguf; do
  name=$(basename "$file" .gguf)
  run "$name.b4846" b4846 cpu "$file"
  run "$name.b12017" b12017 cpu "$file"
  run "$name.b12017-norepack" b12017 cpu "$file" DUO_LM_NO_REPACK=1
done

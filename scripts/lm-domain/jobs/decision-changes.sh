#!/usr/bin/env bash
# Job: counts the corrections where the Q4_K_M file of an arm takes another reading than its F32
# file with a 32-bit cache, with the apostrophe step on (WSL). Four runs work at the same time,
# each on some sets and with its own copy of the answers of the Q4_K_M file. A run with a
# corrections.jsonl.gz is left out. The F32 file is build/lm-domain/f32/ARM.f32.gguf.
# Usage: decision-changes.sh ARM Q4_FILE WEIGHT FROM_TYPED TO_TYPED OTHER SPACE_AFTER LEAD
set -euo pipefail
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
arm="$1"; model="${2/#\~/$HOME}"; shift 2
setting="$1 $2 $3 $4 $5"; lead="$6"
out="build/lm-domain/decisions/$arm"
mkdir -p "$out"
part=0
for sets in "dev" "domain_dev" "github_select published_dev apostrophe_word apostrophe_next_word" "stream_select domain_stream_dev"; do
  part=$((part + 1))
  if [ -f "$out/part-$part/corrections.jsonl.gz" ]; then continue; fi
  mkdir -p "$out/part-$part"
  if [ ! -f "$out/part-$part/answers-q4.jsonl" ]; then cp "build/lm-domain/results/$arm/answers.jsonl" "$out/part-$part/answers-q4.jsonl"; fi
  # shellcheck disable=SC2086
  nice -n 10 python3 scripts/lm-domain/decision_changes.py --shim "$HOME/lmdom/bin/libduo_shim.so" --lm "$HOME/lmdom/bin/lm_score" \
    --model "$model" --q4-answers "$out/part-$part/answers-q4.jsonl" --reference-lm "$HOME/lmft2/kv-test/lm_score_kv32_plain" \
    --reference-model "build/lm-domain/f32/$arm.f32.gguf" --setting $setting --lead "$lead" --sets $sets \
    --data build/lm-domain/data --out "$out/part-$part" > "$out/part-$part/log.txt" 2>&1 &
done
wait
python3 scripts/lm-domain/decision_changes.py --merge "$out"

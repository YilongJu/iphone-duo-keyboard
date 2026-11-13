#!/usr/bin/env bash
# Job: the one read of the confirmation set, for the committed plan (WSL). It first reads the
# engine's readings of the seven files in several processes, then types them for every arm.
# Usage: read-confirm.sh PLAN_SHA256, the value in the message of the commit that holds the plan.
set -euo pipefail
plan_sha256="$1"
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
set_folder=build/lm-domain/data/confirm-holdout
python3 scripts/lm-domain/warm_readings.py --shim "$HOME/lmdom/bin/libduo_shim.so" --data build/lm-domain/data --workers 12 \
  --extra-cases "$set_folder/cases.generated.confirm.jsonl" "$set_folder/cases.stream.confirm.jsonl" "$set_folder/cases.github.confirm.jsonl" \
  "$set_folder/cases.birkbeck.confirm.jsonl" "$set_folder/cases.domain.confirm.jsonl" "$set_folder/cases.domain-stream.confirm.jsonl" \
  "$set_folder/cases.real-word.confirm.jsonl"
python3 scripts/lm-domain/read_fresh_holdout.py --plan scripts/lm-domain/confirm-plan.json --shim "$HOME/lmdom/bin/libduo_shim.so" \
  --lm "$HOME/lmdom/bin/lm_score" --data build/lm-domain/data --threads 2 --workers 6 --out build/lm-domain/confirm-read --plan-sha256 "$plan_sha256"

#!/usr/bin/env bash
# Job: the one read of the fresh held-out set, for the committed plan (WSL). It first reads the
# engine's readings of the six files in several processes, then types them for every arm.
set -euo pipefail
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
fresh=build/lm-domain/data/fresh-holdout
python3 scripts/lm-domain/warm_readings.py --shim "$HOME/lmdom/bin/libduo_shim.so" --data build/lm-domain/data --workers 12 \
  --extra-cases "$fresh/cases.generated.fresh.jsonl" "$fresh/cases.stream.fresh.jsonl" "$fresh/cases.github.fresh.jsonl" \
  "$fresh/cases.birkbeck.fresh.jsonl" "$fresh/cases.domain.fresh.jsonl" "$fresh/cases.domain-stream.fresh.jsonl"
python3 scripts/lm-domain/read_fresh_holdout.py --plan scripts/lm-domain/holdout-plan.json --shim "$HOME/lmdom/bin/libduo_shim.so" \
  --lm "$HOME/lmdom/bin/lm_score" --data build/lm-domain/data --threads 2 --workers 8 --out build/lm-domain/holdout-read

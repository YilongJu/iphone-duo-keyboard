#!/usr/bin/env bash
# Job: writes the plan of the one read of the fresh held-out set from the pick under the parity
# reading that decides it (WSL, where the model files are).
set -euo pipefail
python3 scripts/lm-domain/make_holdout_plan.py --summary build/lm-domain/summary-parity-kv32/summary.json --data build/lm-domain/data \
  --also ship@ceiling-0.3 full-mix-seed1@shipped mix-hinge-seed1@shipped dom-s100-seed1@ceiling-0.3 dom-s100-seed1@shipped dom-s40-seed1@shipped

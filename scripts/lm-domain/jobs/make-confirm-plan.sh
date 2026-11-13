#!/usr/bin/env bash
# Job: writes the plan of the one read of the confirmation set (WSL, where the model files are).
# The candidate is the pick of summarize3.py with the paired dev comparison in condition 6, and
# the job stops unless that pick is the entry that the design names. The arms after --also are
# in the plan for the report only.
set -euo pipefail
python3 scripts/lm-domain/make_holdout_plan.py --summary build/lm-domain/summary-paired/summary.json --data build/lm-domain/data \
  --set-folder confirm-holdout --label confirm --out scripts/lm-domain/confirm-plan.json \
  --rule 'docs/lm-domain-design.md, section "Confirmation round of `dom-s100-seed1`"' \
  --expect-candidate dom-s100-seed1@ceiling-0.3 \
  --also dom-s100-seed1@shipped dom-s100-seed2@ceiling-0.3 dom-s100-seed3@ceiling-0.3 soup-mix@ceiling-0.3

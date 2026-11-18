#!/usr/bin/env bash
# Job: every run of the dev halves that needs no choice: the blocks and places of the shipped
# model, then the texts of the first measurement and the other model files (job_rest.sh).
# The job is safe to start again. Start it detached, from Windows:
#   powershell -File scripts/lm-domain/detach.ps1 -Name bench-dev -Where wsl -Script scripts/prediction-strip/benchmark/job_dev.sh
set -euo pipefail
here=scripts/prediction-strip/benchmark
if [ ! -f build/prediction-strip/bench/places/shipped.mobile.dev.npy ] || [ ! -f build/prediction-strip/bench/places/shipped.technical.dev.npy ]; then
  bash "$here/job_blocks.sh" shipped "$HOME/lmdom/models/dom-s100-seed1.Q4_K_M.gguf" dev 6
  bash "$here/job_places.sh" shipped dev
fi
bash "$here/job_rest.sh"

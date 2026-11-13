#!/usr/bin/env bash
# Job: the scoring queue of scripts/lm-domain/eval-queue.json (WSL).
# Usage: eval.sh PARALLEL WAIT_HOURS THREADS
set -euo pipefail
python3 scripts/lm-domain/run_eval_queue.py --queue scripts/lm-domain/eval-queue.json --parallel "$1" --wait-hours "$2" --threads "$3"

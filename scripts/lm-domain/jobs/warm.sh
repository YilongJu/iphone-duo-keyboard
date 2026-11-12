#!/usr/bin/env bash
# Job: the engine readings of every tuning and evaluation set, for score_model.py (WSL).
# Usage: warm.sh WORKERS [extra case files]
set -euo pipefail
workers="$1"; shift
extra=()
if [ "$#" -gt 0 ]; then extra=(--extra-cases "$@"); fi
nice -n 5 python3 scripts/lm-domain/warm_readings.py --shim "$HOME/lmdom/bin/libduo_shim.so" --data build/lm-domain/data --workers "$workers" "${extra[@]}"

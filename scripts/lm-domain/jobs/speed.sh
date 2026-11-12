#!/usr/bin/env bash
# Job: the time per training step at three micro-batch sizes, one run at a time (Git Bash).
# Usage: speed.sh QUEUE_FILE PARALLEL
set -euo pipefail
build/lm-domain/venv/Scripts/python.exe scripts/lm-domain/run_train_queue.py --queue "$1" \
  --lock D:/Github/iphone-duo-keyboard/build/gpu.lock --parallel "$2" --no-post

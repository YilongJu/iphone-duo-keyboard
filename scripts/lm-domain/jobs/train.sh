#!/usr/bin/env bash
# Job: the training queue of scripts/lm-domain/train-queue.json (Git Bash).
# Usage: train.sh PARALLEL WAIT_HOURS
set -euo pipefail
build/lm-domain/venv/Scripts/python.exe scripts/lm-domain/run_train_queue.py --queue scripts/lm-domain/train-queue.json \
  --lock D:/Github/iphone-duo-keyboard/build/gpu.lock --parallel "$1" --wait-hours "$2"

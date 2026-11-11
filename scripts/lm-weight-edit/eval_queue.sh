#!/usr/bin/env bash
# Runs eval_edit.sh for several arms in WSL, at most JOBS at once. Each arm waits until its
# conversion has finished (the Q3_K_M parity scores exist), so the queue can start while
# convert_edit.sh still works through the list.
# Usage, inside WSL: eval_queue.sh JOBS NAME [NAME ...]
set -uo pipefail
jobs_at_once="$1"; shift
here="$(cd "$(dirname "$0")" && pwd)"
models=/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit/build/lm-weight-edit/models
for name in "$@"; do
  until [ -s "$models/$name/parity/llama-scores-quant.txt" ] && [ -s "$HOME/lmedit/models/$name.Q3_K_M.gguf" ]; do sleep 20; done
  while [ "$(jobs -rp | wc -l)" -ge "$jobs_at_once" ]; do sleep 20; done
  echo "start $name"
  ( bash "$here/eval_edit.sh" "$name" "$name.Q3_K_M.gguf" 2 | sed "s/^/$name /" ) &
done
wait
echo "queue done"

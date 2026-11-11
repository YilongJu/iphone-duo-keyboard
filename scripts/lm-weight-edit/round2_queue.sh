#!/usr/bin/env bash
# Runs the evaluations of the design's interpolation part and its controls in WSL, at most JOBS at
# once, each with 2 threads at the lowest priority. An arm waits until its conversion has
# finished (export_convert.sh). A finished arm is skipped, so the queue can be started again
# after a stop. Start one queue only: two queues with the same group run the same arm twice.
# Use JOBS = 4 on the working desktop. Seventeen jobs at once took the load to 28 of 32 threads.
# Usage, inside WSL: round2_queue.sh JOBS GROUP [GROUP ...]
#   GROUP is one of: references, s-wise, d-wise, d2-wise, s-random, d-random
#   d-random holds seed 1 too (d-random-1.0), which does not have a dev score yet.
set -uo pipefail
jobs_at_once="$1"; shift
here="$(cd "$(dirname "$0")" && pwd)"
models=/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit/build/lm-weight-edit/models
grid="0.1 0.2 0.3 0.4 0.5 0.6 0.7 0.8 0.9"
# The common setting of a base is the tuned setting of its a = 1 fine-tune (result.json of that run).
common_s='{"weight": 1.5, "margin_from_typed": 2, "margin_to_typed": 4, "margin_other": 2, "space_after": 1}'
common_d='{"weight": 1.5, "margin_from_typed": 1, "margin_to_typed": 4, "margin_other": 2, "space_after": 1}'
common_d2='{"weight": 1.0, "margin_from_typed": 1, "margin_to_typed": 0, "margin_other": 0, "space_after": 1}'

wait_for_slot() { while [ "$(jobs -rp | wc -l)" -ge "$jobs_at_once" ]; do sleep 15; done; }

# evaluate.py, then eval_extra.py with the common setting when one is given.
arm() {
  local name="$1" common="${2:-}"
  # check_parity.py writes parity.json last, so a stopped conversion does not count.
  until [ -s "$models/$name/parity/parity.json" ] && [ -s "$HOME/lmedit/models/$name.Q3_K_M.gguf" ]; do sleep 20; done
  wait_for_slot
  (
    if [ ! -s "$HOME/lmedit/results/$name/result.json" ]; then
      bash "$here/eval_edit.sh" "$name" "$name.Q3_K_M.gguf" 2 | sed "s/^/$name /"
    fi
    if [ -n "$common" ] && [ ! -s "$HOME/lmedit/extra/$name/extra.json" ]; then
      bash "$here/eval_extra.sh" "$name" "$HOME/lmedit/results/$name" "$HOME/lmedit/models/$name.Q3_K_M.gguf" 2 \
        --common-setting "$common" | sed "s/^/$name extra /"
    fi
  ) &
}

# eval_extra.py for a run that exists already: the a = 0 and a = 1 rows.
reference() {
  local out_name="$1" run_dir="$2" model="$3"; shift 3
  wait_for_slot
  ( [ -s "$HOME/lmedit/extra/$out_name/extra.json" ] || bash "$here/eval_extra.sh" "$out_name" "$run_dir" "$model" 2 "$@" | sed "s/^/$out_name extra /" ) &
}

for group in "$@"; do
  case "$group" in
    references)
      reference s-lora "$HOME/lmedit/results/smollm2-lora-seed1-q3" "$HOME/lmedit/models/smollm2-lora-seed1.Q3_K_M.gguf" --weight-candidates
      reference d-lora "$HOME/lmft/results/lora-seed1" "$HOME/lmft/models/lora-seed1.Q3_K_M.gguf" --weight-candidates
      reference d2-lora "$HOME/lmft/results/lora-seed2" "$HOME/lmft/models/lora-seed2.Q3_K_M.gguf" --weight-candidates
      reference s-stock "$HOME/lmedit/results/smollm2-stock-q3" "$HOME/lmedit/models/smollm2-stock.Q3_K_M.gguf" --common-setting "$common_s"
      reference d-stock "$HOME/lmft/results/stock-typed" "$HOME/lmft/models/distilgpt2.Q3_K_M.gguf" --common-setting "$common_d"
      reference d2-stock "$HOME/lmft/results/stock-typed" "$HOME/lmft/models/distilgpt2.Q3_K_M.gguf" --common-setting "$common_d2" ;;
    s-wise) for a in $grid; do arm "s-wise-$a" "$common_s"; done ;;
    d-wise) for a in $grid; do arm "d-wise-$a" "$common_d"; done ;;
    d2-wise) for a in $grid; do arm "d2-wise-$a" "$common_d2"; done ;;
    s-random) for seed in 2 3 4 5; do arm "s-random-1.0-seed$seed"; done ;;
    d-random) arm d-random-1.0; for seed in 2 3 4 5; do arm "d-random-1.0-seed$seed"; done ;;
    *) echo "unknown group $group"; exit 2 ;;
  esac
done
wait
echo "queue done"

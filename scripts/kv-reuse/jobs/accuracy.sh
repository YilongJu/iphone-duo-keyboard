#!/usr/bin/env bash
# Job: the replay of every approach, all at once, each at 2 threads, for the accuracy counts of
# docs/kv-reuse-results.md. Each run with reuse has the check of the cache with an infinite
# tolerance, so it records the widest difference from a fresh read and does not stop on one.
# A finished run (its result.json) is kept, so the job can start again after a restart.
# Usage, from the repository root in WSL: accuracy.sh EVERYDAY_FOLDER [EVERY]
set -euo pipefail
everyday="$1"
every="${2:-1}"
kv="${KV:-$HOME/kvreuse}"
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
bash scripts/kv-reuse/jobs/build.sh
out="$kv/accuracy"
mkdir -p "$out"
run() {
  local name="$1" program="$2" mode="$3" slots="$4"
  local dir="$out/$name"
  if [ -f "$dir/result.json" ]; then echo "kept $name"; return 0; fi
  local check=()
  [ "$mode" != none ] && check=(--check inf)
  python3 scripts/kv-reuse/replay.py --shim "$kv/bin/libduo_shim.so" --program "$kv/bin/$program" \
    --model "$kv/model.gguf" --threads 2 --mode "$mode" --slots "$slots" "${check[@]}" \
    --everyday "$everyday" --out "$dir" --every "$every" > "$dir.log" 2>&1 && echo "done $name" || { echo "FAILED $name"; tail -5 "$dir.log"; return 1; }
}
pids=()
run A kv_replay none 1 & pids+=($!)
run B kv_replay prefix 1 & pids+=($!)
run C kv_replay shift 1 & pids+=($!)
run D kv_replay anchor 1 & pids+=($!)
run BE kv_replay prefix 2 & pids+=($!)
run CE kv_replay shift 2 & pids+=($!)
run DE kv_replay anchor 2 & pids+=($!)
run B1 kv_replay-min1 prefix 1 & pids+=($!)
status=0
for pid in "${pids[@]}"; do wait "$pid" || status=1; done
exit $status

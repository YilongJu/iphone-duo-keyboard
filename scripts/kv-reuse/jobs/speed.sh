#!/usr/bin/env bash
# Job: the speed pass of docs/kv-reuse-design.md. The requests of approach A's replay go in order
# through each approach, one approach at a time, at 2 threads, without the check of the cache.
# Run it alone on the machine. A finished approach (its .done file) is kept, so the job can start
# again after a restart. Approach A runs first and again last, to show the drift of the machine.
# Usage, from the repository root in WSL, after jobs/accuracy.sh: speed.sh
set -euo pipefail
kv="${KV:-$HOME/kvreuse}"
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
requests="$kv/accuracy/A/requests.tsv"
[ -f "$kv/accuracy/A/result.json" ] || { echo "the replay of A has not finished"; exit 1; }
out="$kv/speed"
mkdir -p "$out"
run() {
  local name="$1" program="$2" mode="$3" slots="$4"
  if [ -f "$out/$name.done" ]; then echo "kept $name"; return 0; fi
  "$kv/bin/$program" "$kv/model.gguf" 2 "$mode" "$slots" 17 times "$out/$name.times" < "$requests" \
    2> "$out/$name.log" | tail -n +2 > "$out/$name.answers"
  [ "$(wc -l < "$out/$name.answers")" = "$(wc -l < "$requests")" ] || { echo "FAILED $name"; cat "$out/$name.log"; exit 1; }
  date -Is > "$out/$name.done"
  echo "done $name"
}
run A kv_replay none 1
run B kv_replay prefix 1
run C kv_replay shift 1
run D kv_replay anchor 1
run BE kv_replay prefix 2
run CE kv_replay shift 2
run DE kv_replay anchor 2
run B1 kv_replay-min1 prefix 1
run A-again kv_replay none 1

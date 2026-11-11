#!/usr/bin/env bash
# Runs one command while holding the shared GPU lock file build/gpu.lock of the main checkout.
# The lock is created exclusively. When another worker holds it, this script retries every
# minute. It never deletes a lock it did not create: a lock older than 3 hours stops the script
# with the lock's content, for a person to read.
# Usage, from Git Bash: with_gpu_lock.sh "PURPOSE" COMMAND [ARGUMENTS ...]
set -uo pipefail
purpose="$1"; shift
lock=/d/Github/iphone-duo-keyboard/build/gpu.lock
while true; do
  if ( set -o noclobber; printf 'owner: lm-edit worker (weight-edit experiment, branch engine/lm-edit)\npurpose: %s\nstarted: %s\n' \
       "$purpose" "$(date '+%Y-%m-%d %H:%M:%S %z')" > "$lock" ) 2> /dev/null; then
    break
  fi
  age=$(( $(date +%s) - $(stat -c %Y "$lock") ))
  if [ "$age" -gt 10800 ]; then
    echo "the GPU lock is $age s old, over 3 hours; it is left in place:" >&2
    cat "$lock" >&2
    exit 3
  fi
  echo "GPU lock held ($age s old), retry in 60 s: $(head -n 2 "$lock" | tr '\n' ' ')"
  sleep 60
done
trap 'rm -f "$lock"' EXIT
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
"$@"
status=$?
exit $status

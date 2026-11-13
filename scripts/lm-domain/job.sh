#!/usr/bin/env bash
# Runs one job script with its log and its state file, for scripts/lm-domain/detach.ps1.
# Usage: job.sh NAME SCRIPT [arguments of the script]
# The log is build/lm-domain/logs/NAME.log. build/lm-domain/state/NAME.done holds the exit code
# and the end time, and it exists only after the job ended.
name="$1"; script="$2"; shift 2
root="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$root/build/lm-domain/state" "$root/build/lm-domain/logs"
cd "$root"
echo "==== $(date -Is) start of $name: $script $*" >> "build/lm-domain/logs/$name.log"
bash "$script" "$@" >> "build/lm-domain/logs/$name.log" 2>&1
code=$?
echo "==== $(date -Is) end of $name with exit code $code" >> "build/lm-domain/logs/$name.log"
echo "exit $code $(date -Is)" > "build/lm-domain/state/$name.done"

#!/usr/bin/env bash
# Runs scripts/typing-evaluation/score.py for each engine name and half under an output folder.
#
# Usage, from the repository root: score_outputs.sh build/typing-evaluation
#
# An engine name that typed a sample of the cases holds the sample as TASK.HALF.cases.jsonl, and
# the script scores against that file. Every other engine name is scored against all cases of
# the half in scripts/typing-evaluation/cases. The summary goes to TASK.HALF.summary.json.
set -euo pipefail

out="$1"
for predictions in "$out"/*/*.jsonl; do
  case "$predictions" in
    *.cases.jsonl | *.detail.jsonl) continue ;;
  esac
  folder=$(dirname "$predictions")
  engine=$(basename "$folder")
  stem=$(basename "$predictions" .jsonl)
  task=${stem%%.*}
  if [ -f "$folder/$stem.cases.jsonl" ]; then
    cases="$folder/$stem.cases.jsonl"
  else
    cases="scripts/typing-evaluation/cases/$stem.jsonl"
  fi
  python3 scripts/typing-evaluation/score.py --task "$task" --engine "$engine" \
    --cases "$cases" --predictions "$predictions" --json "$folder/$stem.summary.json"
  echo
done

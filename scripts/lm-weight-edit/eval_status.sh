#!/usr/bin/env bash
# Prints the progress and result lines of every evaluate.py run under ~/lmedit/results (WSL).
for f in "$HOME"/lmedit/results/*.log; do
  echo "== $(basename "$f")"
  grep -E '^(control|tuned)|setting [0-9]+ of|Error|Traceback' "$f" | tail -2 | cut -c1-400
done

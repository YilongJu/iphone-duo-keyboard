#!/usr/bin/env bash
# The one read of the held-out set with the committed plan, then its tables.
#
# Usage, in WSL:
#   bash scripts/lm-finetune2/wsl_read_holdout.sh dry                      a check on the selection files
#   bash scripts/lm-finetune2/wsl_read_holdout.sh SHA256_OF_THE_PLAN         the read
#   bash scripts/lm-finetune2/wsl_read_holdout.sh SHA256_OF_THE_PLAN resume  go on with a read that stopped
#
# The SHA-256 of the committed plan comes from Windows, because git in WSL cannot read this worktree:
#   git show HEAD:scripts/lm-finetune2/holdout-plan.json | sha256sum
# The read writes only into ~/lmft2/holdout: the outputs, read.log, read-log.jsonl, result.json and
# the folder summary. A read that stops can go on with "resume": read_holdout.py keeps every whole
# file and scores the others. The script counts right cases once, when every file is whole.
#
# To start the read apart from the terminal, so that it lives on when the terminal closes, from
# PowerShell on Windows:
#   Start-Process -WindowStyle Hidden wsl.exe -ArgumentList '-d','Ubuntu','--','bash',
#     '/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune2/scripts/lm-finetune2/wsl_read_holdout.sh','SHA256','resume'
set -euo pipefail
cd /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune2
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
plan=scripts/lm-finetune2/holdout-plan.json
if [ "${1:-}" = "dry" ]; then
  python3 - <<'PY'
import json
plan = json.load(open("scripts/lm-finetune2/holdout-plan.json"))
plan["arms"] = [arm for arm in plan["arms"] if arm["name"] in ("control", "ship", "smollm2-lora-seed1-calibrated")]
json.dump(plan, open("/root/lmft2/dry-plan.json", "w"))
PY
  rm -rf "$HOME/lmft2/holdout-dry"
  nice -n 19 python3 scripts/lm-finetune2/read_holdout.py --plan "$HOME/lmft2/dry-plan.json" --shim "$HOME/lmft/bin/libduo_shim.so" \
    --lm "$HOME/lmft/bin/lm_score" --models "$HOME/lmft/models" --models "$HOME/lmft2/models" --data build/lm-finetune2/data \
    --threads 2 --workers 2 --dry-run-on-select --out "$HOME/lmft2/holdout-dry" 2>&1 | grep -v "repaired"
  exit 0
fi
committed="${1:?give the SHA-256 of the committed plan}"
mode="${2:-}"
out="$HOME/lmft2/holdout"
mkdir -p "$out"
exec >> "$out/read.log" 2>&1
echo "$(date -Is) wsl_read_holdout.sh starts, mode '${mode}', process $$"
[ "$(sha256sum < "$plan" | cut -d" " -f1)" = "$committed" ] || { echo "the plan differs from the committed plan"; exit 1; }
resume=()
if [ "$mode" = "resume" ]; then
  resume=(--resume)
elif [ -n "$mode" ]; then
  echo "unknown mode '${mode}'"; exit 1
fi
if [ -e "$out/result.json" ]; then
  echo "result.json exists: the read is whole, and it does not run again"
else
  nice -n 19 python3 scripts/lm-finetune2/read_holdout.py --plan "$plan" --shim "$HOME/lmft/bin/libduo_shim.so" \
    --lm "$HOME/lmft/bin/lm_score" --models "$HOME/lmft/models" --models "$HOME/lmft2/models" --data build/lm-finetune2/data \
    --threads 2 --workers 8 "${resume[@]}" --out "$out" 2>&1 | grep -v "repaired"
fi
# The tables, once. They stay in the folder of the read.
if [ ! -e "$out/summary/holdout-summary.md" ]; then
  nice -n 19 python3 scripts/lm-finetune2/summarize2.py holdout --round1 ../lm-finetune --data build/lm-finetune2/data \
    --read "$out" --plan "$plan" --out "$out/summary" > "$out/summarize.log" 2>&1
fi
echo "$(date -Is) held-out read and tables done"

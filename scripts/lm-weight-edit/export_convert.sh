#!/usr/bin/env bash
# Exports each named arm on the processor (no GPU), converts it to f16 and Q3_K_M with
# convert_edit.sh, and checks parity. One call is one stream: it works through the names in order.
# An arm counts as converted when check_parity.py has written parity/parity.json and the Q3_K_M
# file is in WSL. The parity check writes that file last, so a stopped conversion does not have
# it, and this script converts that arm again from the export.
# Usage, from Git Bash:
#   export_convert.sh BASE ARMS_JSON NAME [NAME ...]   BASE is smollm2-135m or distilgpt2
#   export_convert.sh --status NAME [NAME ...]         prints the state of each arm and changes nothing
set -uo pipefail
cd /d/Github/iphone-duo-keyboard/build/worktrees/lm-edit
PY=../lm-finetune/build/lm-finetune/venv/Scripts/python.exe

# Prints converted, partial or absent for one arm.
state_of() {
  local name="$1" model="build/lm-weight-edit/models/$1"
  if [ -s "$model/parity/parity.json" ] && \
     MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash -lc "test -s ~/lmedit/models/$name.Q3_K_M.gguf" < /dev/null; then
    echo converted
  elif [ -d "$model" ]; then
    echo partial
  else
    echo absent
  fi
}

if [ "$1" = "--status" ]; then
  shift
  for name in "$@"; do echo "$name $(state_of "$name")"; done
  exit 0
fi

base="$1"; arms="$2"; shift 2
for name in "$@"; do
  model=build/lm-weight-edit/models/$name
  if [ "$(state_of "$name")" = converted ]; then echo "$name already converted"; continue; fi
  mkdir -p "$model"
  if ! $PY scripts/lm-weight-edit/sweep.py --base "$base" --arms "$arms" --device cpu --export "$name" \
      --export-dir "$model/hf" > "$model/export.log" 2>&1; then echo "$name EXPORT FAILED"; tail -3 "$model/export.log"; continue; fi
  bash scripts/lm-weight-edit/convert_edit.sh "$name" > "$model/parity-compare.txt" 2>&1
  status=$?
  echo "$name convert exit $status: $(tail -2 "$model/parity-compare.txt" | tr '\n' ' ')"
  # The f16 file stays on D:. Its WSL copy is removed, because the WSL disk is nearly full.
  MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash -lc "rm -f ~/lmedit/models/$name.f16.gguf" < /dev/null
done
echo "stream done"

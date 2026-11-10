#!/usr/bin/env bash
# Runs one English baseline engine on the dev half and the test half, then scores both halves.
# The cases are the generated cases and the cases from published misspelling lists. Run
# scripts/typing-evaluation/build_external_english_cases.py first, which writes the second group.
#
# Usage, from the repository root:
#   PYTHON=build/venv/bin/python bash scripts/typing-evaluation/engines/english-baselines/run_and_score.sh ENGINE [adapter options]
#
# PYTHON names the interpreter that holds the engine. The adapter options go to
# run_english_baselines.py, for example --workers 4 or --jamspell-model build/jamspell/en.bin.
set -euo pipefail

engine="${1:?give the engine name as the first argument}"
shift
python="${PYTHON:?set PYTHON to the interpreter that holds the engine}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
evaluation="$(cd "$here/../.." && pwd)"

"$python" "$here/run_english_baselines.py" --engine "$engine" --half dev test --with-external-cases "$@"
for half in dev test; do
  "$python" "$evaluation/score.py" --task english --engine "$engine" \
    --cases "$evaluation/cases/english.$half.jsonl" "build/typing-evaluation/external/english.$half.jsonl" \
    --predictions "build/typing-evaluation/$engine/english.$half.jsonl" \
    --json "build/typing-evaluation/$engine/english.$half.summary.json"
done

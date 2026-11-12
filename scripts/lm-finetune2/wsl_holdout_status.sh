#!/usr/bin/env bash
# The state of the held-out read, from file names and line counts only. The script does not open a
# result for its content, and it does not count right cases.
# Usage, in WSL: bash scripts/lm-finetune2/wsl_holdout_status.sh
cd /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune2
python3 - <<'PY'
import json
from pathlib import Path

out = Path.home() / "lmft2" / "holdout"
data = Path("build/lm-finetune2/data")
files = {"generated": "cases.generated.holdout.jsonl", "stream": "cases.stream.holdout.jsonl",
         "github": "cases.github.holdout.jsonl", "mitton": "cases.mitton-remainder.holdout.jsonl"}
cases = {name: sum(1 for line in (data / file).open(encoding="utf-8") if line.strip()) for name, file in files.items()}
plan = json.loads(Path("scripts/lm-finetune2/holdout-plan.json").read_text(encoding="utf-8"))
complete = 0
for arm in plan["arms"]:
    states = []
    for name, count in cases.items():
        path = out / f"{arm['name']}.{name}.jsonl"
        if not path.exists():
            states.append(f"{name}: missing")
            continue
        lines = sum(1 for line in path.open(encoding="utf-8") if line.strip())
        states.append(f"{name}: {'complete' if lines == count else f'{lines} of {count} lines'}")
        complete += lines == count
    print(f"{arm['name']}: " + ", ".join(states))
print(f"{complete} of {len(plan['arms']) * len(cases)} files complete; result.json {'exists' if (out / 'result.json').exists() else 'does not exist'}")
print("other files:", sorted(p.name for p in out.iterdir() if not p.name.endswith(".jsonl")))
PY
ps -eo etime,pcpu,nlwp,cmd | grep -E "[r]ead_holdout|[l]m_score" | cut -c1-150
uptime

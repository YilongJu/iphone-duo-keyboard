#!/usr/bin/env bash
# Tests the held-out tables of summarize2.py on the selection files, never on the held-out files.
# It builds a folder with the shape of a held-out read from the selection outputs of evaluate2.py:
#   generated <- the generated dev half, stream <- the select stream, github <- the select half of
#   the GitHub typos, mitton <- the published dev misspellings.
# Then it runs "summarize2.py holdout" on that folder and compares its rows with pick.json, which
# "summarize2.py pick" made from the same outputs by another path.
# Usage, in WSL: bash scripts/lm-finetune2/wsl_test_summary.sh
set -euo pipefail
cd /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune2
work="$HOME/lmft2/summary-test"
rm -rf "$work"
mkdir -p "$work/data" "$work/read"
cat scripts/typing-evaluation/cases/english.dev.jsonl scripts/typing-evaluation/cases/english-symbols.dev.jsonl > "$work/data/cases.generated.holdout.jsonl"
cp build/lm-finetune2/data/cases.stream.select.jsonl "$work/data/cases.stream.holdout.jsonl"
cp build/lm-finetune2/data/cases.github.select.jsonl "$work/data/cases.github.holdout.jsonl"
cp ../lm-finetune/build/typing-evaluation/external/english.dev.jsonl "$work/data/cases.mitton-remainder.holdout.jsonl"
ln -s "$PWD/build/lm-finetune2/data/cases2.train.jsonl" "$PWD/build/lm-finetune2/data/lists2.train.jsonl.gz" \
  "$PWD/build/lm-finetune2/data/lists2.stop.jsonl.gz" "$work/data/"
python3 - "$work" <<'PY'
import json, shutil, sys
from pathlib import Path
work = Path(sys.argv[1])
results = Path.home() / "lmft2" / "results"
plan = json.loads(Path("scripts/lm-finetune2/holdout-plan.json").read_text())
source = {"control": ("smollm2-lora-seed1-calibrated", "control"), "ship": ("smollm2-lora-seed1-calibrated", "ship"),
          "smollm2-lora-seed1-calibrated": ("smollm2-lora-seed1-calibrated", "tuned"),
          "smollm2-lora-mix-seed1": ("smollm2-lora-mix-seed1", "tuned"), "smollm2-full-mix-seed1": ("smollm2-full-mix-seed1", "tuned")}
plan["arms"] = [arm for arm in plan["arms"] if arm["name"] in source]
plan["candidate"] = "smollm2-full-mix-seed1"
files = {"generated": "dev", "stream": "stream", "github": "github", "mitton": "published_dev"}
for arm, (folder, label) in source.items():
    for shape, name in files.items():
        shutil.copy(results / folder / f"{label}.{name}.jsonl", work / "read" / f"{arm}.{shape}.jsonl")
(work / "plan.json").write_text(json.dumps(plan))
(work / "read" / "result.json").write_text(json.dumps({"plan": plan, "arms": {arm: {"stream": {}} for arm in source}}))
PY
python3 scripts/lm-finetune2/summarize2.py holdout --round1 ../lm-finetune --data "$work/data" --read "$work/read" \
  --plan "$work/plan.json" --out "$work/summary" > "$work/summary.log" 2>&1 || { tail -n 20 "$work/summary.log"; exit 1; }
python3 - "$work" <<'PY'
import json, sys
from pathlib import Path
work = Path(sys.argv[1])
summary = json.loads((work / "summary" / "holdout-summary.json").read_text())
pick = json.loads(Path("scripts/lm-finetune2/reports/pick.json").read_text())
pairs = {"control": "control", "ship": "ship", "smollm2-lora-mix-seed1": "smollm2-lora-mix-seed1:tuned",
         "smollm2-full-mix-seed1": "smollm2-full-mix-seed1:tuned"}
failures = []
for name, other in pairs.items():
    a = {k: v for k, v in summary["rows"][name].items() if k != "estimate"}
    b = {k: v for k, v in pick["rows"][other].items() if k != "estimate"}
    if a != b:
        failures.append(f"the row of {name} differs from pick.json: {[k for k in a if a[k] != b.get(k)]}")
dry = pick["dry_run_of_the_replacement_conditions_on_the_selection_sets"]["smollm2-full-mix-seed1:tuned"]
got = summary["decisions"]["ship"]
if got["conditions"] != dry["conditions"] or got["numbers"]["non_word_interval"] != dry["numbers"]["non_word_interval"]:
    failures.append("the six conditions of the candidate differ from the dry run of the pick")
if set(summary["decisions"]) != {"ship", "smollm2-lora-seed1-calibrated"}:
    failures.append("the decisions do not hold both references")
if set(summary["every_arm_against_ship"]) != {"smollm2-lora-seed1-calibrated", "smollm2-lora-mix-seed1", "smollm2-full-mix-seed1"}:
    failures.append("the table of every arm against ship holds other arms")
paired = summary["paired_against_ship"]["smollm2-full-mix-seed1"]
rows = summary["rows"]
for label, key in (("non-word slips", "non_word_slips"), ("real-word slips", "real_word_slip"), ("real misspellings", "real_misspellings")):
    if paired[label]["only_arm"] - paired[label]["only_reference"] != rows["smollm2-full-mix-seed1"][key] - rows["ship"][key]:
        failures.append(f"the paired counts of {label} do not add up to the difference of the rows")
if summary["paired_against_ship"]["smollm2-lora-seed1-calibrated"]["real misspellings"] != {"cases": 2251, "only_arm": 0, "only_reference": 0, "two_sided_p": 1.0}:
    failures.append("the paired counts of two equal arms are not zero")
text = (work / "summary" / "holdout-summary.md").read_text()
for label in ("Table A", "Table B", "Table C", "Table D", "Table F", "Table G", "Table H"):
    if label not in text:
        failures.append(f"{label} is missing")
print("seen:", json.dumps(summary["seen"])[:400])
print("FAIL: " + "; ".join(failures) if failures else "summary test passed: the rows and the six conditions equal the pick on the same outputs")
sys.exit(1 if failures else 0)
PY

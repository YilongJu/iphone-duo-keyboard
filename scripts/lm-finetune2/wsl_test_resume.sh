#!/usr/bin/env bash
# Tests the resume path of read_holdout.py on the selection files, never on the held-out files.
# It copies the folder of an earlier dry run (wsl_read_holdout.sh dry), removes result.json, deletes
# one file and cuts another one off in the middle of a line. Then it checks that
#   1. the read refuses the folder without --resume,
#   2. with --resume the read keeps the four whole files (same modification time),
#   3. it scores the two others again, and every file equals the file of the dry run byte for byte,
#   4. the counts of result.json equal the counts of the dry run.
# Usage, in WSL: bash scripts/lm-finetune2/wsl_test_resume.sh
set -euo pipefail
cd /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune2
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
source_folder="$HOME/lmft2/holdout-dry"
test_folder="$HOME/lmft2/resume-test"
[ -e "$source_folder/result.json" ] || { echo "run wsl_read_holdout.sh dry first"; exit 1; }
rm -rf "$test_folder"
cp -rp "$source_folder" "$test_folder"
rm -f "$test_folder/result.json" "$test_folder/read-log.jsonl" "$test_folder/model-stats.jsonl"
read_it() {
  nice -n 19 python3 scripts/lm-finetune2/read_holdout.py --plan "$HOME/lmft2/dry-plan.json" --shim "$HOME/lmft/bin/libduo_shim.so" \
    --lm "$HOME/lmft/bin/lm_score" --models "$HOME/lmft/models" --models "$HOME/lmft2/models" --data build/lm-finetune2/data \
    --threads 2 --workers 2 --dry-run-on-select --out "$test_folder" "$@" 2>&1 | grep -v "repaired"
}
echo "check 1: without --resume"
if read_it; then echo "FAIL: the read took a folder with files and without --resume"; exit 1; fi
rm "$test_folder/ship.github.jsonl"
head -c "$(( $(head -n 100 "$source_folder/control.stream.jsonl" | wc -c) + 17 ))" "$source_folder/control.stream.jsonl" > "$test_folder/control.stream.jsonl"
stat -c "%n %Y" "$test_folder"/*.jsonl | sort > "$test_folder/times-before.txt"
echo "check 2 and 3: with --resume"
read_it --resume
python3 - "$source_folder" "$test_folder" <<'PY'
import json, sys
from pathlib import Path
source, test = Path(sys.argv[1]), Path(sys.argv[2])
before = dict(line.rsplit(" ", 1) for line in (test / "times-before.txt").read_text().splitlines())
failures = []
names = sorted(p.name for p in source.glob("*.jsonl") if p.name not in ("read-log.jsonl", "model-stats.jsonl"))
for name in names:
    if (source / name).read_bytes() != (test / name).read_bytes():
        failures.append(f"{name} differs from the dry run")
    kept = name not in ("ship.github.jsonl", "control.stream.jsonl")
    same_time = before.get(str(test / name)) == str(int((test / name).stat().st_mtime))
    if kept and not same_time:
        failures.append(f"{name} was written again")
    if not kept and same_time:
        failures.append(f"{name} was not written again")
log = [json.loads(line) for line in (test / "read-log.jsonl").read_text().splitlines()]
events = sorted((row["arm"], row["set"], row["event"]) for row in log if "arm" in row)
print("events:", events)
wanted = sorted([("control", "github", "kept"), ("control", "stream", "deleted a file that was not whole"), ("control", "stream", "scored"),
                 ("ship", "stream", "kept"), ("ship", "github", "scored"), ("smollm2-lora-seed1-calibrated", "stream", "kept"),
                 ("smollm2-lora-seed1-calibrated", "github", "kept")])
if events != wanted:
    failures.append("the read log does not hold the wanted events")
old = json.loads((source / "result.json").read_text())
new = json.loads((test / "result.json").read_text())
for arm, sets in old["arms"].items():
    for name, entry in sets.items():
        a = {k: v for k, v in entry.items() if k != "model"}
        b = {k: v for k, v in new["arms"][arm][name].items() if k != "model"}
        if a != b:
            failures.append(f"the counts of {arm} on {name} differ")
print("model stats:", (test / "model-stats.jsonl").read_text().strip())
print("FAIL: " + "; ".join(failures) if failures else "resume test passed: 6 files equal the dry run, 4 kept and 2 scored again")
sys.exit(1 if failures else 0)
PY

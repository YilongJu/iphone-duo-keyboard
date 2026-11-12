#!/usr/bin/env bash
# Job: the lead of the apostrophe step for every scored arm of eval-queue.json (WSL), several arms
# at the same time. An arm waits until both parts of score_model.py are done, because both
# scripts write the arm's file of answers. An arm with an apostrophe.json is left out.
# Usage: tune-apostrophe.sh PARALLEL
set -uo pipefail
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
python3 - "$1" <<'PY'
import json, subprocess, sys, time
from pathlib import Path
parallel = int(sys.argv[1])
results = Path("build/lm-domain/results")
running = {}
while True:
    arms = json.loads(Path("scripts/lm-domain/eval-queue.json").read_text())["arms"]
    for name in [name for name, process in running.items() if process.poll() is not None]:
        print(name, "ended with exit code", running.pop(name).returncode, flush=True)
    waiting = [arm for arm in arms if not (results / arm["name"] / "apostrophe.json").exists() and arm["name"] not in running]
    ready = [arm for arm in waiting if (results / arm["name"] / "result-test.json").exists()]
    for arm in ready:
        if len(running) >= parallel:
            break
        log = open(f"build/lm-domain/logs/apostrophe-{arm['name']}.log", "a")
        running[arm["name"]] = subprocess.Popen(
            ["nice", "-n", "10", sys.executable, "scripts/lm-domain/tune_apostrophe.py", "--shim", str(Path("~/lmdom/bin/libduo_shim.so").expanduser()),
             "--lm", str(Path("~/lmdom/bin/lm_score").expanduser()), "--model", str(Path(arm["model"]).expanduser()),
             "--data", "build/lm-domain/data", "--out", str(results / arm["name"])], stdout=log, stderr=subprocess.STDOUT)
        print(arm["name"], "started", flush=True)
    if not running and not waiting:
        break
    time.sleep(60)
PY

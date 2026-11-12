"""Scores a queue of model files with score_model.py, several at the same time.

The queue file names the arms: {"arms": [{"name": NAME, "model": PATH}]}. A path may start with
~ for the home folder. Each arm has two runs: the part "select" of score_model.py, then the
part "test". Every waiting run of the part "select" starts before a run of the part "test",
because the choices of the round wait for the first part only. A run with a result file is
done, and the script leaves it out, so the queue is safe to start again. A run that a stop left
half done goes on from its stored answers of lm_score and from its grid rows. An arm whose
model file does not exist yet waits: the script reads the queue again every 2 minutes, so the
queue can run beside the training queue and an arm can join it. The script ends when every run
has a result, or when --wait-hours pass without a new start.

Usage, from the repository root, on Linux:
    python3 scripts/lm-domain/run_eval_queue.py --queue scripts/lm-domain/eval-queue.json --parallel 6
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "build" / "lm-domain" / "results"
LOGS = ROOT / "build" / "lm-domain" / "logs"


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--parallel", type=int, required=True)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--wait-hours", type=float, default=0.0, help="how long the script waits for a model file that is not there yet")
    parser.add_argument("--shim", type=Path, default=Path("~/lmdom/bin/libduo_shim.so"))
    parser.add_argument("--lm", type=Path, default=Path("~/lmdom/bin/lm_score"))
    parser.add_argument("--llama", type=Path, default=Path("~/lmft/llama/lib"))
    arguments = parser.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "LD_LIBRARY_PATH": str(arguments.llama.expanduser())}
    running: dict[tuple[str, str], subprocess.Popen] = {}
    failed: set[tuple[str, str]] = set()
    files = {"select": "result.json", "test": "result-test.json"}
    last_start = time.monotonic()
    while True:
        arms = json.loads(arguments.queue.read_text(encoding="utf-8"))["arms"]
        for key in [key for key, process in running.items() if process.poll() is not None]:
            code = running.pop(key).returncode
            print(f"{now()} {key[0]}, part {key[1]}: score_model.py ended with exit code {code}", flush=True)
            if code != 0:
                failed.add(key)
        waiting = []
        for part in ("select", "test"):
            for arm in arms:
                key = (arm["name"], part)
                folder = RESULTS / arm["name"]
                if (folder / files[part]).exists() or key in running or key in failed:
                    continue
                # The part "test" reads the settings of the part "select", and one arm has one run at a time.
                if part == "test" and (not (folder / files["select"]).exists() or (arm["name"], "select") in running):
                    continue
                waiting.append((arm, part))
        for arm, part in waiting:
            model = Path(arm["model"]).expanduser()
            if len(running) >= arguments.parallel or not model.exists():
                continue
            log = (LOGS / f"eval-{arm['name']}.log").open("a", encoding="utf-8")
            command = ["nice", "-n", "15", sys.executable, str(ROOT / "scripts" / "lm-domain" / "score_model.py"),
                       "--shim", str(arguments.shim.expanduser()), "--lm", str(arguments.lm.expanduser()), "--model", str(model),
                       "--threads", str(arguments.threads), "--data", str(ROOT / "build" / "lm-domain" / "data"),
                       "--name", arm["name"], "--part", part, "--out", str(RESULTS / arm["name"])]
            running[(arm["name"], part)] = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, env=environment)
            last_start = time.monotonic()
            print(f"{now()} {arm['name']}, part {part}: started on {model}", flush=True)
        if not running:
            still = sorted({arm["name"] for arm, _ in waiting if not Path(arm["model"]).expanduser().exists()})
            if not still or time.monotonic() - last_start > arguments.wait_hours * 3600:
                print(f"{now()} the queue is done; failed runs: {sorted(failed)}; arms without a model file: {still}", flush=True)
                break
        time.sleep(120)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

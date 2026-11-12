"""Runs the training queue of the domain round on the one GPU, in waves.

A wave holds up to --parallel arms that train at the same time (train3.py with
--lock-held-by-parent). The script takes the GPU lock for one wave and releases it after the
wave, then waits 90 seconds, so another user of the lock can take it between two waves. A wave
takes only as many arms as the free GPU memory holds: each arm needs its cap and a margin for
its CUDA context.

The queue file names the arms: {"common": [arguments of every arm], "arms": [{"name": NAME,
"memory_gb": 2.3, "arguments": [...]}]}. An arm with a train-result.json is done, and the script
leaves it out, so the queue is safe to start again. An arm that a stop left half done goes on
from its checkpoint.pt. After an arm trains, post_arm.sh converts and checks its model.

The script writes build/lm-domain/state/train-queue.status.json after every change.

Usage, from Git Bash at the root of the worktree:
    build/lm-domain/venv/Scripts/python.exe scripts/lm-domain/run_train_queue.py \
        --queue scripts/lm-domain/train-queue.json --lock D:/Github/iphone-duo-keyboard/build/gpu.lock --parallel 6
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune2"))
import gpu_lock  # noqa: E402

gpu_lock.NAME = "lm-domain (Claude agent, domain round of the re-ranker fine-tune)"
CONTEXT_MARGIN_MIB = 450
BETWEEN_WAVES_SECONDS = 90
BASH = r"C:\Program Files\Git\bin\bash.exe"
MODELS = ROOT / "build" / "lm-domain" / "models"
LOGS = ROOT / "build" / "lm-domain" / "logs"
STATUS = ROOT / "build" / "lm-domain" / "state" / "train-queue.status.json"


def gpu_used_mib() -> int:
    answer = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"],
                            capture_output=True, text=True, check=True)
    return int(answer.stdout.strip())


def done(arm: dict) -> bool:
    return (MODELS / arm["name"] / "train-result.json").exists()


def write_status(status: dict) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS.with_suffix(".tmp")
    temporary.write_text(json.dumps({"written": gpu_lock.now(), **status}, indent=1), encoding="utf-8")
    os.replace(temporary, STATUS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--parallel", type=int, required=True)
    parser.add_argument("--gpu-limit-mib", type=int, default=22300)
    parser.add_argument("--no-post", action="store_true", help="leave out post_arm.sh, for a speed measurement")
    arguments = parser.parse_args()
    queue = json.loads(arguments.queue.read_text(encoding="utf-8"))
    LOGS.mkdir(parents=True, exist_ok=True)
    names = [arm["name"] for arm in queue["arms"]]
    if len(set(names)) != len(names):
        raise SystemExit("the queue names an arm twice")
    status = {"queue": str(arguments.queue), "arms": {name: "waiting" for name in names}, "wave": 0}
    for arm in queue["arms"]:
        if done(arm):
            status["arms"][arm["name"]] = "trained earlier"
    failed: set[str] = set()
    posts = []
    while True:
        pending = [arm for arm in queue["arms"] if not done(arm) and arm["name"] not in failed]
        if not pending:
            break
        wave, used = [], gpu_used_mib()
        needed = 0.0
        for arm in pending:
            cost = arm["memory_gb"] * 1024 + CONTEXT_MARGIN_MIB
            if len(wave) < arguments.parallel and used + needed + cost <= arguments.gpu_limit_mib:
                wave.append(arm)
                needed += cost
        if not wave:
            print(f"{gpu_lock.now()} the GPU holds {used} MiB, so no arm fits; the script looks again in 5 minutes", flush=True)
            time.sleep(300)
            continue
        status["wave"] += 1
        print(f"{gpu_lock.now()} wave {status['wave']}: {[arm['name'] for arm in wave]}, {used} MiB in use, {needed:.0f} MiB needed", flush=True)
        with gpu_lock.GpuLock(arguments.lock, "train " + " ".join(arm["name"] for arm in wave)):
            runs = []
            for arm in wave:
                log = (LOGS / f"train-{arm['name']}.log").open("a", encoding="utf-8")
                command = [sys.executable, str(ROOT / "scripts" / "lm-domain" / "train3.py"), *queue["common"], *arm["arguments"],
                           "--memory-gb", str(arm["memory_gb"]), "--gpu-lock", str(arguments.lock), "--lock-held-by-parent",
                           "--out", str(MODELS / arm["name"])]
                environment = {**os.environ, "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "PYTHONUNBUFFERED": "1"}
                runs.append((arm, subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, env=environment)))
                status["arms"][arm["name"]] = f"training since {gpu_lock.now()}"
            write_status(status)
            for arm, process in runs:
                code = process.wait()
                print(f"{gpu_lock.now()} {arm['name']}: training ended with exit code {code}", flush=True)
                if done(arm):
                    status["arms"][arm["name"]] = f"trained at {gpu_lock.now()}"
                else:
                    failed.add(arm["name"])
                    status["arms"][arm["name"]] = f"failed with exit code {code} at {gpu_lock.now()}"
                write_status(status)
        for arm, _ in runs:
            if done(arm) and not arguments.no_post:
                log = (LOGS / f"post-{arm['name']}.log").open("a", encoding="utf-8")
                posts.append((arm["name"], subprocess.Popen([BASH, "scripts/lm-domain/post_arm.sh", arm["name"]],
                                                            stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)))
        if any(not done(arm) and arm["name"] not in failed for arm in queue["arms"]):
            time.sleep(BETWEEN_WAVES_SECONDS)
    for name, process in posts:
        code = process.wait()
        print(f"{gpu_lock.now()} {name}: conversion and checks ended with exit code {code}", flush=True)
        status["arms"][name] += f"; post_arm.sh ended with exit code {code}"
    status["ended"] = gpu_lock.now()
    write_status(status)
    print(f"{gpu_lock.now()} the queue is done; failed arms: {sorted(failed)}", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

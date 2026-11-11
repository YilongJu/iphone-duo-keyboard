"""Keeps two training runs of round 2 on the one GPU until the queue is empty.

The script holds the GPU lock from its start to its end and writes it again every 10 minutes. When
a run ends, post_arm.sh converts and tunes that arm on the CPU, and the next arm of
train-queue.json starts as soon as the memory in use on the GPU, its cap and a margin for the CUDA
context stay under the limit. An arm with a train-result.json is skipped.

--adopt NAME:PID takes over a training run that an earlier runner started, and the lock of that
runner: the lock file must name this project.

Usage, from Git Bash at the root of the lm-finetune2 worktree, with the project's Python:
    uv run --project scripts/lm-finetune python scripts/lm-finetune2/run_slots.py \
        --queue scripts/lm-finetune2/train-queue.json --lock D:/Github/iphone-duo-keyboard/build/gpu.lock
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune2"))
import gpu_lock  # noqa: E402
import run_queue  # noqa: E402

SLOTS = 2
POLL_SECONDS = 30
MODELS = ROOT / "build" / "lm-finetune2" / "models"
LOGS = ROOT / "build" / "lm-finetune2" / "logs"


def pid_alive(pid: int) -> bool:
    # One empty answer of tasklist does not show that the process ended, so the check asks three times.
    for _ in range(3):
        answer = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        if str(pid) in answer.stdout:
            return True
        time.sleep(5)
    return False


class Adopted:
    """A training process that another runner started."""

    def __init__(self, pid: int):
        self.pid = pid

    def poll(self):
        return None if pid_alive(self.pid) else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--round1", type=Path, default=ROOT.parent / "lm-finetune")
    parser.add_argument("--adopt", action="append", default=[], help="NAME:PID of a training run that is already on the GPU")
    parser.add_argument("--slots", type=int, default=SLOTS, help="training runs at the same time, for a new start")
    parser.add_argument("--single-from", help="HH:MM of today: from then on one run only")
    parser.add_argument("--stop-then", help="the run that stops at --single-from when two runs are still training")
    arguments = parser.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    queue = [arm for batch in json.loads(arguments.queue.read_text(encoding="utf-8"))["batches"] for arm in batch]
    running = {}
    for text in arguments.adopt:
        name, pid = text.split(":")
        running[name] = Adopted(int(pid))
    pending = [arm for arm in queue if arm["name"] not in running and not (MODELS / arm["name"] / "train-result.json").exists()]

    content = {"name": gpu_lock.NAME, "purpose": "train the round 2 arms, two at a time", "pid": os.getpid(), "start": gpu_lock.now()}
    if arguments.adopt:
        gpu_lock.check_held(arguments.lock)
        arguments.lock.write_text(json.dumps(content) + "\n", encoding="utf-8")
        print(f"{gpu_lock.now()} took over the GPU lock {arguments.lock}", flush=True)
        stop = threading.Event()

        def refresh():
            while not stop.wait(gpu_lock.REFRESH_SECONDS):
                arguments.lock.write_text(json.dumps({**content, "alive_at": gpu_lock.now()}) + "\n", encoding="utf-8")
        threading.Thread(target=refresh, daemon=True).start()
        lock = None
    else:
        lock = gpu_lock.GpuLock(arguments.lock, content["purpose"])
        lock.__enter__()
    posts = []
    try:
        while running or pending:
            for name, process in list(running.items()):
                code = process.poll()
                if code is None:
                    continue
                del running[name]
                if (MODELS / name / "train-result.json").exists():
                    print(f"{gpu_lock.now()} {name}: training ended, conversion and tuning start", flush=True)
                    log = (LOGS / f"post-{name}.log").open("w", encoding="utf-8")
                    posts.append((name, subprocess.Popen([run_queue.BASH, "scripts/lm-finetune2/post_arm.sh", name],
                                                         stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)))
                else:
                    print(f"{gpu_lock.now()} {name}: training ended with exit code {code} and without a result", flush=True)
            single = arguments.single_from is not None and time.strftime("%H:%M") >= arguments.single_from
            if single and len(running) > 1:
                victim = running.pop(arguments.stop_then)
                subprocess.run(["taskkill", "/PID", str(victim.pid), "/T", "/F"], capture_output=True)
                print(f"{gpu_lock.now()} {arguments.stop_then}: stopped, one run only from {arguments.single_from}", flush=True)
            if pending and len(running) < (1 if single else arguments.slots):
                arm = pending[0]
                used = run_queue.gpu_used_mib()
                needed = arm["memory_gb"] * 1024 + run_queue.CONTEXT_MARGIN_MIB
                if used + needed <= run_queue.GPU_LIMIT_MIB:
                    pending.pop(0)
                    running[arm["name"]] = run_queue.train(arm, arguments)
                    print(f"{gpu_lock.now()} {arm['name']}: training starts, {used} MiB in use before it", flush=True)
                    time.sleep(240)  # the new run takes its memory before the next memory check
                    continue
                if not running:
                    print(f"{gpu_lock.now()} {arm['name']} waits: {used} MiB in use, {needed:.0f} MiB needed", flush=True)
            time.sleep(POLL_SECONDS)
    finally:
        if lock is not None:
            lock.__exit__(None, None, None)
        else:
            stop.set()
            arguments.lock.unlink()
            print(f"{gpu_lock.now()} released the GPU lock {arguments.lock}", flush=True)
    for name, process in posts:
        print(f"{gpu_lock.now()} {name}: conversion and tuning ended with exit code {process.wait()}", flush=True)
    print(f"{gpu_lock.now()} the queue is done", flush=True)


if __name__ == "__main__":
    main()

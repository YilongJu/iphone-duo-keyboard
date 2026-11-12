"""Runs the training queue of the domain round on the one GPU, up to --parallel arms at a time.

The script takes the GPU lock when it starts its first arm, starts the next arm of the queue
whenever a place is free (train3.py with --lock-held-by-parent), and releases the lock when no
arm runs. An arm starts only when the free GPU memory holds its cap and a margin for its CUDA
context, and when every file of its `needs` exists. So an arm can stand in the queue before its
lists are built.

The queue file names the arms: {"common": [arguments of every arm], "arms": [{"name": NAME,
"memory_gb": 3.7, "needs": [FILES], "arguments": [...]}]}. An arm with a train-result.json is
done, and the script leaves it out, so the queue is safe to start again. An arm that a stop left
half done goes on from its checkpoint.pt. After an arm trains, post_arm.sh converts and checks
its model. The script reads the queue file again on every round, so an arm can join a running
queue. It ends when every arm is done or failed, or when the arms that are left wait for a file
for longer than --wait-hours.

The script writes build/lm-domain/state/train-queue.status.json after every change.

Usage, from Git Bash at the root of the worktree:
    build/lm-domain/venv/Scripts/python.exe scripts/lm-domain/run_train_queue.py \
        --queue scripts/lm-domain/train-queue.json --lock D:/Github/iphone-duo-keyboard/build/gpu.lock --parallel 4
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
BASH = r"C:\Program Files\Git\bin\bash.exe"
MODELS = ROOT / "build" / "lm-domain" / "models"
LOGS = ROOT / "build" / "lm-domain" / "logs"
STATUS = ROOT / "build" / "lm-domain" / "state" / "train-queue.status.json"


def gpu_used_mib() -> int:
    answer = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"],
                            capture_output=True, text=True, check=True)
    return int(answer.stdout.strip())


def done(name: str) -> bool:
    return (MODELS / name / "train-result.json").exists()


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
    parser.add_argument("--wait-hours", type=float, default=0.0, help="how long the script waits for a file that an arm needs")
    parser.add_argument("--no-post", action="store_true", help="leave out post_arm.sh, for a speed measurement")
    arguments = parser.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    status = {"queue": str(arguments.queue), "arms": {}}
    running: dict[str, subprocess.Popen] = {}
    reserved: dict[str, float] = {}
    posts: dict[str, subprocess.Popen] = {}
    failed: set[str] = set()
    lock = None
    others = 0
    last_change = time.monotonic()
    while True:
        queue = json.loads(arguments.queue.read_text(encoding="utf-8"))
        names = [arm["name"] for arm in queue["arms"]]
        if len(set(names)) != len(names):
            raise SystemExit("the queue names an arm twice")
        for name in [name for name, process in running.items() if process.poll() is not None]:
            code = running.pop(name).returncode
            reserved.pop(name)
            last_change = time.monotonic()
            print(f"{gpu_lock.now()} {name}: training ended with exit code {code}", flush=True)
            if done(name):
                status["arms"][name] = f"trained at {gpu_lock.now()}"
                if not arguments.no_post:
                    log = (LOGS / f"post-{name}.log").open("a", encoding="utf-8")
                    posts[name] = subprocess.Popen([BASH, "scripts/lm-domain/post_arm.sh", name], stdout=log,
                                                   stderr=subprocess.STDOUT, cwd=ROOT)
            else:
                failed.add(name)
                status["arms"][name] = f"failed with exit code {code} at {gpu_lock.now()}"
        for name in [name for name, process in posts.items() if process.poll() is not None]:
            code = posts.pop(name).returncode
            print(f"{gpu_lock.now()} {name}: conversion and checks ended with exit code {code}", flush=True)
            status["arms"][name] += f"; post_arm.sh ended with exit code {code}"
        waiting = [arm for arm in queue["arms"] if not done(arm["name"]) and arm["name"] not in failed and arm["name"] not in running]
        for arm in queue["arms"]:
            if done(arm["name"]) and arm["name"] not in status["arms"]:
                status["arms"][arm["name"]] = "trained earlier"
        ready = [arm for arm in waiting if all((ROOT / path).exists() for path in arm.get("needs", []))]
        for arm in waiting:
            if arm not in ready:
                status["arms"][arm["name"]] = "waiting for a file that it needs"
            elif arm["name"] not in status["arms"] or status["arms"][arm["name"]].startswith("waiting for a file"):
                status["arms"][arm["name"]] = "waiting for a place"
        # The memory in use counts the full cap of every running arm, also before the arm has
        # taken it: the memory of the other programs, measured while no arm ran, plus the caps.
        used = 0.0
        if ready and len(running) < arguments.parallel:
            if not running:
                others = gpu_used_mib()
            used = max(gpu_used_mib(), others + sum(reserved.values()))
        for arm in ready:
            cost = arm["memory_gb"] * 1024 + CONTEXT_MARGIN_MIB
            if len(running) >= arguments.parallel or used + cost > arguments.gpu_limit_mib:
                break
            if lock is None:
                lock = gpu_lock.GpuLock(arguments.lock, f"training queue of the domain round, up to {arguments.parallel} arms at a time")
                lock.__enter__()
            log = (LOGS / f"train-{arm['name']}.log").open("a", encoding="utf-8")
            command = [sys.executable, str(ROOT / "scripts" / "lm-domain" / "train3.py"), *queue["common"], *arm["arguments"],
                       "--memory-gb", str(arm["memory_gb"]), "--gpu-lock", str(arguments.lock), "--lock-held-by-parent",
                       "--out", str(MODELS / arm["name"])]
            environment = {**os.environ, "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "PYTHONUNBUFFERED": "1"}
            running[arm["name"]] = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, env=environment)
            reserved[arm["name"]] = cost
            used += cost
            last_change = time.monotonic()
            status["arms"][arm["name"]] = f"training since {gpu_lock.now()}"
            print(f"{gpu_lock.now()} {arm['name']}: started, {used:.0f} MiB counted in use", flush=True)
            # The next arm starts after this one has loaded its lists and its model.
            time.sleep(30)
            used = max(gpu_used_mib(), others + sum(reserved.values()))
        write_status({**status, "running": sorted(running), "failed": sorted(failed)})
        if not running:
            if lock is not None:
                lock.__exit__(None, None, None)
                lock = None
            if not waiting:
                break
            if not ready and time.monotonic() - last_change > arguments.wait_hours * 3600:
                print(f"{gpu_lock.now()} the arms {[arm['name'] for arm in waiting]} still wait for a file", flush=True)
                break
        time.sleep(60)
    for name, process in posts.items():
        code = process.wait()
        print(f"{gpu_lock.now()} {name}: conversion and checks ended with exit code {code}", flush=True)
        status["arms"][name] += f"; post_arm.sh ended with exit code {code}"
    write_status({**status, "running": [], "failed": sorted(failed), "ended": gpu_lock.now()})
    print(f"{gpu_lock.now()} the queue is done; failed arms: {sorted(failed)}", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

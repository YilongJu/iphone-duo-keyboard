"""Runs the training queue of round 2 on the one GPU, one batch after another.

A batch holds one or two arms. The script takes the GPU lock for the batch, trains its arms at the
same time (train2.py with --lock-held-by-parent), and releases the lock. Two arms run together only
when the memory in use on the GPU, their two caps and a margin for the CUDA contexts stay under
the limit. Otherwise they run back to back. After an arm trains, post_arm.sh converts it, checks
it against lm_score and starts its tuning in WSL, beside the next batch.

An arm with a train-result.json is skipped, so the queue can start again after a stop. A run that
fails is written to the log, and the queue goes on.

Usage, from Git Bash at the root of the lm-finetune2 worktree, with the project's Python:
    uv run --project scripts/lm-finetune python scripts/lm-finetune2/run_queue.py \
        --queue scripts/lm-finetune2/train-queue.json --lock D:/Github/iphone-duo-keyboard/build/gpu.lock
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
from gpu_lock import GpuLock, now  # noqa: E402

GPU_LIMIT_MIB = 22500
CONTEXT_MARGIN_MIB = 400
BASH = r"C:\Program Files\Git\bin\bash.exe"


def gpu_used_mib() -> int:
    answer = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"],
                            capture_output=True, text=True, check=True)
    return int(answer.stdout.strip())


def train(arm: dict, arguments) -> subprocess.Popen:
    out = ROOT / "build" / "lm-finetune2" / "models" / arm["name"]
    log = (ROOT / "build" / "lm-finetune2" / "logs" / f"train-{arm['name']}.log").open("w", encoding="utf-8")
    command = [sys.executable, str(ROOT / "scripts" / "lm-finetune2" / "train2.py"), "--base", "smollm2-135m",
               "--method", arm["method"], "--seed", str(arm["seed"]), "--packed", "--micro-tokens", "1500",
               "--memory-gb", str(arm["memory_gb"]), "--data", str(arguments.round1 / "build" / "lm-finetune" / "data"),
               "--gpu-lock", str(arguments.lock), "--lock-held-by-parent", "--out", str(out), *arm.get("extra", [])]
    environment = {**os.environ, "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "PYTHONUNBUFFERED": "1"}
    return subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, env=environment)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--round1", type=Path, default=ROOT.parent / "lm-finetune")
    arguments = parser.parse_args()
    (ROOT / "build" / "lm-finetune2" / "logs").mkdir(parents=True, exist_ok=True)
    queue = json.loads(arguments.queue.read_text(encoding="utf-8"))
    posts = []
    for batch in queue["batches"]:
        arms = [arm for arm in batch if not (ROOT / "build" / "lm-finetune2" / "models" / arm["name"] / "train-result.json").exists()]
        if not arms:
            continue
        used = gpu_used_mib()
        needed = sum(arm["memory_gb"] * 1024 + CONTEXT_MARGIN_MIB for arm in arms)
        groups = [arms] if used + needed <= GPU_LIMIT_MIB else [[arm] for arm in arms]
        print(f"{now()} batch {[arm['name'] for arm in arms]}: {used} MiB in use, {needed:.0f} MiB needed, "
              f"{'together' if len(groups) == 1 else 'back to back'}", flush=True)
        for group in groups:
            with GpuLock(arguments.lock, "train " + " and ".join(arm["name"] for arm in group)):
                runs = [(arm, train(arm, arguments)) for arm in group]
                for arm, process in runs:
                    code = process.wait()
                    print(f"{now()} {arm['name']}: training ended with exit code {code}", flush=True)
            for arm in group:
                if (ROOT / "build" / "lm-finetune2" / "models" / arm["name"] / "train-result.json").exists():
                    log = (ROOT / "build" / "lm-finetune2" / "logs" / f"post-{arm['name']}.log").open("w", encoding="utf-8")
                    posts.append((arm["name"], subprocess.Popen([BASH, "scripts/lm-finetune2/post_arm.sh", arm["name"]],
                                                                stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)))
                else:
                    print(f"{now()} {arm['name']}: no train-result.json, so the arm is not converted", flush=True)
    for name, process in posts:
        print(f"{now()} {name}: conversion and checks ended with exit code {process.wait()}", flush=True)
    print(f"{now()} the queue is done", flush=True)


if __name__ == "__main__":
    main()

"""The lock file that the users of the one GPU share (build/gpu.lock of the main checkout).

A holder creates the file exclusively, with its name, its purpose and its start time, and deletes
it when its GPU work ends, also after an error. A waiter looks again every minute. A lock older
than 3 hours stays in place: the waiter stops and shows its content, so a person can decide. A
holder that runs longer than that writes the file again every 10 minutes, so the file's age shows
that the holder is alive.
"""
import datetime
import json
import os
import threading
import time
from pathlib import Path

NAME = "lm-finetune2 (Claude agent, round 2 of the re-ranker fine-tune)"
RETRY_SECONDS = 60
STALE_SECONDS = 3 * 3600
REFRESH_SECONDS = 600


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class GpuLock:
    def __init__(self, path: Path, purpose: str):
        self.path, self.purpose, self.held = path, purpose, False
        self.content = {"name": NAME, "purpose": purpose, "pid": os.getpid()}
        self.stop = threading.Event()

    def __enter__(self):
        while True:
            try:
                with open(self.path, "x", encoding="utf-8") as file:
                    self.content["start"] = now()
                    file.write(json.dumps(self.content) + "\n")
                self.held = True
                print(f"{now()} took the GPU lock {self.path}: {self.purpose}", flush=True)
                threading.Thread(target=self.refresh, daemon=True).start()
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                    content = self.path.read_text(encoding="utf-8", errors="replace").strip()
                except FileNotFoundError:
                    continue
                if age > STALE_SECONDS:
                    raise SystemExit(f"the GPU lock {self.path} is {age / 3600:.1f} hours old and stays in place: {content}")
                print(f"{now()} the GPU lock is held ({age / 60:.0f} min old): {content}", flush=True)
                time.sleep(RETRY_SECONDS)

    def refresh(self) -> None:
        while not self.stop.wait(REFRESH_SECONDS):
            if self.held:
                self.path.write_text(json.dumps({**self.content, "alive_at": now()}) + "\n", encoding="utf-8")

    def __exit__(self, *exception):
        self.stop.set()
        if self.held:
            self.held = False
            self.path.unlink()
            print(f"{now()} released the GPU lock {self.path}", flush=True)


def check_held(path: Path) -> None:
    """Stops unless the lock file exists and names this project as its holder."""
    if not path.exists():
        raise SystemExit(f"the GPU lock {path} is not held")
    content = json.loads(path.read_text(encoding="utf-8"))
    if content.get("name") != NAME:
        raise SystemExit(f"the GPU lock {path} belongs to another holder: {content}")

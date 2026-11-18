"""Reads the next-token block of every text that a model reads in a text half, and stores the
blocks as 16-bit floats: one row per text, one number per token of the vocabulary.

`lm_score MODEL THREADS next` (scripts/lm-rerank/lm_score.c) gives each block. Several scorer
processes run side by side. A run that stopped goes on after the rows it finished.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/benchmark/blocks.py --lm LM_SCORE \
        --model MODEL.gguf --name shipped --set technical --half dev --workers 6
"""
import argparse
import hashlib
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import core  # noqa: E402
import rules  # noqa: E402


class Scorer:
    """One `lm_score MODEL THREADS next` process."""

    def __init__(self, program: str, model: str, threads: int, log: Path):
        self.log = log.open("wb")
        self.process = subprocess.Popen(
            [program, model, str(threads), "next"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log)
        ready = self.process.stdout.readline().decode("utf-8")
        if not ready.startswith("ready vocabulary="):
            raise SystemExit(f"lm_score did not start: {ready!r}; see {log}")
        self.ready = ready.strip()
        self.vocabulary = int(ready.split()[1].split("=")[1])
        self.seconds: list[float] = []

    def send(self, line: str) -> None:
        if "\n" in line or "\r" in line:
            raise SystemExit(f"a request holds a line break: {line!r}")
        self.process.stdin.write(line.encode("utf-8") + b"\n")
        self.process.stdin.flush()

    def next_tokens(self, context: str) -> np.ndarray:
        if "\t" in context:
            raise SystemExit(f"a context holds a tab: {context!r}")
        started = time.monotonic()
        self.send(context)
        wanted = self.vocabulary * 4
        data = bytearray()
        while len(data) < wanted:
            part = self.process.stdout.read(wanted - len(data))
            if not part:
                raise SystemExit(f"lm_score ended in a next-token block; see {self.log.name}")
            data += part
        self.seconds.append(time.monotonic() - started)
        return np.frombuffer(bytes(data), dtype=np.float32)

    def exact(self, context: str, forms: list[str]) -> list[tuple[float, float]]:
        """(log probability, log probability that the next token starts with a space) of each
        form after `context`. A form follows a context after one space, and opens an empty one."""
        self.send("\t".join([context, *forms]))
        fields = self.process.stdout.readline().decode("utf-8").rstrip("\n").split("\t")
        if len(fields) != len(forms):
            raise SystemExit(f"lm_score answered {fields!r} for {forms!r}; see {self.log.name}")
        return [tuple(float(value) for value in field.split(" ")) for field in fields]

    def close(self) -> None:
        self.process.stdin.close()
        self.process.wait()
        self.log.close()


def folder(name: str, text_set: str, half: str) -> Path:
    return core.BENCH / "blocks" / name / f"{text_set}.{half}"


def open_blocks(name: str, text_set: str, half: str, contexts: list[str]) -> np.ndarray:
    """The stored blocks of a text half, after a check that they belong to these texts and that
    every row is there."""
    where = folder(name, text_set, half)
    facts = json.loads((where / "facts.json").read_text(encoding="utf-8"))
    if facts["contexts_sha256"] != hashlib.sha256("\n".join(contexts).encode("utf-8")).hexdigest():
        raise SystemExit(f"{where} holds the blocks of other texts")
    done = np.load(where / "done.npy")
    if not done.all():
        raise SystemExit(f"{where} lacks {int((~done).sum())} of {len(done)} blocks")
    return np.memmap(where / "blocks.f16", dtype=np.float16, mode="r", shape=(len(contexts), facts["vocabulary"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--set", required=True, dest="text_set")
    parser.add_argument("--half", required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--contexts", type=Path, help="a file with one text per line, in place of a text set")
    args = parser.parse_args()
    if args.contexts is not None:
        contexts = args.contexts.read_text(encoding="utf-8").split("\n")
    else:
        rules.require_half(args.half)
        contexts, _ = core.states_of(args.text_set, args.half).contexts()
    where = folder(args.name, args.text_set, args.half)
    where.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256("\n".join(contexts).encode("utf-8")).hexdigest()

    first = Scorer(args.lm, args.model, args.threads, where / "worker-0.lm_score.log")
    vocabulary = first.vocabulary
    facts_path = where / "facts.json"
    done_path = where / "done.npy"
    if facts_path.exists() and done_path.exists() and json.loads(facts_path.read_text(encoding="utf-8")).get("contexts_sha256") == digest:
        done = np.load(done_path)
        blocks = np.memmap(where / "blocks.f16", dtype=np.float16, mode="r+", shape=(len(contexts), vocabulary))
    else:
        done = np.zeros(len(contexts), dtype=bool)
        blocks = np.memmap(where / "blocks.f16", dtype=np.float16, mode="w+", shape=(len(contexts), vocabulary))
    facts = {"model": args.model, "vocabulary": vocabulary, "contexts": len(contexts), "contexts_sha256": digest,
             "ready": first.ready, "workers": args.workers, "threads": args.threads}
    facts_path.write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    todo = [number for number in range(len(contexts)) if not done[number]]
    print(f"{args.name} {args.text_set}.{args.half}: {len(todo)} of {len(contexts)} blocks to read", flush=True)
    scorers = [first] + [Scorer(args.lm, args.model, args.threads, where / f"worker-{index}.lm_score.log")
                         for index in range(1, args.workers)]
    lock = threading.Lock()
    started = time.monotonic()
    count = [0]

    def work(scorer: Scorer, numbers: list[int]) -> None:
        for number in numbers:
            block = scorer.next_tokens(contexts[number])
            if not np.isfinite(block).all():
                raise SystemExit(f"the block of text {number} holds a number that is not finite")
            blocks[number] = block.astype(np.float16)
            with lock:
                done[number] = True
                count[0] += 1
                if count[0] % 2000 == 0:
                    np.save(done_path, done)
                    print(f"  {count[0]} blocks, {time.monotonic() - started:.0f} s", flush=True)

    threads = [threading.Thread(target=work, args=(scorer, todo[index::args.workers])) for index, scorer in enumerate(scorers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    blocks.flush()
    np.save(done_path, done)
    seconds = [value for scorer in scorers for value in scorer.seconds]
    for scorer in scorers:
        scorer.close()
    if not done.all():
        raise SystemExit(f"{int((~done).sum())} blocks are missing; a worker stopped")
    if seconds:
        facts["read_ms_median"] = float(np.median(seconds) * 1000)
        facts["read_ms_mean"] = float(np.mean(seconds) * 1000)
        facts["wall_seconds"] = time.monotonic() - started
        facts_path.write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    print(f"{args.name} {args.text_set}.{args.half}: done, {json.dumps(facts)}", flush=True)


if __name__ == "__main__":
    main()

"""Builds the lists of the new training and stopping cases of round 2 (cases2.train.jsonl and
cases2.stop.jsonl of build_cases2.py), with the list builder of round 1
(scripts/lm-finetune/build_lists.py). A clean sentence gives one list per correction, and the
target of each is the reading as typed.

Usage, from the repository root, on Linux:
    python3 scripts/lm-finetune2/build_lists2.py --shim build/lm-rerank/libduo_shim.so \
        --data build/lm-finetune2/data --workers 4
"""
import argparse
import gzip
import json
import multiprocessing
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import build_lists  # noqa: E402
import rerank  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--workers", type=int, required=True)
    arguments = parser.parse_args()

    report = {}
    for split in ("train", "stop"):
        cases = rerank.load_cases([arguments.data / f"cases2.{split}.jsonl"])
        if any(case["split"] != split for case in cases):
            raise SystemExit(f"cases2.{split}.jsonl holds a case of another split")
        started = time.monotonic()
        chunks = [cases[index::arguments.workers * 8] for index in range(arguments.workers * 8)]
        with multiprocessing.Pool(arguments.workers, initializer=build_lists.start_worker, initargs=(str(arguments.shim),)) as pool:
            results = pool.map(build_lists.lists_of_chunk, chunks)
        lists = [item for found, _ in results for item in found]
        lists.sort(key=lambda item: item["case"])
        categories = {}
        for _, totals in results:
            for name, counts in totals.items():
                entry = categories.setdefault(name, {})
                for key, value in counts.items():
                    entry[key] = entry.get(key, 0) + value
        typed_targets = sum(1 for item in lists if item["readings"][item["target"]][3] == 1)
        with gzip.open(arguments.data / f"lists2.{split}.jsonl.gz", "wt", encoding="utf-8") as file:
            for item in lists:
                file.write(json.dumps(item) + "\n")
        report[split] = {"cases": len(cases), "lists": len(lists), "lists_with_the_typed_reading_as_target": typed_targets,
                         "seconds": round(time.monotonic() - started, 1), "categories": dict(sorted(categories.items()))}
        print(split, json.dumps(report[split]), flush=True)
    (arguments.data / "lists2-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

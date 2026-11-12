"""Builds the training lists of the distilgpt2 fine-tune from the cases of build_cases.py.

Each case is typed through the Python copy of the keyboard rules in scripts/lm-rerank/rerank.py.
At every correction the engine gives up to 8 readings. The list holds the text before the span,
the typed span and the readings, each as [text, engine score, slip cost, as typed, chosen]. Its target is the longest reading that keeps the field a prefix
of the intended text. At the last correction of a case that is the reading that gives the
intended text. The typing then goes on with the target, or with the engine's choice when the
list does not hold one. A list without a target, and a list of one reading, stay out of the
file, and the report counts them.

Usage, from the repository root, on Linux:
    python3 scripts/lm-finetune/build_lists.py --shim build/lm-rerank/libduo_shim.so \
        --data build/lm-finetune/data --workers 4
"""
import argparse
import gzip
import json
import multiprocessing
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import rerank  # noqa: E402

engine = None


def start_worker(shim: str) -> None:
    global engine
    engine = rerank.Engine(Path(shim), rerank.LEXICON)


def lists_of_case(case: dict) -> tuple[list[dict], dict]:
    target_text = (case["context"] + " " if case["context"] else "") + case["intended"].strip().lower() + " "
    found, counts = [], {"events": 0, "one_reading": 0, "without_target": 0}

    def chooser(readings: list[dict], text_before: str, typed: str) -> str:
        counts["events"] += 1
        matches = [r for r in readings if target_text.startswith(text_before + r["text"] + " ")]
        target = max(matches, key=lambda r: len(r["text"])) if matches else None
        if len(readings) < 2:
            counts["one_reading"] += 1
        elif target is None:
            counts["without_target"] += 1
        else:
            found.append({"case": case["id"], "category": case["category"], "context": text_before.rstrip(" "),
                          "typed": typed,
                          "readings": [[r["text"], r["score"], r["slips"], int(r["as_typed"]), int(r["chosen"])]
                                       for r in readings],
                          "target": readings.index(target)})
        return target["text"] if target is not None else rerank.engine_choice(readings, text_before, typed)

    output = rerank.type_case(case, engine, chooser)
    counts["right_after_oracle"] = int(output.strip().lower() == case["intended"].strip().lower())
    return found, counts


def lists_of_chunk(cases: list[dict]) -> tuple[list[dict], dict]:
    lists, totals = [], {}
    for case in cases:
        found, counts = lists_of_case(case)
        lists.extend(found)
        category = totals.setdefault(case["category"], {"cases": 0, "lists": 0})
        category["cases"] += 1
        category["lists"] += len(found)
        for key, value in counts.items():
            category[key] = category.get(key, 0) + value
    return lists, totals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--workers", type=int, required=True)
    arguments = parser.parse_args()

    report = {}
    for split in ("train", "stop", "tune"):
        cases = rerank.load_cases([arguments.data / f"cases.{split}.jsonl"])
        if any(case["split"] != split for case in cases):
            raise SystemExit(f"cases.{split}.jsonl holds a case of another split")
        started = time.monotonic()
        chunks = [cases[index::arguments.workers * 8] for index in range(arguments.workers * 8)]
        with multiprocessing.Pool(arguments.workers, initializer=start_worker, initargs=(str(arguments.shim),)) as pool:
            results = pool.map(lists_of_chunk, chunks)
        lists = [item for found, _ in results for item in found]
        lists.sort(key=lambda item: item["case"])
        categories = {}
        for _, totals in results:
            for name, counts in totals.items():
                entry = categories.setdefault(name, {})
                for key, value in counts.items():
                    entry[key] = entry.get(key, 0) + value
        with gzip.open(arguments.data / f"lists.{split}.jsonl.gz", "wt", encoding="utf-8") as file:
            for item in lists:
                file.write(json.dumps(item) + "\n")
        report[split] = {"cases": len(cases), "lists": len(lists), "seconds": round(time.monotonic() - started, 1),
                         "categories": dict(sorted(categories.items()))}
        print(split, json.dumps({key: value for key, value in report[split].items() if key != "categories"}), flush=True)
    (arguments.data / "lists-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

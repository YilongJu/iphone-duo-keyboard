"""Builds training lists with the work area on, from any file of cases.

Each case is typed as the keyboard ships with the work area "AI and software" on
(harness.Typist): the engine reads with the supplement, and the field keeps the typed capitals.
The protection of a typed new word is off here, so a list holds every reading of the engine and
the model learns to keep a word of the pack by itself. At every correction the engine gives up
to 8 readings. The list holds the text before the span, the typed span and the readings, each
as [text, engine score, slip cost, as typed, chosen]. Its target is the longest reading that
keeps the field a start of the intended text (harness.perfect_chooser). The typing goes on with
the target, or with the engine's choice when the list does not hold one. A list without a
target, and a list of one reading, stay out of the file, and the report counts them.

A list keeps the fields `u`, `source` and `term` of its case, when the case has them.

Usage, from the repository root, on Linux:
    python3 scripts/lm-domain/build_lists3.py --shim ~/lmdom/bin/libduo_shim.so --workers 8 \
        --cases build/lm-domain/data/domain/cases.train.jsonl --out build/lm-domain/data/domain/lists.train.jsonl.gz
"""
import argparse
import gzip
import json
import multiprocessing
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-domain"))
import harness  # noqa: E402
import rerank  # noqa: E402

typist = None


def start_worker(shim: str) -> None:
    global typist
    typist = harness.Typist(Path(shim), protect_new_words=False)


def lists_of_case(case: dict) -> tuple[list[dict], dict]:
    target_text = ((case["context"] + " " if case["context"] else "") + case["intended"].strip() + " ").lower()
    found, counts = [], {"events": 0, "one_reading": 0, "without_target": 0}
    kept = {key: case[key] for key in ("u", "source", "term") if key in case}

    def chooser(readings: list[dict], text_before: str, typed: str | None = None) -> str:
        counts["events"] += 1
        before = text_before.lower()
        matches = [r for r in readings if target_text.startswith(before + r["text"])
                   and target_text[len(before) + len(r["text"])] in rerank.TERMINATORS]
        target = max(matches, key=lambda r: len(r["text"])) if matches else None
        if len(readings) < 2:
            counts["one_reading"] += 1
        elif target is None:
            counts["without_target"] += 1
        else:
            found.append({"case": case["id"], "category": case["category"], "context": text_before.rstrip(" "), "typed": typed,
                          "readings": [[r["text"], r["score"], r["slips"], int(r["as_typed"]), int(r["chosen"])] for r in readings],
                          "target": readings.index(target), **kept})
        return target["text"] if target is not None else rerank.engine_choice(readings, text_before, typed)

    output = typist.type(case, chooser)
    counts["right_after_perfect_chooser"] = int(harness.is_right(case, output))
    return found, counts


def lists_of_chunk(cases: list[dict]) -> tuple[list[dict], dict]:
    lists, totals = [], {}
    for case in cases:
        found, counts = lists_of_case(case)
        lists.extend(found)
        category = totals.setdefault(case["category"], {"cases": 0, "lists": 0, "lists_with_the_typed_reading_as_target": 0})
        category["cases"] += 1
        category["lists"] += len(found)
        category["lists_with_the_typed_reading_as_target"] += sum(1 for item in found if item["readings"][item["target"]][3] == 1)
        for key, value in counts.items():
            category[key] = category.get(key, 0) + value
    return lists, totals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--cases", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, required=True)
    arguments = parser.parse_args()
    cases = rerank.load_cases(arguments.cases)
    if len({case["id"] for case in cases}) != len(cases):
        raise SystemExit("the case files hold an id twice")
    started = time.monotonic()
    chunks = [cases[index::arguments.workers * 8] for index in range(arguments.workers * 8)]
    with multiprocessing.Pool(arguments.workers, initializer=start_worker, initargs=(str(arguments.shim),)) as pool:
        results = pool.map(lists_of_chunk, chunks)
    lists = [item for found, _ in results for item in found]
    lists.sort(key=lambda item: item["case"])
    categories: dict[str, dict] = {}
    for _, totals in results:
        for name, counts in totals.items():
            entry = categories.setdefault(name, {})
            for key, value in counts.items():
                entry[key] = entry.get(key, 0) + value
    with gzip.open(arguments.out, "wt", encoding="utf-8") as file:
        for item in lists:
            file.write(json.dumps(item) + "\n")
    report = {"cases": len(cases), "lists": len(lists),
              "lists_with_the_typed_reading_as_target": sum(entry["lists_with_the_typed_reading_as_target"] for entry in categories.values()),
              "seconds": round(time.monotonic() - started, 1), "supplement": rerank.SUPPLEMENT.name,
              "categories": dict(sorted(categories.items()))}
    Path(str(arguments.out).replace(".jsonl.gz", "") + "-report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "categories"}), flush=True)


if __name__ == "__main__":
    main()

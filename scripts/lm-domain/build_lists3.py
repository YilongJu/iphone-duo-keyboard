"""Builds training lists with the work area on, from any file of cases.

Each case is typed as the keyboard ships with the work area "AI and software" on
(harness.Typist): the engine reads with the supplement, and the field keeps the typed capitals.
The protection of a typed new word is off here, so a list holds every reading of the engine and
the model learns to keep a word of the pack by itself. At every correction the engine gives up
to 8 readings. The list holds the text before the span, the typed span and the readings, each
as [text, engine score, slip cost, as typed, chosen]. Its target is the reading that the
perfect chooser takes (harness.perfect_typing): the text as typed in a case without a slip, and
in a case with a slip a reading that keeps the field a start of the intended text and leads to
the intended text. A list without a target, and a list of one reading, stay out of the file,
and the report counts them.

The list builder of rounds 1 and 2 takes the longest reading that keeps the field a start of
the intended text. In clean running text that rule takes a reading that adds the next word, as
"pay attention in" for the typed "pay attention": 200 of the 54,759 clean running-text lists of
round 2 have such a target.

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
    output, corrections = harness.perfect_typing(typist, case)
    found, counts = [], {"events": len(corrections), "one_reading": 0, "without_target": 0}
    kept = {key: case[key] for key in ("u", "source", "term") if key in case}
    for correction in corrections:
        readings = correction["readings"]
        # The target is the reading that the perfect chooser took, when that reading is a match.
        target = None
        if correction["choice"] in correction["matches"]:
            target = next(r for r in readings if r["text"] == correction["choice"])
        if len(readings) < 2:
            counts["one_reading"] += 1
        elif target is None:
            counts["without_target"] += 1
        else:
            found.append({"case": case["id"], "category": case["category"], "context": correction["text_before"].rstrip(" "),
                          "typed": correction["typed"],
                          "readings": [[r["text"], r["score"], r["slips"], int(r["as_typed"]), int(r["chosen"])] for r in readings],
                          "target": readings.index(target), **kept})
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

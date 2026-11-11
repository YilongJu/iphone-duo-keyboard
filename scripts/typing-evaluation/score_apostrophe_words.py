"""Scores outputs on cases/english-apostrophe-words.HALF.jsonl, per category and per pair.

A word output is right when it equals `intended`. A next-word output, from typing the target
word and then the next word, is right when it equals `intended`, one space and `next_word`.
Letter case does not count, as in score.py.

Usage, from the repository root:
    python3 scripts/typing-evaluation/score_apostrophe_words.py --cases scripts/typing-evaluation/cases/english-apostrophe-words.dev.jsonl \
        --word path/to/word.jsonl [--next-word path/to/next-word.jsonl] [--json path/to/summary.json]
"""
import argparse
import json
from pathlib import Path

from score import normalize


def read(path: Path) -> dict[str, str]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {row["id"]: row["output"] for row in rows}


def tally(cases: list[dict], outputs: dict[str, str], with_next_word: bool) -> dict:
    categories: dict[str, list[int]] = {}
    pairs: dict[str, dict[str, list[int]]] = {}
    missing = 0
    for case in cases:
        intended = case["intended"] + (" " + case["next_word"] if with_next_word else "")
        output = outputs.get(case["id"])
        missing += output is None
        right = int(output is not None and normalize("english", output) == normalize("english", intended))
        for cell in (categories.setdefault(case["category"], [0, 0]),
                     pairs.setdefault(case["pair"], {}).setdefault(case["category"], [0, 0])):
            cell[0] += right
            cell[1] += 1
    return {"right": sum(v[0] for v in categories.values()), "cases": len(cases), "missing": missing,
            "categories": categories, "pairs": pairs}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--word", type=Path, required=True)
    parser.add_argument("--next-word", type=Path)
    parser.add_argument("--json", type=Path)
    arguments = parser.parse_args()
    cases = [json.loads(line) for line in arguments.cases.read_text(encoding="utf-8").splitlines() if line]
    summary = {"word": tally(cases, read(arguments.word), False)}
    if arguments.next_word is not None:
        summary["next_word"] = tally(cases, read(arguments.next_word), True)
    for way, entry in summary.items():
        print(f"{arguments.word.name} {way.replace('_', ' ')}: {entry['right']} / {entry['cases']}"
              + (f", missing {entry['missing']}" if entry["missing"] else ""))
        for category, (right, count) in entry["categories"].items():
            print(f"  {category:32s} {right:5d} / {count:5d}")
    if arguments.json:
        arguments.json.parent.mkdir(parents=True, exist_ok=True)
        arguments.json.write_text(json.dumps(summary, indent=1), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

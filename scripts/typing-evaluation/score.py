"""Scores one engine's outputs against the test cases.

Usage, from the repository root:
    python scripts/typing-evaluation/score.py --task english --cases scripts/typing-evaluation/cases/english.dev.jsonl \
        --predictions path/to/predictions.jsonl --engine NAME [--json path/to/summary.json]

A predictions file holds one JSON object per line with the case `id` and the engine's `output`.
A case without a prediction counts as wrong, and the script reports how many are missing.

English: an output is right when it equals the intended text, ignoring letter case.
Pinyin: an output is right when it equals the intended Chinese text. The script also reports
character accuracy, which is 1 minus the edit distance between output and intended text divided
by the length of the intended text, floored at 0, averaged over the cases of a category.

Categories whose name starts with "clean" hold text typed without a slip. Their accuracy says how
often the engine leaves correct input alone. The other categories hold slips, and their accuracy
says how often the engine repairs the slip.
"""
import argparse
import json
from pathlib import Path


def edit_distance(first: str, second: str) -> int:
    previous = list(range(len(second) + 1))
    for i, a in enumerate(first, 1):
        current = [i]
        for j, b in enumerate(second, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def normalize(task: str, text: str) -> str:
    text = text.strip().replace("’", "'")
    return text.lower() if task == "english" else text


def score(task: str, cases: list[dict], predictions: dict[str, str]) -> dict:
    categories: dict[str, dict] = {}
    for case in cases:
        entry = categories.setdefault(case["category"], {"cases": 0, "right": 0, "missing": 0, "character_accuracy_sum": 0.0})
        entry["cases"] += 1
        output = predictions.get(case["id"])
        if output is None:
            entry["missing"] += 1
            continue
        intended = normalize(task, case["intended"])
        output = normalize(task, output)
        entry["right"] += output == intended
        if task == "pinyin":
            entry["character_accuracy_sum"] += max(0.0, 1 - edit_distance(output, intended) / len(intended))

    def total(names):
        cases_count = sum(categories[name]["cases"] for name in names)
        right = sum(categories[name]["right"] for name in names)
        return {"cases": cases_count, "right": right, "accuracy": right / cases_count if cases_count else None}

    for entry in categories.values():
        entry["accuracy"] = entry["right"] / entry["cases"]
        if task == "pinyin":
            entry["character_accuracy"] = entry.pop("character_accuracy_sum") / entry["cases"]
        else:
            entry.pop("character_accuracy_sum")
    clean = [name for name in categories if name.startswith("clean")]
    slips = [name for name in categories if not name.startswith("clean")]
    return {"categories": categories, "clean": total(clean), "slips": total(slips)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["english", "pinyin"], required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--json", type=Path)
    arguments = parser.parse_args()

    cases = [json.loads(line) for line in arguments.cases.read_text(encoding="utf-8").splitlines() if line]
    predictions = {}
    for line in arguments.predictions.read_text(encoding="utf-8").splitlines():
        if line:
            record = json.loads(line)
            predictions[record["id"]] = record["output"]
    summary = score(arguments.task, cases, predictions)
    summary.update({"engine": arguments.engine, "task": arguments.task, "cases_file": arguments.cases.name})

    print(f"{arguments.engine} on {arguments.cases.name}")
    for name, entry in summary["categories"].items():
        extra = f"   characters {entry['character_accuracy']:.4f}" if arguments.task == "pinyin" else ""
        missing = f"   missing {entry['missing']}" if entry["missing"] else ""
        print(f"  {name:24s} {entry['right']:4d} / {entry['cases']:4d} = {entry['accuracy']:.4f}{extra}{missing}")
    for group in ("clean", "slips"):
        entry = summary[group]
        print(f"  {'ALL ' + group.upper():24s} {entry['right']:4d} / {entry['cases']:4d} = {entry['accuracy']:.4f}")
    if arguments.json:
        arguments.json.parent.mkdir(parents=True, exist_ok=True)
        arguments.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

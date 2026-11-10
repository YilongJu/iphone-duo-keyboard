"""Scores one engine's outputs against the test cases.

Usage, from the repository root:
    python scripts/typing-evaluation/score.py --task english --cases scripts/typing-evaluation/cases/english.dev.jsonl \
        --predictions path/to/predictions.jsonl --engine NAME [--json path/to/summary.json]

A predictions file holds one JSON object per line with the case `id` and the engine's `output`.
A case without a prediction counts as wrong, and the script reports how many are missing.

English: an output is right when it equals the intended text, ignoring letter case.
Pinyin: an output is right when it equals the intended Chinese text. The script also reports
character accuracy, which is 1 minus the edit distance between output and intended text divided
by the length of the intended text, floored at 0, averaged over cases.

The script reports each category, then groups of categories:
- `clean`: text typed without a slip. Accuracy is the share the engine leaves right.
- `letter_slips` (English) and `finger_slips` (Pinyin): a wrong, missing, extra or swapped letter.
- `space_slips` (English): slips around the space bar. An engine that corrects one word at a
  time cannot repair these, so they stay apart from the letter slips.
- `symbol_slips` and `clean_symbols` (English, the files english-symbols.*.jsonl): a symbol or
  digit key in place of a letter, and real text with a symbol or digit that must stay as typed.
- Every other category is reported alone.

A slip case can name its clean twin (`twin`): the same text typed without the slip. For those
cases the script also reports the repair rate among the cases whose clean twin the engine gets
right. That number separates "did not repair the slip" from "cannot produce this text at all".
"""
import argparse
import json
from pathlib import Path

GROUPS = {
    "english": {
        "letter_slips": ["substitution_adjacent", "deletion", "double_letter", "extra_adjacent", "transposition", "two_errors", "short_word_slip"],
        "space_slips": ["space_missing", "space_to_letter", "space_transposed", "space_extra", "letter_to_space"],
        "symbol_slips": ["symbol_first_letter", "symbol_inner_letter", "symbol_first_letter_two_words", "symbol_plus_letter_slip"],
        "clean_symbols": ["clean_symbol_token", "clean_bracket_or_dot_word"],
    },
    "pinyin": {
        "finger_slips": ["substitution_adjacent", "deletion", "double_letter", "extra_adjacent", "transposition", "two_errors"],
    },
}


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


def _tally(task: str, rows: list[dict]) -> dict:
    """Counts for a list of scored cases."""
    entry = {"cases": len(rows), "right": sum(row["right"] for row in rows), "missing": sum(row["missing"] for row in rows)}
    entry["accuracy"] = entry["right"] / entry["cases"] if rows else None
    if task == "pinyin":
        entry["character_accuracy"] = sum(row["character_accuracy"] for row in rows) / len(rows) if rows else None
    paired = [row for row in rows if row["twin_right"] is not None]
    if paired:
        able = [row for row in paired if row["twin_right"]]
        entry["twin_right_cases"] = len(able)
        entry["accuracy_when_twin_right"] = sum(row["right"] for row in able) / len(able) if able else None
    return entry


def score(task: str, cases: list[dict], predictions: dict[str, str]) -> dict:
    scored = {}
    for case in cases:
        output = predictions.get(case["id"])
        intended = normalize(task, case["intended"])
        produced = normalize(task, output) if output is not None else None
        row = {"case": case, "missing": output is None, "right": produced == intended, "twin_right": None}
        if task == "pinyin":
            row["character_accuracy"] = 0.0 if produced is None else max(0.0, 1 - edit_distance(produced, intended) / len(intended))
        scored[case["id"]] = row
    for row in scored.values():
        twin = row["case"].get("twin")
        if twin is not None:
            row["twin_right"] = scored[twin]["right"]

    by_category: dict[str, list[dict]] = {}
    for row in scored.values():
        by_category.setdefault(row["case"]["category"], []).append(row)
    summary = {"categories": {name: _tally(task, rows) for name, rows in by_category.items()}, "groups": {}, "strata": {}}

    # A clean category that a named group lists stays out of the group `clean`.
    named = {category for members in GROUPS[task].values() for category in members}
    groups = {"clean": [name for name in by_category if name.startswith("clean") and name not in named]}
    groups.update({name: [category for category in members if category in by_category] for name, members in GROUPS[task].items()})
    for name, members in groups.items():
        rows = [row for category in members for row in by_category[category]]
        if rows:
            summary["groups"][name] = _tally(task, rows)
            summary["groups"][name]["categories"] = members

    # Finer cuts of the same cases, by a field that the case carries.
    for field, group in (("length_bin", "clean"), ("typed_parses_exactly", "finger_slips"), ("length_bin", "finger_slips")):
        rows = [row for category in groups.get(group, []) for row in by_category[category] if field in row["case"]]
        values = sorted({str(row["case"][field]) for row in rows})
        if values:
            summary["strata"][f"{group} by {field}"] = {
                value: _tally(task, [row for row in rows if str(row["case"][field]) == value]) for value in values
            }
    return summary


def print_summary(engine: str, task: str, label: str, summary: dict) -> None:
    def line(name: str, entry: dict) -> str:
        text = f"  {name:34s} {entry['right']:5d} / {entry['cases']:5d} = {entry['accuracy']:.4f}"
        if task == "pinyin":
            text += f"   characters {entry['character_accuracy']:.4f}"
        if entry.get("accuracy_when_twin_right") is not None:
            text += f"   when the clean twin is right: {entry['accuracy_when_twin_right']:.4f} of {entry['twin_right_cases']}"
        if entry["missing"]:
            text += f"   missing {entry['missing']}"
        return text

    print(f"{engine} on {label}")
    for name, entry in summary["categories"].items():
        print(line(name, entry))
    for name, entry in summary["groups"].items():
        print(line("GROUP " + name, entry))
    for title, values in summary["strata"].items():
        for value, entry in values.items():
            print(line(f"{title} = {value}", entry))


def load_cases(paths: list[Path]) -> list[dict]:
    return [json.loads(line) for path in paths for line in path.read_text(encoding="utf-8").splitlines() if line]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["english", "pinyin"], required=True)
    parser.add_argument("--cases", type=Path, required=True, nargs="+")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--json", type=Path)
    arguments = parser.parse_args()

    cases = load_cases(arguments.cases)
    predictions = {}
    for line in arguments.predictions.read_text(encoding="utf-8").splitlines():
        if line:
            record = json.loads(line)
            predictions[record["id"]] = record["output"]
    summary = score(arguments.task, cases, predictions)
    label = " + ".join(path.name for path in arguments.cases)
    summary.update({"engine": arguments.engine, "task": arguments.task, "cases_files": [path.name for path in arguments.cases]})
    print_summary(arguments.engine, arguments.task, label, summary)
    if arguments.json:
        arguments.json.parent.mkdir(parents=True, exist_ok=True)
        arguments.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

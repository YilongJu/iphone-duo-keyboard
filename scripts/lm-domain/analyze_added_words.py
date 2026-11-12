"""Counts the words that an arm adds to clean running text by repeating the next word.

The list builder of rounds 1 and 2 gave 200 clean running-text lists of round 2 a target that
adds the next word of the sentence, as "pay attention in" for the typed "pay attention". A
model that learned this writes "pay attention in in class". This script measures that error: in
the clean running text of the selection sets, it counts the words that the field holds twice in
a row where the typed sentence holds them once.

For every arm of build/lm-domain/results and every setting rule, the script prints the changed
words of each stream, and how many of them are such repeated words.

Usage, from the repository root:
    python3 scripts/lm-domain/analyze_added_words.py --results build/lm-domain/results --data build/lm-domain/data
"""
import argparse
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-domain"))
import harness  # noqa: E402

STREAMS = ("stream_select", "domain_stream_dev")


def repeated_words(typed: list[str], shown: list[str]) -> int:
    """The words that the field adds right before or after the same typed word."""
    count = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=typed, b=shown, autojunk=False).get_opcodes():
        if tag != "insert":
            continue
        for place in range(j1, j2):
            word = shown[place]
            if (place + 1 < len(shown) and shown[place + 1] == word) or (place > 0 and shown[place - 1] == word):
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()
    sets = harness.load_sets(arguments.data, "select")
    rows = []
    for folder in sorted(path.parent for path in arguments.results.glob("*/result.json")):
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        if "evaluation" not in result:
            continue
        for rule in ("shipped", "ceiling-0.3", "ceiling-0.2"):
            evaluation = result["evaluation"][rule]
            if evaluation is None:
                continue
            source = evaluation.get("same_setting_as", rule)
            outputs: dict[str, dict[str, str]] = {}
            with (folder / f"outputs.select.{source}.jsonl").open(encoding="utf-8") as file:
                for line in file:
                    row = json.loads(line)
                    if row["set"] in STREAMS:
                        outputs.setdefault(row["set"], {})[row["id"]] = row["output"]
            entry = {"arm": folder.name, "rule": rule}
            for name in STREAMS:
                changed = repeated = sentences = 0
                for case in sets[name]["cases"]:
                    shown = outputs[name][case["id"]]
                    changed += harness.changed_words(case, shown)
                    found = repeated_words(case["intended"].lower().split(), shown.lower().split())
                    repeated += found
                    sentences += int(found > 0)
                entry[name] = {"changed_words": changed, "repeated_words": repeated, "sentences_with_a_repeated_word": sentences}
            rows.append(entry)
            print(json.dumps(entry))
    if arguments.out is not None:
        arguments.out.write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

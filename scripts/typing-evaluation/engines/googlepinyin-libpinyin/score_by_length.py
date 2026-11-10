"""Counts the right clean cases of each engine name by the count of typed letters.

Usage, from the repository root, after the engine outputs exist:
    python3 scripts/typing-evaluation/engines/googlepinyin-libpinyin/score_by_length.py \
        --half dev --letters 39 NAME [NAME ...]

The script reads build/typing-evaluation/NAME/pinyin.HALF.jsonl. A case is right by the rule of
score.py: the output equals the intended text. The script also counts the clean outputs that
hold a Latin letter, which is a typed letter that the engine left unchanged.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts" / "typing-evaluation"))
from score import normalize  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
OUTPUT = ROOT / "build" / "typing-evaluation"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--half", choices=["dev", "test"], required=True)
    parser.add_argument("--letters", type=int, required=True, help="the count of letters that splits the cases")
    parser.add_argument("names", nargs="+")
    arguments = parser.parse_args()

    cases_file = CASES / f"pinyin.{arguments.half}.jsonl"
    cases = [json.loads(line) for line in cases_file.read_text(encoding="utf-8").split("\n") if line]
    clean = [case for case in cases if case["category"].startswith("clean")]
    longer = sum(len(case["typed"]) > arguments.letters for case in cases)
    print(f"{cases_file.name}: {longer} of {len(cases)} cases have more than {arguments.letters} letters")
    for name in arguments.names:
        outputs_file = OUTPUT / name / f"pinyin.{arguments.half}.jsonl"
        outputs = {}
        for line in outputs_file.read_text(encoding="utf-8").split("\n"):
            if line:
                record = json.loads(line)
                outputs[record["id"]] = record["output"]
        counts = {"short": [0, 0], "long": [0, 0]}
        with_latin_letter = 0
        for case in clean:
            output = outputs[case["id"]]
            group = "long" if len(case["typed"]) > arguments.letters else "short"
            counts[group][0] += normalize("pinyin", output) == normalize("pinyin", case["intended"])
            counts[group][1] += 1
            with_latin_letter += bool(re.search("[a-z]", output))
        short, long = counts["short"], counts["long"]
        print(f"  {name:38s} clean, {arguments.letters} letters or fewer: {short[0]:3d} / {short[1]:3d} = {short[0] / short[1]:.4f}"
              f"   clean, over {arguments.letters} letters: {long[0]:3d} / {long[1]:3d} = {long[0] / long[1]:.4f}"
              f"   clean outputs with a Latin letter: {with_latin_letter}")


if __name__ == "__main__":
    main()

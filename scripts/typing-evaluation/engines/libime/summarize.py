"""Prints one table per half from the summary files that score.py wrote for the libime engine names.

Usage, from the repository root, after score.py ran with --json:
    python3 scripts/typing-evaluation/engines/libime/summarize.py

The script reads build/typing-evaluation/libime*/pinyin.HALF.summary.json. It only prints numbers
that score.py computed.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUTPUT = ROOT / "build" / "typing-evaluation"


def main():
    for half in ("dev", "test"):
        summaries = []
        for path in sorted(OUTPUT.glob(f"libime*/pinyin.{half}.summary.json")):
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
        if not summaries:
            print(f"pinyin.{half}: summary files do not exist yet")
            continue
        categories = list(summaries[0]["categories"])
        print(f"pinyin.{half}: share of cases with an exact match")
        print("| engine | ALL CLEAN | ALL SLIPS | " + " | ".join(categories) + " |")
        print("| --- | --- | --- | " + " | ".join("---" for _ in categories) + " |")
        for summary in summaries:
            if list(summary["categories"]) != categories:
                raise ValueError(f"{summary['engine']}: the categories differ from {summaries[0]['engine']}")
            cells = [f"{summary['categories'][name]['accuracy']:.4f}" for name in categories]
            print(f"| {summary['engine']} | {summary['clean']['accuracy']:.4f} | {summary['slips']['accuracy']:.4f} | "
                  + " | ".join(cells) + " |")
        print(f"pinyin.{half}: character accuracy")
        print("| engine | " + " | ".join(categories) + " |")
        print("| --- | " + " | ".join("---" for _ in categories) + " |")
        for summary in summaries:
            cells = [f"{summary['categories'][name]['character_accuracy']:.4f}" for name in categories]
            print(f"| {summary['engine']} | " + " | ".join(cells) + " |")
        print()


if __name__ == "__main__":
    main()

"""Prints the scores of every engine in build/typing-evaluation/ as one Markdown table per half.

Usage, from the repository root, after score.py wrote its summary files with --json:
    python scripts/typing-evaluation/engines/english-baselines/print_scores.py

The script reads build/typing-evaluation/ENGINE/english.HALF.summary.json. A cell holds the share
of cases in which the engine's output equals the intended text.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUTPUT = ROOT / "build" / "typing-evaluation"


def main():
    for half in ("dev", "test"):
        summaries = {path.parent.name: json.loads(path.read_text(encoding="utf-8"))
                     for path in sorted(OUTPUT.glob(f"*/english.{half}.summary.json"))}
        if not summaries:
            raise SystemExit(f"{OUTPUT} does not hold a summary file for the {half} half")
        engines = list(summaries)
        categories = list(next(iter(summaries.values()))["categories"])
        for engine, summary in summaries.items():
            if list(summary["categories"]) != categories:
                raise ValueError(f"{engine} has other categories than {engines[0]} on the {half} half")
        print(f"\nShare of cases with the intended text, English {half} half\n")
        print("| Category | Cases | " + " | ".join(engines) + " |")
        print("| --- | ---: | " + " | ".join("---:" for _ in engines) + " |")
        for category in categories:
            cells = [f"{summaries[engine]['categories'][category]['accuracy']:.4f}" for engine in engines]
            print(f"| `{category}` | {summaries[engines[0]]['categories'][category]['cases']} | " + " | ".join(cells) + " |")
        for group in ("clean", "slips"):
            cells = [f"{summaries[engine][group]['accuracy']:.4f}" for engine in engines]
            print(f"| ALL {group.upper()} | {summaries[engines[0]][group]['cases']} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()

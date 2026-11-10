"""Prints one line for each engine from its score summaries under one folder.

Usage: python scripts/typing-evaluation/print_summaries.py FOLDER --task pinyin --half dev

The script reads every `ENGINE/TASK.HALF.summary.json` under FOLDER, at any depth. A summary is
the file that score.py writes. Each line shows the engine's accuracy on the clean cases and on
every slip group of the task.
"""

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--task", required=True, choices=["english", "pinyin"])
    parser.add_argument("--half", required=True, choices=["dev", "test"])
    arguments = parser.parse_args()

    paths = sorted(arguments.folder.rglob(f"{arguments.task}.{arguments.half}.summary.json"))
    if not paths:
        raise SystemExit(f"{arguments.folder} holds no {arguments.task}.{arguments.half}.summary.json")
    rows = []
    for path in paths:
        summary = json.loads(path.read_text(encoding="utf-8"))
        if "groups" not in summary:
            # A summary of the first test set does not hold groups, and its cases differ from
            # the cases of the summaries with groups, so the line says so in place of a score.
            print(f"{path.parent.name:44s} scored on the first test set, not comparable")
            continue
        rows.append((path.parent.name, summary["groups"]))
    rows.sort(key=lambda row: -row[1]["clean"]["accuracy"])
    for engine, groups in rows:
        fields = []
        for name, group in groups.items():
            field = f"{name} {group['accuracy']:.4f} (n={group['cases']})"
            if "accuracy_when_twin_right" in group:
                field += f", {group['accuracy_when_twin_right']:.4f} when the clean twin is right"
            fields.append(field)
        print(f"{engine:44s} " + " | ".join(fields))


if __name__ == "__main__":
    main()

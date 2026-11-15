"""Compares the keyboard's outputs of two runs of the workflow "Language model in the keyboard",
case by case, to show that the normal autocorrection did not change.

Usage: python3 compare_keyboard_runs.py BASE_DIR NEW_DIR
  BASE_DIR, NEW_DIR  the artifact "keyboard" of each run (gh run download RUN -n keyboard)
For each case file of the two artifacts (*.dev*.jsonl, the predictions with the model and with
the engine alone), compares each line as parsed JSON with the time fields left out, and prints
the cases that differ. Exits with 1 when a case differs or a file is missing on one side.
"""

import json
import pathlib
import sys

# Fields that hold times, which change from run to run on any runner.
TIME_FIELDS = {"milliseconds", "model_milliseconds", "time_ms", "elapsed_ms", "seconds"}


def strip_times(value):
    if isinstance(value, dict):
        return {key: strip_times(item) for key, item in value.items() if key not in TIME_FIELDS}
    if isinstance(value, list):
        return [strip_times(item) for item in value]
    return value


def main():
    base, new = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    names = sorted({path.name for path in base.glob("*.jsonl")} | {path.name for path in new.glob("*.jsonl")})
    status = 0
    total = 0
    for name in names:
        if not (base / name).exists() or not (new / name).exists():
            print(f"{name}: only in {'the new run' if (new / name).exists() else 'the base run'}")
            status = 1
            continue
        old_lines = (base / name).read_text(encoding="utf-8").splitlines()
        new_lines = (new / name).read_text(encoding="utf-8").splitlines()
        if len(old_lines) != len(new_lines):
            print(f"{name}: {len(old_lines)} cases against {len(new_lines)}")
            status = 1
            continue
        differing = [index for index, (a, b) in enumerate(zip(old_lines, new_lines))
                     if strip_times(json.loads(a)) != strip_times(json.loads(b))]
        total += len(old_lines)
        print(f"{name}: {len(old_lines)} cases, {len(differing)} differ")
        for index in differing[:5]:
            print(f"  case {index + 1}:\n    base {old_lines[index][:300]}\n    new  {new_lines[index][:300]}")
        if differing:
            status = 1
    print(f"{len(names)} files, {total} cases compared")
    sys.exit(status)


if __name__ == "__main__":
    main()

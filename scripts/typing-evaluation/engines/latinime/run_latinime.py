"""Runs the native suggest engine of the AOSP keyboard (LatinIME) over the English test cases.

Usage, from the repository root, after fetch_sources.sh and build.sh in this folder:
    python3 scripts/typing-evaluation/engines/latinime/run_latinime.py --half dev
    python3 scripts/typing-evaluation/engines/latinime/run_latinime.py --explain-samples
    python3 scripts/typing-evaluation/engines/latinime/run_latinime.py --list-engines

For each engine name the script writes build/typing-evaluation/NAME/english.HALF.jsonl with one
JSON object per case: the case `id` and the engine's `output`.

The script builds the keyboard layout from scripts/typing-evaluation/keyboard_noise.py and hands
the cases to latinime_driver, which calls the engine. README.md in this folder describes both.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVALUATION = HERE.parents[1]
ROOT = EVALUATION.parents[1]
sys.path.insert(0, str(EVALUATION))

import keyboard_noise as noise  # noqa: E402

CASES = EVALUATION / "cases"
OUTPUT = ROOT / "build" / "typing-evaluation"
BUILD = ROOT / "build" / "latinime"

# keyboard_noise.py measures in key widths and puts two rows one key width apart. The engine
# takes whole pixels. 108 pixels is one tenth of a screen 1080 pixels wide.
KEY_WIDTH = 108
ROW_HEIGHT = 108

# The auto-correction thresholds of java/res/values/config-auto-correction-thresholds.xml in the
# AOSP keyboard. SettingsValues.java uses "modest" whenever auto-correction is on, so "modest" is
# the stock setting. The other two stand in the same resource file, and the settings screen of
# this AOSP version does not offer them.
THRESHOLDS = {"modest": "0.185", "aggressive": "0.067", "very-aggressive": "-inf"}

# Engine name, mode and threshold. Mode "token": each space-separated token of `typed` is one
# composing word, as on a phone. Mode "span": the whole of `typed` is one touch sequence, and a
# typed space is a touch on the space bar.
ENGINES = [
    ("latinime-token", "token", "modest"),
    ("latinime-span", "span", "modest"),
    ("latinime-token-aggressive", "token", "aggressive"),
    ("latinime-span-aggressive", "span", "aggressive"),
    ("latinime-token-very-aggressive", "token", "very-aggressive"),
    ("latinime-span-very-aggressive", "span", "very-aggressive"),
]

# Context and typed text for --explain-samples: cases of the dev half, one for each category
# example of Table 3 in scripts/typing-evaluation/README.md, and the word "hid". The stock word
# list holds "hid" as a word and also maps "hid" to "his".
SAMPLES = [
    ("has tom tried doing", "this"),
    ("", "mary"),
    ("i", "hid"),
    ("he", "xcode"),
    ("i", "wrofe"),
    ("i", "accpt"),
    ("i don't think tom can be left", "allone"),
    ("it's divided", "injto"),
    ("his mom", "sepaks"),
    ("tom said that he wished he'd kissed mary", "oodbyye"),
    ("he said he", "wantedto"),
    ("i know that tom is about the same weight", "asmyou"),
    ("where's tom going", "tob e"),
    ("that's not my", "l aptop"),
    ("the notorious dictator abused his privileges to his heart's", "conte t"),
    ("", "youd"),
]


def pixels(value: float, unit: int) -> int:
    scaled = value * unit
    if scaled != int(scaled):
        raise ValueError(f"{value} key widths is not a whole number of pixels at {unit} pixels")
    return int(scaled)


def write_layout(path: Path) -> None:
    """Writes the key boxes for the driver: the 26 letter keys and the space bar.

    keyboard_noise.KEY_POSITION gives the center of each letter key in key widths, with q at
    (0, 0). The layout moves every key half a key right and half a row down, so the box of q
    starts at pixel (0, 0). The distances between key centers stay as keyboard_noise.py has them.
    The space bar is the row under the letters, below the keys of keyboard_noise.SPACE_NEIGHBORS.
    """
    keys = [
        (ord(letter), pixels(column, KEY_WIDTH), pixels(row, ROW_HEIGHT), KEY_WIDTH, ROW_HEIGHT)
        for letter, (column, row) in noise.KEY_POSITION.items()
    ]
    space_columns = [noise.KEY_POSITION[letter][0] for letter in noise.SPACE_NEIGHBORS]
    space_left = pixels(min(space_columns), KEY_WIDTH)
    space_right = pixels(max(space_columns) + 1, KEY_WIDTH)
    space_row = max(row for _, row in noise.KEY_POSITION.values()) + 1
    keys.append((ord(" "), space_left, pixels(space_row, ROW_HEIGHT), space_right - space_left, ROW_HEIGHT))
    lines = [
        f"keyboard_width\t{max(left + width for _, left, _, width, _ in keys)}",
        f"keyboard_height\t{max(top + height for _, _, top, _, height in keys)}",
        f"most_common_key_width\t{KEY_WIDTH}",
        f"most_common_key_height\t{ROW_HEIGHT}",
    ]
    lines += [f"key\t{code}\t{left}\t{top}\t{width}\t{height}" for code, left, top, width, height in keys]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def driver_command(arguments: argparse.Namespace, layout: Path) -> list[str]:
    for required in (arguments.driver, arguments.dictionary):
        if not required.is_file():
            raise SystemExit(f"{required} is missing: run fetch_sources.sh and build.sh first")
    command = [str(arguments.driver), "--dictionary", str(arguments.dictionary), "--layout", str(layout)]
    for name, mode, threshold in ENGINES:
        command += ["--engine", f"{name}:{mode}:{THRESHOLDS[threshold]}"]
    return command


def run_half(arguments: argparse.Namespace, layout: Path) -> None:
    cases_file = CASES / f"english.{arguments.half}.jsonl"
    cases = [json.loads(line) for line in cases_file.read_text(encoding="utf-8").split("\n") if line]
    lines = [f"{case['id']}\t{case['context']}\t{case['typed']}" for case in cases]
    completed = subprocess.run(
        driver_command(arguments, layout), input="\n".join(lines) + "\n",
        capture_output=True, text=True, encoding="utf-8")
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        raise SystemExit(f"latinime_driver stopped with exit code {completed.returncode}")

    outputs: dict[str, dict[str, str]] = {name: {} for name, _, _ in ENGINES}
    for line in completed.stdout.split("\n"):
        if line:
            case_id, name, output = line.split("\t", 2)
            outputs[name][case_id] = output
    for name, _, _ in ENGINES:
        missing = [case["id"] for case in cases if case["id"] not in outputs[name]]
        if missing:
            raise SystemExit(f"{name}: the driver gave no output for {len(missing)} cases, first {missing[0]}")
        target = OUTPUT / name / f"english.{arguments.half}.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "".join(json.dumps({"id": case["id"], "output": outputs[name][case["id"]]}, ensure_ascii=False) + "\n"
                    for case in cases),
            encoding="utf-8", newline="\n")
        print(f"{name}: wrote {len(cases)} outputs to {target.relative_to(ROOT)}")


def explain_samples(arguments: argparse.Namespace, layout: Path) -> None:
    lines = [f"sample-{index:02d}\t{context}\t{typed}" for index, (context, typed) in enumerate(SAMPLES)]
    completed = subprocess.run(
        driver_command(arguments, layout) + ["--explain", "--dump-layout"], input="\n".join(lines) + "\n",
        capture_output=True, text=True, encoding="utf-8")
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        raise SystemExit(f"latinime_driver stopped with exit code {completed.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--half", choices=["dev", "test"], help="run the cases of this half")
    action.add_argument("--explain-samples", action="store_true",
                        help="print the layout and the engine's suggestions for a few dev examples")
    action.add_argument("--list-engines", action="store_true", help="print the engine names")
    parser.add_argument("--driver", type=Path, default=BUILD / "latinime_driver")
    parser.add_argument("--dictionary", type=Path,
                        default=BUILD / "source" / "java" / "res" / "raw" / "main_en.dict")
    arguments = parser.parse_args()

    if arguments.list_engines:
        print("\n".join(name for name, _, _ in ENGINES))
        return
    layout = BUILD / "layout.tsv"
    write_layout(layout)
    if arguments.explain_samples:
        explain_samples(arguments, layout)
    else:
        run_half(arguments, layout)


if __name__ == "__main__":
    main()

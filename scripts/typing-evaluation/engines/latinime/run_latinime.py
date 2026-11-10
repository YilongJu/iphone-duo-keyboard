"""Runs the native suggest engine of the AOSP keyboard (LatinIME) over the English test cases.

Usage, from the repository root, after fetch_sources.sh and build.sh in this folder:
    python3 scripts/typing-evaluation/engines/latinime/run_latinime.py --tune-on-dev
    python3 scripts/typing-evaluation/engines/latinime/run_latinime.py --half dev
    python3 scripts/typing-evaluation/engines/latinime/run_latinime.py --controls
    python3 scripts/typing-evaluation/engines/latinime/run_latinime.py --explain-samples
    python3 scripts/typing-evaluation/engines/latinime/run_latinime.py --list-engines

--tune-on-dev scores the dev half at a grid of thresholds and writes the tuned threshold to
build/latinime/tuned-threshold.txt. The other actions that run the engine read that file.
--half writes build/typing-evaluation/NAME/english.HALF.jsonl for each engine name, with one JSON
object per case: the case `id` and the engine's `output`.
--controls prints four checks on the dev half that score.py does not make.

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
from score import score  # noqa: E402

CASES = EVALUATION / "cases"
OUTPUT = ROOT / "build" / "typing-evaluation"
# The cases from published misspelling lists, which build_external_english_cases.py writes.
EXTERNAL = OUTPUT / "external"
BUILD = ROOT / "build" / "latinime"
TUNED_THRESHOLD_FILE = BUILD / "tuned-threshold.txt"

# keyboard_noise.py measures in key widths and puts two rows one key width apart. The engine
# takes whole pixels. 108 pixels is one tenth of a screen 1080 pixels wide.
KEY_WIDTH = 108
ROW_HEIGHT = 108

# The auto-correction thresholds of java/res/values/config-auto-correction-thresholds.xml in the
# AOSP keyboard. SettingsValues.java uses "modest" whenever auto-correction is on, so "modest" is
# the stock setting. The other two stand in the same resource file, and the settings screen of
# this AOSP version does not offer them. "tuned" is the value that --tune-on-dev writes.
THRESHOLDS = {"modest": "0.185", "aggressive": "0.067", "very-aggressive": "-inf"}

# Engine name, mode and threshold. Mode "token": each space-separated token of `typed` is one
# composing word, as on a phone. Mode "span": the whole of `typed` is one touch sequence, and a
# typed space is a touch on the space bar.
ENGINES = [
    ("latinime-token", "token", "modest"),
    ("latinime-span", "span", "modest"),
    ("latinime-token-tuned", "token", "tuned"),
    ("latinime-span-tuned", "span", "tuned"),
    ("latinime-token-aggressive", "token", "aggressive"),
    ("latinime-span-aggressive", "span", "aggressive"),
    ("latinime-token-very-aggressive", "token", "very-aggressive"),
    ("latinime-span-very-aggressive", "span", "very-aggressive"),
]

# The task picks a setting on the dev half by the share of slips repaired, with the share of
# clean cases kept at 0.98 or more (scripts/typing-evaluation/README.md, Table 1, at the commit
# this adapter was written against). --clean-floor sets another value.
CLEAN_FLOOR = 0.98
# The grid of --tune-on-dev: the stock value, then steps of 0.01 up to 0.60, then three wide
# steps. "inf" switches the threshold rule off, so that only a whitelist entry replaces a word.
TUNING_GRID = ["0.185"] + [f"{0.19 + 0.01 * step:.2f}" for step in range(42)] + ["0.8", "1", "inf"]

# Context and typed text for --explain-samples: cases of the dev half, one for each category
# example of Table 3 in scripts/typing-evaluation/README.md, the word "hid", and one correct
# two-word text. The stock word list holds "hid" as a word and also maps "hid" to "his".
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
    ("where's tom going", "to be"),
]

EngineSetting = tuple[str, str, str]  # Engine name, mode, threshold value for the driver.


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


def engine_settings() -> list[EngineSetting]:
    """The eight engine names with their threshold values. Reads the tuned threshold from its file."""
    if not TUNED_THRESHOLD_FILE.is_file():
        raise SystemExit(f"{TUNED_THRESHOLD_FILE} is missing: run this script with --tune-on-dev first")
    values = dict(THRESHOLDS, tuned=TUNED_THRESHOLD_FILE.read_text(encoding="utf-8").strip())
    return [(name, mode, values[threshold]) for name, mode, threshold in ENGINES]


def driver_command(arguments: argparse.Namespace, layout: Path, engines: list[EngineSetting]) -> list[str]:
    for required in (arguments.driver, arguments.dictionary):
        if not required.is_file():
            raise SystemExit(f"{required} is missing: run fetch_sources.sh and build.sh first")
    command = [str(arguments.driver), "--dictionary", str(arguments.dictionary), "--layout", str(layout)]
    for name, mode, threshold in engines:
        command += ["--engine", f"{name}:{mode}:{threshold}"]
    return command


def run_driver(arguments: argparse.Namespace, layout: Path, inputs: list[tuple[str, str, str]],
               engines: list[EngineSetting], options: tuple[str, ...] = ()) -> dict[str, dict[str, str]]:
    """Runs (id, context, typed) triples through the driver. Returns output by engine name and id.

    `options` holds extra driver arguments, such as ("--lookup", "incremental").
    """
    lines = [f"{case_id}\t{context}\t{typed}" for case_id, context, typed in inputs]
    completed = subprocess.run(
        driver_command(arguments, layout, engines) + list(options), input="\n".join(lines) + "\n",
        capture_output=True, text=True, encoding="utf-8")
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        raise SystemExit(f"latinime_driver stopped with exit code {completed.returncode}")
    outputs: dict[str, dict[str, str]] = {name: {} for name, _, _ in engines}
    for line in completed.stdout.split("\n"):
        if line:
            case_id, name, output = line.split("\t", 2)
            outputs[name][case_id] = output
    for name, _, _ in engines:
        missing = [case_id for case_id, _, _ in inputs if case_id not in outputs[name]]
        if missing:
            raise SystemExit(f"{name}: the driver gave no output for {len(missing)} cases, first {missing[0]}")
    return outputs


def load_cases(half: str, with_external_cases: bool = False) -> list[dict]:
    files = [CASES / f"english.{half}.jsonl"]
    if with_external_cases:
        files.append(EXTERNAL / f"english.{half}.jsonl")
    return [json.loads(line) for path in files for line in path.read_text(encoding="utf-8").split("\n") if line]


def clean_and_slip_shares(cases: list[dict], outputs: dict[str, str]) -> tuple[float, float]:
    """The share of clean cases kept and the share of slip cases repaired.

    Both come from the per-category counts of score.py. A category whose name starts with
    "clean" holds clean cases, and every other category holds slips. These are the totals that
    score.py prints as ALL CLEAN and ALL SLIPS.
    """
    categories = score("english", cases, outputs)["categories"]
    clean = [entry for name, entry in categories.items() if name.startswith("clean")]
    slips = [entry for name, entry in categories.items() if not name.startswith("clean")]
    return (sum(entry["right"] for entry in clean) / sum(entry["cases"] for entry in clean),
            sum(entry["right"] for entry in slips) / sum(entry["cases"] for entry in slips))


def tune_on_dev(arguments: argparse.Namespace, layout: Path) -> None:
    """Scores the dev half at each threshold of the grid and writes the tuned threshold.

    The tuned threshold is the lowest grid value at which token mode keeps the clean floor of
    the clean dev cases. A lower threshold repairs more slips, so the lowest value that keeps
    the floor is the setting that the task's rule picks. The test half takes no part.
    """
    floor = arguments.clean_floor
    cases = load_cases("dev")
    inputs = [(case["id"], case["context"], case["typed"]) for case in cases]
    grid = [(f"grid-{mode}-{threshold}", mode, threshold) for threshold in TUNING_GRID for mode in ("token", "span")]
    outputs = run_driver(arguments, layout, inputs, grid)
    typed_as_is = clean_and_slip_shares(cases, {case["id"]: case["typed"] for case in cases})
    print("Dev shares by auto-correction threshold")
    print(f"  typed text as it is   clean {typed_as_is[0]:.4f}  slips {typed_as_is[1]:.4f}")
    tuned = None
    for threshold in TUNING_GRID:
        token_clean, token_slips = clean_and_slip_shares(cases, outputs[f"grid-token-{threshold}"])
        span_clean, span_slips = clean_and_slip_shares(cases, outputs[f"grid-span-{threshold}"])
        if tuned is None and token_clean >= floor:
            tuned = threshold
        print(f"  threshold {threshold:>5s}   token clean {token_clean:.4f} slips {token_slips:.4f}"
              f"   span clean {span_clean:.4f} slips {span_slips:.4f}")
    if tuned is None:
        raise SystemExit(f"token mode keeps less than {floor} of the clean dev cases at every grid threshold")
    TUNED_THRESHOLD_FILE.parent.mkdir(parents=True, exist_ok=True)
    TUNED_THRESHOLD_FILE.write_text(tuned + "\n", encoding="utf-8", newline="\n")
    print(f"Tuned threshold: {tuned}, the lowest grid value at which token mode keeps {floor} "
          f"of the clean dev cases. Written to {TUNED_THRESHOLD_FILE.relative_to(ROOT)}")


def run_half(arguments: argparse.Namespace, layout: Path) -> None:
    cases = load_cases(arguments.half, arguments.with_external_cases)
    engines = engine_settings()
    outputs = run_driver(arguments, layout, [(case["id"], case["context"], case["typed"]) for case in cases], engines)
    for name, mode, threshold in engines:
        target = OUTPUT / name / f"english.{arguments.half}.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "".join(json.dumps({"id": case["id"], "output": outputs[name][case["id"]]}, ensure_ascii=False) + "\n"
                    for case in cases),
            encoding="utf-8", newline="\n")
        (target.parent / "settings.json").write_text(
            json.dumps({"engine": name, "mode": mode, "threshold": threshold}) + "\n",
            encoding="utf-8", newline="\n")
        print(f"{name} ({mode} mode, threshold {threshold}): wrote {len(cases)} outputs to {target.relative_to(ROOT)}")


def report_changes(cases: list[dict], first: dict[str, dict[str, str]], second: dict[str, dict[str, str]],
                   ignore_case: bool) -> None:
    """Prints, for each engine name, the number of cases whose output differs between two runs."""
    for name, _, _ in ENGINES:
        changed = []
        for case in cases:
            before, after = first[name][case["id"]], second[name][case["id"]]
            if (before.lower() != after.lower()) if ignore_case else (before != after):
                changed.append((case["typed"], before, after))
        print(f"  {name:32s} {len(changed):4d} / {len(cases):4d}")
        for typed, before, after in changed[:5]:
            print(f"      typed {typed!r}: {before!r} becomes {after!r}")


def run_controls(arguments: argparse.Namespace, layout: Path) -> None:
    """Four checks on the dev half that score.py does not make."""
    cases = load_cases("dev")
    engines = engine_settings()
    inputs = [(case["id"], case["context"], case["typed"]) for case in cases]
    baseline = run_driver(arguments, layout, inputs, engines)

    # Control 1: the same cases with the context removed. The stock dictionary does not hold
    # word pairs, so the previous words should not change an output.
    without_context = run_driver(arguments, layout, [(case["id"], "", case["typed"]) for case in cases], engines)
    print("Control 1: dev outputs that change when the context is removed")
    report_changes(cases, baseline, without_context, ignore_case=False)

    # Control 2: correct two-word text. The clean categories hold one word each, so they do not
    # show how often an engine changes two correct words typed with their space. This control
    # types the intended text of each dev case that holds two words.
    two_words = [case for case in cases if " " in case["intended"]]
    typed_right = run_driver(
        arguments, layout, [(case["id"], case["context"], case["intended"]) for case in two_words], engines)
    print("Control 2: dev two-word targets typed without a slip, share left unchanged (letter case ignored)")
    for name, _, _ in ENGINES:
        kept = sum(typed_right[name][case["id"]].lower() == case["intended"].lower() for case in two_words)
        print(f"  {name:32s} {kept:4d} / {len(two_words):4d} = {kept / len(two_words):.4f}")
        shown = 0
        for case in two_words:
            output = typed_right[name][case["id"]]
            if output.lower() != case["intended"].lower() and shown < 5:
                shown += 1
                print(f"      changed: {case['intended']!r} to {output!r}")

    # Control 3: the lookup sequence. The scored runs ask the engine once for each word, in a new
    # session. On a phone the keyboard keeps one session and may ask after every key, and the
    # engine then continues its last search. This control asks after every key in one session.
    incremental = run_driver(arguments, layout, inputs, engines, ("--lookup", "incremental"))
    print("Control 3: dev outputs that change when the engine is asked after every key in one session")
    report_changes(cases, baseline, incremental, ignore_case=False)

    # Control 4: auto-capitalization. The scored runs type every letter in lower case. On a phone
    # the first letter of an empty text field is in upper case. This control types that letter in
    # upper case for the cases with an empty context, and compares the outputs without their case.
    capitalized = run_driver(arguments, layout, inputs, engines, ("--auto-capitalize",))
    empty_context = [case for case in cases if not case["context"]]
    print("Control 4: dev outputs of the cases with an empty context that change, letter case ignored,")
    print("           when the first letter is typed in upper case")
    report_changes(empty_context, baseline, capitalized, ignore_case=True)


def explain_samples(arguments: argparse.Namespace, layout: Path) -> None:
    lines = [f"sample-{index:02d}\t{context}\t{typed}" for index, (context, typed) in enumerate(SAMPLES)]
    completed = subprocess.run(
        driver_command(arguments, layout, engine_settings())
        + ["--explain", "--dump-layout", "--dictionary-statistics"],
        input="\n".join(lines) + "\n", capture_output=True, text=True, encoding="utf-8")
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        raise SystemExit(f"latinime_driver stopped with exit code {completed.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--tune-on-dev", action="store_true",
                        help="score the dev half at a grid of thresholds and write the tuned threshold")
    action.add_argument("--half", choices=["dev", "test"], help="run the cases of this half")
    action.add_argument("--controls", action="store_true", help="print the four controls on the dev half")
    action.add_argument("--explain-samples", action="store_true",
                        help="print the dictionary counts, the layout and the suggestions for a few dev examples")
    action.add_argument("--list-engines", action="store_true", help="print the engine names")
    parser.add_argument("--clean-floor", type=float, default=CLEAN_FLOOR,
                        help="for --tune-on-dev: the share of clean dev cases that the tuned threshold must keep")
    parser.add_argument("--with-external-cases", action="store_true",
                        help="for --half: also run the cases of build/typing-evaluation/external/, "
                             "from published misspelling lists")
    parser.add_argument("--driver", type=Path, default=BUILD / "latinime_driver")
    parser.add_argument("--dictionary", type=Path,
                        default=BUILD / "source" / "java" / "res" / "raw" / "main_en.dict")
    arguments = parser.parse_args()
    # Whole lines at once, so that the driver's messages keep their place in a log.
    sys.stdout.reconfigure(line_buffering=True)

    if arguments.list_engines:
        print("\n".join(name for name, _, _ in ENGINES))
        return
    layout = BUILD / "layout.tsv"
    write_layout(layout)
    if arguments.tune_on_dev:
        tune_on_dev(arguments, layout)
    elif arguments.explain_samples:
        explain_samples(arguments, layout)
    elif arguments.controls:
        run_controls(arguments, layout)
    else:
        run_half(arguments, layout)


if __name__ == "__main__":
    main()

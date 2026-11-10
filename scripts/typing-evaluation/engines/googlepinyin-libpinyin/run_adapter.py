"""Runs one engine program of this group over the Pinyin test cases and writes the engine's outputs.

Usage, from the repository root:
    python3 scripts/typing-evaluation/engines/googlepinyin-libpinyin/run_adapter.py \
        --engine NAME --half dev -- PROGRAM [ARGUMENT ...]

The program gets one line per case on standard input: the case id, a tab, and the typed letters.
The program writes one line per case on standard output: the case id, a tab, and the text.

The script writes two files in build/typing-evaluation/NAME/:
    pinyin.HALF.jsonl        one JSON object per line with the case `id` and the engine's `output`
    pinyin.HALF.adapter.txt  the program's standard error (the adapter statistics) and the run time
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
OUTPUT = ROOT / "build" / "typing-evaluation"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    parser.add_argument("--half", choices=["dev", "test"], required=True)
    parser.add_argument("--samples", type=int, default=2, help="print this many outputs per category")
    parser.add_argument("command", nargs="+", help="the engine program and its arguments, after --")
    arguments = parser.parse_args()
    command = [part for index, part in enumerate(arguments.command) if not (index == 0 and part == "--")]

    cases_file = CASES / f"pinyin.{arguments.half}.jsonl"
    cases = [json.loads(line) for line in cases_file.read_text(encoding="utf-8").split("\n") if line]
    lines = "".join(f"{case['id']}\t{case['typed']}\n" for case in cases)

    started = time.monotonic()
    completed = subprocess.run(command, input=lines.encode("utf-8"), capture_output=True)
    seconds = time.monotonic() - started
    statistics = completed.stderr.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise SystemExit(f"{command[0]} ended with code {completed.returncode}:\n{statistics}")

    records = [line.split("\t", 1) for line in completed.stdout.decode("utf-8").split("\n") if line]
    for record in records:
        if len(record) != 2:
            raise SystemExit(f"{command[0]} wrote a line without a tab: {record[0]!r}")
    expected = [case["id"] for case in cases]
    returned = [identifier for identifier, _ in records]
    if returned != expected:
        raise SystemExit(
            f"{command[0]} returned {len(returned)} ids for {len(expected)} cases, or the ids are in a different order")
    outputs = dict(records)

    folder = OUTPUT / arguments.engine
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"pinyin.{arguments.half}.jsonl").write_text(
        "".join(json.dumps({"id": case["id"], "output": outputs[case["id"]]}, ensure_ascii=False) + "\n" for case in cases),
        encoding="utf-8", newline="\n")
    timing = (f"run time: {seconds:.2f} seconds for {len(cases)} cases, with the program start and the data load\n"
              f"mean time for one case: {1000 * seconds / len(cases):.2f} milliseconds\n")
    (folder / f"pinyin.{arguments.half}.adapter.txt").write_text(statistics + timing, encoding="utf-8", newline="\n")

    print(f"{arguments.engine} on {cases_file.name}: {' '.join(command)}")
    print("  " + (statistics + timing).rstrip("\n").replace("\n", "\n  "))
    shown = {}
    for case in cases:
        if shown.get(case["category"], 0) < arguments.samples:
            shown[case["category"]] = shown.get(case["category"], 0) + 1
            print(f"  sample {case['category']}: {case['typed']} -> {outputs[case['id']]} (intended {case['intended']})")


if __name__ == "__main__":
    main()

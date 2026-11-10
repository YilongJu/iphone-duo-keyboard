"""Runs the Duo typing engine (Engine/duo_engine.c) over the test cases and scores it.

Usage, from the repository root, after building Engine/duo_cli.c into build/engine/duo_cli:
    python3 scripts/typing-evaluation/run_duo_engine.py --task english --half dev [name=value ...]

A name=value argument sets one engine parameter for this run, such as margin_known=4.
The outputs go to build/typing-evaluation/duo-engine/.
"""
import argparse
import json
import subprocess
from pathlib import Path

from score import score

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
OUTPUT = ROOT / "build" / "typing-evaluation" / "duo-engine"
LEXICON = {"english": ROOT / "Shared" / "lexicon-english.bin", "pinyin": ROOT / "Shared" / "lexicon-pinyin.bin"}


def run(task: str, half: str, settings: list[str], cli: Path) -> tuple[list[dict], dict[str, str]]:
    cases = [json.loads(line) for line in (CASES / f"{task}.{half}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if task == "english":
        # The engine sees the word right before the typed text, as the keyboard does.
        lines = [f"{case['id']}\t{case['context'].split(' ')[-1] if case['context'] else ''}\t{case['typed']}" for case in cases]
    else:
        lines = [f"{case['id']}\t{case['typed']}" for case in cases]
    completed = subprocess.run(
        [str(cli), task, str(LEXICON[task]), *settings],
        input="\n".join(lines) + "\n", capture_output=True, text=True, encoding="utf-8", check=True)
    predictions = dict(line.split("\t", 1) for line in completed.stdout.splitlines())
    return cases, predictions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["english", "pinyin"], required=True)
    parser.add_argument("--half", choices=["dev", "test"], required=True)
    parser.add_argument("--cli", type=Path, default=ROOT / "build" / "engine" / "duo_cli")
    parser.add_argument("--show-misses", type=int, default=0, help="print this many wrong cases per category")
    parser.add_argument("settings", nargs="*")
    arguments = parser.parse_args()

    cases, predictions = run(arguments.task, arguments.half, arguments.settings, arguments.cli)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / f"{arguments.task}.{arguments.half}.jsonl").write_text(
        "".join(json.dumps({"id": case["id"], "output": predictions.get(case["id"], "")}, ensure_ascii=False) + "\n" for case in cases),
        encoding="utf-8", newline="\n")
    summary = score(arguments.task, cases, predictions)
    print(f"duo-engine on {arguments.task}.{arguments.half} {' '.join(arguments.settings)}")
    for name, entry in summary["categories"].items():
        extra = f"   characters {entry['character_accuracy']:.4f}" if arguments.task == "pinyin" else ""
        print(f"  {name:24s} {entry['right']:4d} / {entry['cases']:4d} = {entry['accuracy']:.4f}{extra}")
    for group in ("clean", "slips"):
        entry = summary[group]
        print(f"  {'ALL ' + group.upper():24s} {entry['right']:4d} / {entry['cases']:4d} = {entry['accuracy']:.4f}")
    if arguments.show_misses:
        shown = {}
        for case in cases:
            output = predictions.get(case["id"], "")
            if output.lower() != case["intended"].lower() and shown.get(case["category"], 0) < arguments.show_misses:
                shown[case["category"]] = shown.get(case["category"], 0) + 1
                context = f"[{case.get('context', '')}] " if arguments.task == "english" else ""
                print(f"    MISS {case['category']}: {context}{case['typed']!r} -> {output!r}, wanted {case['intended']!r}")


if __name__ == "__main__":
    main()

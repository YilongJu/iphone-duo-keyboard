"""Runs the Duo typing engine (Engine/duo_engine.c) over the test cases and scores it.

Usage, from the repository root, after building Engine/duo_cli.c into build/engine/duo_cli:
    python3 scripts/typing-evaluation/run_duo_engine.py --task english --half dev [name=value ...]

A name=value argument sets one engine parameter for this run, such as margin_known=4.
The outputs go to build/typing-evaluation/duo-engine/. The English run also reads the cases
from published misspelling lists in build/typing-evaluation/external/, when that file exists.
The task english-symbols runs the English engine on cases/english-symbols.HALF.jsonl, the cases
with a symbol or digit key in place of a letter. The task english-apostrophe-words runs it on
cases/english-apostrophe-words.HALF.jsonl, the words with and without an apostrophe.
"""
import argparse
import json
import subprocess
from pathlib import Path

from score import load_cases, print_summary, score

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
EXTERNAL = ROOT / "build" / "typing-evaluation" / "external"
OUTPUT = ROOT / "build" / "typing-evaluation" / "duo-engine"
LEXICON = {"english": ROOT / "Shared" / "lexicon-english.bin", "pinyin": ROOT / "Shared" / "lexicon-pinyin.bin"}
# The task names of the command line, each with the engine mode and the scoring rules it uses.
ENGINE_TASK = {"english": "english", "english-symbols": "english", "english-apostrophe-words": "english", "pinyin": "pinyin"}


def case_files(task: str, half: str) -> list[Path]:
    files = [CASES / f"{task}.{half}.jsonl"]
    external = EXTERNAL / f"{task}.{half}.jsonl"
    if external.exists():
        files.append(external)
    return files


def run_timed(task: str, cases: list[dict], settings: list[str], cli: Path, lexicon: Path) -> tuple[dict[str, str], str]:
    """Runs the engine in the mode `task`, english or pinyin. Returns its outputs and its report
    of the processor time per input."""
    if task == "english":
        # The engine sees the word right before the typed text, as the keyboard does.
        lines = [f"{case['id']}\t{case['context'].split(' ')[-1] if case['context'] else ''}\t{case['typed']}" for case in cases]
    else:
        lines = [f"{case['id']}\t{case['typed']}" for case in cases]
    completed = subprocess.run(
        [str(cli), task, str(lexicon), *settings],
        input="\n".join(lines) + "\n", capture_output=True, text=True, encoding="utf-8", check=True)
    return dict(line.split("\t", 1) for line in completed.stdout.splitlines()), completed.stderr.strip()


def run(task: str, cases: list[dict], settings: list[str], cli: Path, lexicon: Path) -> dict[str, str]:
    return run_timed(task, cases, settings, cli, lexicon)[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=sorted(ENGINE_TASK), required=True)
    parser.add_argument("--half", choices=["dev", "test"], required=True)
    parser.add_argument("--cli", type=Path, default=ROOT / "build" / "engine" / "duo_cli")
    parser.add_argument("--lexicon", type=Path)
    parser.add_argument("--name", default="duo-engine", help="the engine name in the output file names")
    parser.add_argument("--show-misses", type=int, default=0, help="print this many wrong cases per category")
    parser.add_argument("--show-time", action="store_true", help="print the engine's processor time per input")
    parser.add_argument("settings", nargs="*")
    arguments = parser.parse_args()

    files = case_files(arguments.task, arguments.half)
    cases = load_cases(files)
    engine_task = ENGINE_TASK[arguments.task]
    lexicon = arguments.lexicon or LEXICON[engine_task]
    predictions, time_report = run_timed(engine_task, cases, arguments.settings, arguments.cli, lexicon)
    if arguments.show_time:
        print(time_report)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    stem = f"{arguments.name}.{arguments.task}.{arguments.half}"
    (OUTPUT / f"{stem}.jsonl").write_text(
        "".join(json.dumps({"id": case["id"], "output": predictions.get(case["id"], "")}, ensure_ascii=False) + "\n" for case in cases),
        encoding="utf-8", newline="\n")
    summary = score(engine_task, cases, predictions)
    summary.update({"engine": arguments.name, "task": arguments.task, "settings": arguments.settings})
    (OUTPUT / f"{stem}.summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print_summary(arguments.name + (" " + " ".join(arguments.settings) if arguments.settings else ""), engine_task,
                  " + ".join(path.name for path in files), summary)
    if arguments.show_misses:
        shown = {}
        for case in cases:
            output = predictions.get(case["id"], "")
            if output.lower() != case["intended"].lower() and shown.get(case["category"], 0) < arguments.show_misses:
                shown[case["category"]] = shown.get(case["category"], 0) + 1
                context = f"[{case.get('context', '')}] " if engine_task == "english" else ""
                print(f"    MISS {case['category']}: {context}{case['typed']!r} -> {output!r}, wanted {case['intended']!r}")


if __name__ == "__main__":
    main()

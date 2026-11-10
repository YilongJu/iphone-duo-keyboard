"""Scores the Duo typing engine under several settings, to choose settings on the dev half.

Usage, from the repository root:
    python3 scripts/typing-evaluation/sweep_duo_engine.py --task english "margin_known=4" "margin_known=5 missing_space=4"

Each quoted argument is one set of name=value pairs. An empty string scores the built-in settings.
The script prints one line per set with the accuracy of each group and the engine's processor
time per input, and it always reads the dev half: the test half is for the final table only.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from run_duo_engine import ENGINE_TASK, LEXICON, ROOT, case_files, run_timed
from score import load_cases, score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=sorted(ENGINE_TASK), required=True)
    parser.add_argument("--cli", type=Path, default=ROOT / "build" / "engine" / "duo_cli")
    parser.add_argument("--lexicon", type=Path)
    parser.add_argument("--categories", action="store_true", help="also print each category")
    parser.add_argument("--jobs", type=int, help="how many sets run at one time; 1 gives times that compare")
    parser.add_argument("settings", nargs="+")
    arguments = parser.parse_args()

    cases = load_cases(case_files(arguments.task, "dev"))
    engine_task = ENGINE_TASK[arguments.task]
    lexicon = arguments.lexicon or LEXICON[engine_task]

    def one(settings: str):
        predictions, time_report = run_timed(engine_task, cases, settings.split(), arguments.cli, lexicon)
        return settings, score(engine_task, cases, predictions), time_report

    # Each run is its own process, so threads are enough to use every core.
    with ThreadPoolExecutor(max_workers=arguments.jobs) as pool:
        results = list(pool.map(one, arguments.settings))

    for settings, summary, time_report in results:
        parts = []
        for name, entry in summary["groups"].items():
            text = f"{name} {entry['accuracy']:.4f}"
            if entry.get("accuracy_when_twin_right") is not None:
                text += f" (twin right: {entry['accuracy_when_twin_right']:.4f})"
            parts.append(text)
        alone = [
            f"{name} {entry['accuracy']:.4f}" for name, entry in summary["categories"].items()
            if not any(name in group.get("categories", []) for group in summary["groups"].values())
        ]
        # The report ends with the time, as in "duo_cli: 5754 inputs, 12.345 ms of processor time per input".
        time_text = time_report.rsplit(", ", 1)[-1]
        print(f"[{settings or 'built-in'}]  " + "  ".join(parts + alone) + f"  ({time_text})")
        if arguments.categories:
            for name, entry in summary["categories"].items():
                print(f"      {name:28s} {entry['accuracy']:.4f}")


if __name__ == "__main__":
    main()

"""Scores the Duo typing engine under several settings, to choose settings on the dev half.

Usage, from the repository root:
    python3 scripts/typing-evaluation/sweep_duo_engine.py --task english "margin_known=4" "margin_known=5 missing_space=4"

Each quoted argument is one set of name=value pairs. An empty string scores the built-in settings.
The script prints one line per set with the accuracy of each group, and it always reads the dev
half: the test half is for the final table only.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from run_duo_engine import LEXICON, ROOT, case_files, run
from score import load_cases, score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["english", "pinyin"], required=True)
    parser.add_argument("--cli", type=Path, default=ROOT / "build" / "engine" / "duo_cli")
    parser.add_argument("--lexicon", type=Path)
    parser.add_argument("--categories", action="store_true", help="also print each category")
    parser.add_argument("settings", nargs="+")
    arguments = parser.parse_args()

    cases = load_cases(case_files(arguments.task, "dev"))
    lexicon = arguments.lexicon or LEXICON[arguments.task]

    def one(settings: str):
        predictions = run(arguments.task, cases, settings.split(), arguments.cli, lexicon)
        return settings, score(arguments.task, cases, predictions)

    # Each run is its own process, so threads are enough to use every core.
    with ThreadPoolExecutor() as pool:
        results = list(pool.map(one, arguments.settings))

    for settings, summary in results:
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
        print(f"[{settings or 'built-in'}]  " + "  ".join(parts + alone))
        if arguments.categories:
            for name, entry in summary["categories"].items():
                print(f"      {name:28s} {entry['accuracy']:.4f}")


if __name__ == "__main__":
    main()

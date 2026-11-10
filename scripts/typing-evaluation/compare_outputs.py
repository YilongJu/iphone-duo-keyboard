"""Lists the cases that one engine converts to the wanted text and another engine does not.

Usage:
  python scripts/typing-evaluation/compare_outputs.py CASES RIGHT_OUTPUTS WRONG_OUTPUTS [--category clean] [--limit 40]

CASES is a case file with `id`, `typed`, `intended` and `category` on each line. The two output
files hold `{"id", "output"}` lines, as every engine adapter writes them. The script prints the
cases where RIGHT_OUTPUTS matches `intended` and WRONG_OUTPUTS does not, and the two counts.
"""

import argparse
import json
from pathlib import Path


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument("right_outputs", type=Path)
    parser.add_argument("wrong_outputs", type=Path)
    parser.add_argument("--category", default=None)
    parser.add_argument("--limit", type=int, default=40)
    arguments = parser.parse_args()

    cases = read_lines(arguments.cases)
    first = {line["id"]: line["output"] for line in read_lines(arguments.right_outputs)}
    second = {line["id"]: line["output"] for line in read_lines(arguments.wrong_outputs)}
    only_first = []
    only_second = 0
    both = 0
    total = 0
    for case in cases:
        if arguments.category is not None and not case["category"].startswith(arguments.category):
            continue
        total += 1
        first_right = first[case["id"]] == case["intended"]
        second_right = second[case["id"]] == case["intended"]
        both += first_right and second_right
        only_second += second_right and not first_right
        if first_right and not second_right:
            only_first.append((case["typed"], case["intended"], second[case["id"]]))
    print(f"{total} cases: both right {both}, only the first engine right {len(only_first)}, "
          f"only the second engine right {only_second}")
    for typed, expected, output in only_first[: arguments.limit]:
        print(f"  {typed}  wanted {expected}  second engine gave {output}")


if __name__ == "__main__":
    main()

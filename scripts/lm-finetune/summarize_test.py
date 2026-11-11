"""Builds the test-half tables of scripts/lm-finetune/README.md from the folder of read_test.py.

The paired numbers compare each arm with a reference arm, as summarize.py does on dev.

Usage, from the repository root:
    python3 scripts/lm-finetune/summarize_test.py --test build/lm-finetune/results/test --reference stock-tuned
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune"))
import rerank  # noqa: E402
from read_test import PUBLISHED_TEST, TEST_FILES  # noqa: E402
from summarize import (CLEAN_CATEGORIES, GROUP_ORDER, PUBLISHED_SOURCES, bootstrap, group_of, mcnemar,  # noqa: E402
                       read_predictions, right_of)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--reference", required=True)
    arguments = parser.parse_args()
    result = json.loads((arguments.test / "result.json").read_text(encoding="utf-8"))
    test = rerank.load_cases(TEST_FILES)
    published = rerank.load_cases([PUBLISHED_TEST])
    names = [arm["name"] for arm in result["plan"]["arms"]]
    arms = {name: {"test": right_of(test, read_predictions(arguments.test / f"{name}.test.jsonl")),
                   "published": right_of(published, read_predictions(arguments.test / f"{name}.published_test.jsonl"))}
            for name in names}

    def count(name, cases, keep, which="test"):
        chosen = [c for c in cases if keep(c)]
        return f"{sum(arms[name][which][c['id']] for c in chosen)}/{len(chosen)}"

    print(f"Test scores per group ({len(test)} generated cases)\n")
    print("| Arm | " + " | ".join(GROUP_ORDER) + " | all test cases |")
    print("| --- |" + " --- |" * (len(GROUP_ORDER) + 1))
    for name in names:
        cells = [count(name, test, lambda c, g=g: group_of(c) == g) for g in GROUP_ORDER]
        print(f"| {name} | " + " | ".join(cells) + f" | {count(name, test, lambda c: True)} |")

    print("\nPublished misspellings of the test half, and the generated test cases with an empty context\n")
    print("| Arm | " + " | ".join(PUBLISHED_SOURCES) + " | all published | generated, empty context |")
    print("| --- |" + " --- |" * (len(PUBLISHED_SOURCES) + 2))
    for name in names:
        cells = [count(name, published, lambda c, s=s: c["category"] == f"real_misspelling_{s}", "published")
                 for s in PUBLISHED_SOURCES]
        cells.append(count(name, published, lambda c: True, "published"))
        cells.append(count(name, test, lambda c: c["context"] == ""))
        print(f"| {name} | " + " | ".join(cells) + " |")

    reference = arms[arguments.reference]
    print(f"\nPaired comparison with {arguments.reference} on the generated test cases\n")
    print(f"| Arm | right only by the arm | right only by {arguments.reference} | difference | exact McNemar p | "
          "95% bootstrap interval | published: only arm / only reference | published McNemar p |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for name in names:
        if name == arguments.reference:
            continue
        mine, theirs = arms[name]["test"], reference["test"]
        only_mine = sum(mine[i] and not theirs[i] for i in mine)
        only_theirs = sum(theirs[i] and not mine[i] for i in mine)
        low, high = bootstrap(test, mine, theirs)
        p_mine, p_theirs = arms[name]["published"], reference["published"]
        p_only_mine = sum(p_mine[i] and not p_theirs[i] for i in p_mine)
        p_only_theirs = sum(p_theirs[i] and not p_mine[i] for i in p_mine)
        print(f"| {name} | {only_mine} | {only_theirs} | {only_mine - only_theirs:+d} | {mcnemar(only_mine, only_theirs):.2g} | "
              f"{low:+d} to {high:+d} | {p_only_mine} / {p_only_theirs} | {mcnemar(p_only_mine, p_only_theirs):.2g} |")

    if "control" in arms:
        print("\nTest clean cases broken and repaired against the control (broken / repaired)\n")
        print("| Arm | " + " | ".join(CLEAN_CATEGORIES) + " |")
        print("| --- |" + " --- |" * len(CLEAN_CATEGORIES))
        for name in names:
            if name == "control":
                continue
            cells = []
            for category in CLEAN_CATEGORIES:
                ids = [c["id"] for c in test if c["category"] == category]
                broken = sum(arms["control"]["test"][i] and not arms[name]["test"][i] for i in ids)
                repaired = sum(arms[name]["test"][i] and not arms["control"]["test"][i] for i in ids)
                cells.append(f"{broken} / {repaired}")
            print(f"| {name} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()

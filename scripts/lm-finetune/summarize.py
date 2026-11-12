"""Builds the result tables of scripts/lm-finetune/README.md from the folders of evaluate.py.

Each arm is NAME=FOLDER[:LABEL], where LABEL picks the predictions in the folder: "tuned" (the
setting from the tuning split, the default) or "published-setting" (the setting of
scripts/lm-rerank/README.md).

The paired numbers compare an arm with a reference arm case by case: the cases that only one of
the two gets right, the exact McNemar test on those cases (a two-sided binomial test), and a 95
percent bootstrap interval of the difference in right cases. The bootstrap draws groups of cases
that share a context and an intended text, 10,000 times.

Usage, from the repository root:
    python3 scripts/lm-finetune/summarize.py --data build/lm-finetune/data --reference stock-tuned \
        --arm control=RESULTS/stock:control --arm stock-tuned=RESULTS/stock ... > table.md
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
sys.path.insert(0, str(ROOT / "scripts" / "typing-evaluation"))
import rerank  # noqa: E402
from score import GROUPS, normalize  # noqa: E402

PUBLISHED_DEV = ROOT / "build" / "typing-evaluation" / "external" / "english.dev.jsonl"
GROUP_ORDER = ["clean", "letter_slips", "space_slips", "symbol_slips", "clean_symbols"]
CLEAN_CATEGORIES = ["clean_common", "clean_rare", "clean_names_and_terms", "clean_two_words",
                    "clean_symbol_token", "clean_bracket_or_dot_word"]
PUBLISHED_SOURCES = ["birkbeck", "holbrook", "aspell"]
BOOTSTRAP_DRAWS = 10000


def read_predictions(path: Path) -> dict[str, str]:
    return {r["id"]: r["output"] for r in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)}


def right_of(cases: list[dict], predictions: dict[str, str]) -> dict[str, bool]:
    return {c["id"]: normalize("english", predictions[c["id"]]) == normalize("english", c["intended"]) for c in cases}


def group_of(case: dict) -> str | None:
    for group, members in GROUPS["english"].items():
        if case["category"] in members:
            return group
    return "clean" if case["category"].startswith("clean") else None


def mcnemar(only_first: int, only_second: int) -> float:
    n = only_first + only_second
    if n == 0:
        return 1.0
    k = min(only_first, only_second)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def bootstrap(cases: list[dict], first: dict[str, bool], second: dict[str, bool]) -> tuple[int, int]:
    groups: dict[tuple, int] = {}
    for case in cases:
        key = (case["context"], case["intended"].strip().lower())
        groups[key] = groups.get(key, 0) + int(first[case["id"]]) - int(second[case["id"]])
    values = list(groups.values())
    rng = random.Random(20261110)
    draws = sorted(sum(rng.choice(values) for _ in values) for _ in range(BOOTSTRAP_DRAWS))
    return draws[int(0.025 * BOOTSTRAP_DRAWS)], draws[int(0.975 * BOOTSTRAP_DRAWS) - 1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--arm", action="append", required=True)
    parser.add_argument("--reference", required=True)
    arguments = parser.parse_args()

    dev = rerank.load_cases(rerank.CASE_FILES)
    published = rerank.load_cases([PUBLISHED_DEV])
    training = rerank.load_cases([arguments.data / "cases.train.jsonl"])
    seen_pairs = {(c["typed"], c["intended"].strip().lower()) for c in training if c["typed"] != c["intended"]}

    arms, results = {}, {}
    for spec in arguments.arm:
        name, rest = spec.split("=", 1)
        folder, _, label = rest.partition(":")
        folder = Path(folder)
        label = label or "tuned"
        arms[name] = {"dev": right_of(dev, read_predictions(folder / f"{label}.dev.jsonl")),
                      "published": right_of(published, read_predictions(folder / f"{label}.published_dev.jsonl"))}
        if label == "tuned":
            results[name] = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    reference = arms[arguments.reference]

    def count(name, cases, keep, which="dev"):
        right = arms[name][which]
        chosen = [c for c in cases if keep(c)]
        return f"{sum(right[c['id']] for c in chosen)}/{len(chosen)}"

    print("Dev scores per group\n")
    print("| Arm | " + " | ".join(GROUP_ORDER) + " | all dev cases |")
    print("| --- |" + " --- |" * (len(GROUP_ORDER) + 1))
    for name in arms:
        cells = [count(name, dev, lambda c, g=g: group_of(c) == g) for g in GROUP_ORDER]
        print(f"| {name} | " + " | ".join(cells) + f" | {count(name, dev, lambda c: True)} |")

    print("\nPublished misspellings of the dev half, and the generated dev cases with an empty context\n")
    print("| Arm | " + " | ".join(PUBLISHED_SOURCES) + " | all published | generated, empty context |")
    print("| --- |" + " --- |" * (len(PUBLISHED_SOURCES) + 2))
    for name in arms:
        cells = [count(name, published, lambda c, s=s: c["category"] == f"real_misspelling_{s}", "published")
                 for s in PUBLISHED_SOURCES]
        cells.append(count(name, published, lambda c: True, "published"))
        cells.append(count(name, dev, lambda c: c["context"] == ""))
        print(f"| {name} | " + " | ".join(cells) + " |")

    print(f"\nPaired comparison with {arguments.reference} on the 6,799 generated dev cases\n")
    print(f"| Arm | right only by the arm | right only by {arguments.reference} | difference | exact McNemar p | 95% bootstrap interval | published: only arm / only reference |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for name in arms:
        if name == arguments.reference:
            continue
        mine, theirs = arms[name]["dev"], reference["dev"]
        only_mine = sum(mine[i] and not theirs[i] for i in mine)
        only_theirs = sum(theirs[i] and not mine[i] for i in mine)
        low, high = bootstrap(dev, mine, theirs)
        p_mine, p_theirs = arms[name]["published"], reference["published"]
        published_cell = f"{sum(p_mine[i] and not p_theirs[i] for i in p_mine)} / {sum(p_theirs[i] and not p_mine[i] for i in p_mine)}"
        print(f"| {name} | {only_mine} | {only_theirs} | {only_mine - only_theirs:+d} | {mcnemar(only_mine, only_theirs):.2g} | "
              f"{low:+d} to {high:+d} | {published_cell} |")

    control = arms.get("control")
    if control is not None:
        print("\nClean cases broken and repaired against the control, per clean category (broken / repaired)\n")
        print("| Arm | " + " | ".join(CLEAN_CATEGORIES) + " |")
        print("| --- |" + " --- |" * len(CLEAN_CATEGORIES))
        for name in arms:
            if name == "control":
                continue
            cells = []
            for category in CLEAN_CATEGORIES:
                ids = [c["id"] for c in dev if c["category"] == category]
                broken = sum(control["dev"][i] and not arms[name]["dev"][i] for i in ids)
                repaired = sum(arms[name]["dev"][i] and not control["dev"][i] for i in ids)
                cells.append(f"{broken} / {repaired}")
            print(f"| {name} | " + " | ".join(cells) + " |")

    slip_cases = [c for c in dev if not c["category"].startswith("clean")]
    seen = [c for c in slip_cases if (c["typed"], c["intended"].strip().lower()) in seen_pairs]
    print(f"\nDev slip cases whose typed and intended pair is also a training case ({len(seen)} of {len(slip_cases)})\n")
    print("| Arm | pair in training | pair not in training |")
    print("| --- | --- | --- |")
    seen_ids = {c["id"] for c in seen}
    for name in arms:
        print(f"| {name} | {count(name, slip_cases, lambda c: c['id'] in seen_ids)} | "
              f"{count(name, slip_cases, lambda c: c['id'] not in seen_ids)} |")

    print("\nSettings from the tuning split, and the within-dev check\n")
    print("| Arm | weight | margin from typed | margin to typed | margin other | space after | tuning split right | "
          "dev-tuned setting, dev right | fold 0 to 1 | fold 1 to 0 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, result in results.items():
        if "tuning" not in result:
            continue
        s = result["tuning"]["setting"]
        within = result.get("within_dev")
        within_cells = ["", "", ""]
        if within:
            folds = within["fold_check"]
            within_cells = [str(within["dev"]["right"]), f"{folds[0]['gain_on_other_fold']:+d}", f"{folds[1]['gain_on_other_fold']:+d}"]
        print(f"| {name} | {s['weight']} | {s['margin_from_typed']} | {s['margin_to_typed']} | {s['margin_other']} | "
              f"{'on' if s['space_after'] else 'off'} | {result['tuning']['tune']['right']}/{result['cases']['tune']} | "
              + " | ".join(within_cells) + " |")


if __name__ == "__main__":
    main()

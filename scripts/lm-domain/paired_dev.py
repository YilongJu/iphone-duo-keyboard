"""Applies the paired dev comparison of pick condition 6, and measures the seed spread behind its margins.

Pick condition 6 of docs/lm-domain-design.md compares an entry with `ship` on the same dev
cases. For one part of the dev half, the net loss of an entry is the count of cases that only
`ship` has right, less the count of cases that only the entry has right. The paired bootstrap
draws the cases of the part again with replacement, as many as the part holds. The part passes
when two things hold. Fewer than 5 percent of the draws give a net loss of the margin or more.
And the score test of Tango (Statistics in Medicine 17, 1998, pages 891 to 908) rejects, at the
one-sided level 0.05, that the true net loss is the margin or more.

The share of such draws is computed exactly. A draw gives every case to one of three kinds:
only `ship` right, only the entry right, or the same for both. So the counts of a draw follow a
multinomial distribution, and the script sums its probabilities. The result has no random part.

The parts and their margins:
    all 6,799 dev cases                          0.5 percent of the cases
    letter slips, space slips, symbol slips      1 percent of the cases of the group, each

The script also compares every pair of seeds of one recipe (`mix` seeds 1 to 3, `dom-s100`
seeds 1 to 3) the same way, at each setting rule. These pairs give the net loss that two files
of one recipe show against each other.

Usage, from the repository root, on Linux:
    python3 scripts/lm-domain/paired_dev.py --results build/lm-domain/results --data build/lm-domain/data \
        --entries dom-s100-seed1@shipped dom-s100-seed1@ceiling-0.3 --out build/lm-domain/summary-paired/paired-dev.json
"""
import argparse
import itertools
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-domain"))
import harness  # noqa: E402

LEVEL = 0.05
# The margin of each part, as a share of the cases of the part.
MARGINS = {"all": 0.005, "letter_slips": 0.01, "space_slips": 0.01, "symbol_slips": 0.01}
RECIPES = {"mix": ["mix-seed1", "mix-seed2", "mix-seed3"], "dom-s100": ["dom-s100-seed1", "dom-s100-seed2", "dom-s100-seed3"]}
SPREAD_RULES = ("shipped", "ceiling-0.3")


def share_of_draws_at_or_over(only_first: int, only_second: int, cases: int, margin: float) -> float:
    """The exact share of paired bootstrap draws whose net loss is `margin` or more. A draw takes
    `cases` cases with replacement. B of them are cases that only the first file has right, and
    C are cases that only the second file has right. The net loss of the draw is B - C."""
    if only_first + only_second == 0:
        return 0.0 if margin > 0 else 1.0
    discordant = (only_first + only_second) / cases
    first_share = only_first / (only_first + only_second)

    def log_binomial(n: int, k: int, p: float) -> float:
        if p in (0.0, 1.0):
            return 0.0 if k == (n if p == 1.0 else 0) else -math.inf
        return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * math.log(p) + (n - k) * math.log(1 - p))

    total = 0.0
    for drawn in range(cases + 1):
        log_drawn = log_binomial(cases, drawn, discordant)
        if log_drawn < -60:
            continue
        # B - (drawn - B) >= margin, so B >= (drawn + margin) / 2.
        least = max(0, math.ceil((drawn + margin) / 2 - 1e-12))
        inner = sum(math.exp(log_binomial(drawn, b, first_share)) for b in range(least, drawn + 1))
        total += math.exp(log_drawn) * inner
    return total


def score_test(only_first: int, only_second: int, cases: int, margin: float) -> float:
    """The one-sided p-value of Tango's score test for paired shares. The null hypothesis says that
    the true net loss, as a share of the cases, is the margin or more. The variance uses the
    estimate of the share of cases that only the second file has right under that hypothesis."""
    delta = margin / cases
    w = -only_first - only_second + (2 * cases - only_first + only_second) * delta
    q = (math.sqrt(w * w + 8 * cases * only_second * delta * (1 - delta)) - w) / (4 * cases)
    z = (only_first - only_second - cases * delta) / math.sqrt(cases * (2 * q + delta * (1 - delta)))
    return 0.5 * math.erfc(-z / math.sqrt(2))


def dev_outputs(results: Path, arm: str, rule: str) -> dict[str, str]:
    """The dev outputs of an entry, at the lead of the apostrophe step that the pick reads it at
    (summarize3.py): its own lead, and lead 4 for the shipped file at the shipped setting."""
    import summarize3  # summarize3.py imports this file for the pick, so the import waits until here
    folder = results / arm
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    evaluation = result["evaluation"][rule]
    if evaluation is None:
        raise SystemExit(f"{arm} has no setting for the rule {rule}")
    source = evaluation.get("same_setting_as", rule)
    own = folder / f"outputs.select.{source}.own-lead.jsonl"
    path = own if own.exists() and not (arm == "ship" and rule == "shipped") else folder / f"outputs.select.{source}.jsonl"
    return summarize3.read_outputs(path)["dev"]


def compare(cases: list[dict], first: dict[str, str], second: dict[str, str]) -> dict:
    """The paired comparison of two files on the dev half, per part. The net loss counts the cases
    that the second file loses against the first."""
    group_of = {category: group for group, members in harness.GENERATED_GROUPS.items() for category in members}
    parts: dict[str, list[int]] = {name: [0, 0, 0] for name in MARGINS}
    for case in cases:
        a, b = harness.is_right(case, first[case["id"]]), harness.is_right(case, second[case["id"]])
        for name in ("all", group_of[case["category"]]):
            if name in parts:
                parts[name][0] += 1
                parts[name][1] += int(a and not b)
                parts[name][2] += int(b and not a)
    found = {}
    for name, (count, only_first, only_second) in parts.items():
        margin = MARGINS[name] * count
        share = share_of_draws_at_or_over(only_first, only_second, count, margin)
        p_value = score_test(only_first, only_second, count, margin)
        found[name] = {"cases": count, "only_first_right": only_first, "only_second_right": only_second,
                       "net_loss": only_first - only_second, "margin_in_cases": round(margin, 2),
                       "share_of_draws_at_or_over_the_margin": round(share, 5), "score_test_p": round(p_value, 5),
                       "passes": share < LEVEL and p_value < LEVEL}
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--entries", nargs="*", default=[], help="ARM@RULE, each compared with `ship`")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    cases = harness.load_sets(arguments.data, "select")["dev"]["cases"]
    ship = dev_outputs(arguments.results, "ship", "shipped")
    report: dict = {"level": LEVEL, "margins_as_shares_of_the_cases": MARGINS, "seed_pairs": [], "entries": {}}
    for recipe, arms in RECIPES.items():
        for rule in SPREAD_RULES:
            for first, second in itertools.permutations(arms, 2):
                parts = compare(cases, dev_outputs(arguments.results, first, rule), dev_outputs(arguments.results, second, rule))
                report["seed_pairs"].append({"recipe": recipe, "rule": rule, "first": first, "second": second, "parts": parts,
                                             "passes": all(part["passes"] for part in parts.values())})
    for text in arguments.entries:
        arm, rule = text.split("@")
        parts = compare(cases, ship, dev_outputs(arguments.results, arm, rule))
        report["entries"][text] = {"parts": parts, "passes": all(part["passes"] for part in parts.values())}
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("Seed pairs, all dev cases: recipe, rule, first, second, only first right, only second right, net loss, share of draws, "
          "p of the score test, passes all parts")
    for row in report["seed_pairs"]:
        part = row["parts"]["all"]
        print(row["recipe"], row["rule"], row["first"], row["second"], part["only_first_right"], part["only_second_right"], part["net_loss"],
              part["share_of_draws_at_or_over_the_margin"], part["score_test_p"], row["passes"])
    for text, entry in report["entries"].items():
        print(text, "passes" if entry["passes"] else "does not pass", json.dumps(entry["parts"]))


if __name__ == "__main__":
    main()

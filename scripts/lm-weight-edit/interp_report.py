"""Prints the tables of the interpolation part of docs/lm-weight-edit-design.md, and applies its
selection rule and its dev criteria.

For each family (a base and one fine-tune) it reads, under build/lm-weight-edit:
- results/NAME/: result.json and the predictions of evaluate.py, for a = 0, the grid and a = 1;
- extra/NAME/: extra.json and the predictions of eval_extra.py (stopping cases at the tuned
  setting, dev at the common setting, and the calibration-only candidates of a = 1).

Every count it prints from predictions is checked against the count evaluate.py stored.

Usage: python scripts/lm-weight-edit/interp_report.py [s] [d] [d2] [--json OUT.json]
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build" / "lm-weight-edit"
FINETUNE = ROOT.parent / "lm-finetune"
sys.path.insert(0, str(FINETUNE / "scripts" / "typing-evaluation"))
from score import normalize  # noqa: E402

GRID = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
FAMILIES = {
    "s": {"title": "SmolLM2-135M, LoRA fine-tune seed 1", "stock": ("results/smollm2-stock-q3", "extra/s-stock"),
          "tuned": ("results/smollm2-lora-seed1-q3", "extra/s-lora"), "prefix": "s-wise"},
    "d": {"title": "distilgpt2, LoRA fine-tune seed 1", "stock": ("results/finetune/stock-typed", "extra/d-stock"),
          "tuned": ("results/finetune/lora-seed1", "extra/d-lora"), "prefix": "d-wise"},
    "d2": {"title": "distilgpt2, LoRA fine-tune seed 2", "stock": ("results/finetune/stock-typed", "extra/d2-stock"),
           "tuned": ("results/finetune/lora-seed2", "extra/d2-lora"), "prefix": "d2-wise"},
}
CASE_FILES = {
    "dev": [FINETUNE / "scripts" / "typing-evaluation" / "cases" / name for name in ("english.dev.jsonl", "english-symbols.dev.jsonl")],
    "published_dev": [FINETUNE / "build" / "typing-evaluation" / "external" / "english.dev.jsonl"],
    "stop": [FINETUNE / "build" / "lm-finetune" / "data" / "cases.stop.jsonl"],
}
GROUP_COLUMNS = ["clean", "clean_symbols", "letter_slips", "space_slips", "symbol_slips", "apostrophe_missing", "real_word_slip"]
CLEAN_GROUPS = {"clean": ["clean_common", "clean_rare", "clean_names_and_terms", "clean_two_words"],
                "clean_symbols": ["clean_symbol_token", "clean_bracket_or_dot_word"]}
BOOTSTRAP_DRAWS = 10000


def read_cases(name: str) -> list[dict]:
    return [json.loads(line) for path in CASE_FILES[name] for line in path.read_text(encoding="utf-8").splitlines() if line]


def right_of(cases: list[dict], path: Path, stored: int) -> dict[str, bool]:
    predictions = {r["id"]: r["output"] for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}
    right = {c["id"]: normalize("english", predictions[c["id"]]) == normalize("english", c["intended"]) for c in cases}
    if sum(right.values()) != stored:
        raise SystemExit(f"{path}: {sum(right.values())} right from the predictions, {stored} stored")
    return right


def mcnemar(only_first: int, only_second: int) -> float:
    n = only_first + only_second
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(only_first, only_second) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def paired(first: dict[str, bool], second: dict[str, bool], ids=None) -> tuple[int, int, float]:
    ids = list(first) if ids is None else ids
    only_first = sum(first[i] and not second[i] for i in ids)
    only_second = sum(second[i] and not first[i] for i in ids)
    return only_first, only_second, mcnemar(only_first, only_second)


def bootstrap_half_gain(cases: list[dict], arm: dict, stock: dict, tuned: dict) -> tuple[float, float]:
    """The 95 percent interval of (right at a) less the mean of (right at 0) and (right at 1),
    over draws of the groups of one context and one intended text."""
    groups: dict[tuple, float] = {}
    for case in cases:
        key = (case["context"], case["intended"].strip().lower())
        i = case["id"]
        groups[key] = groups.get(key, 0.0) + arm[i] - 0.5 * (stock[i] + tuned[i])
    values = list(groups.values())
    rng = random.Random(20261110)
    draws = sorted(sum(rng.choices(values, k=len(values))) for _ in range(BOOTSTRAP_DRAWS))
    return draws[int(0.025 * BOOTSTRAP_DRAWS)], draws[int(0.975 * BOOTSTRAP_DRAWS) - 1]


def group_counts(summary: dict) -> dict[str, int]:
    counts = {name: entry["right"] for name, entry in summary["groups"].items()}
    for name in ("apostrophe_missing", "real_word_slip"):
        counts[name] = summary["categories"][name]["right"]
    return counts


def setting_text(setting: dict) -> str:
    return (f"{setting['weight']}; {setting['margin_from_typed']}, {setting['margin_to_typed']}, {setting['margin_other']}; "
            f"{'on' if setting['space_after'] else 'off'}")


def eligible(stop_summary: dict, stop_control: dict) -> bool:
    return all(stop_summary["groups"][g]["right"] >= stop_control["groups"][g]["right"] for g in CLEAN_GROUPS)


def choose(candidates: list[dict]) -> dict | None:
    """The selection rule: the eligible candidate with the most right stopping cases; a tie goes
    to the smaller key (the smaller coefficient, or the lower weight)."""
    allowed = [c for c in candidates if c["eligible"]]
    if not allowed:
        return None
    return sorted(allowed, key=lambda c: (-c["stop_right"], c["key"]))[0]


def family_report(key: str, cases: dict, output: dict) -> None:
    family = FAMILIES[key]
    dev, published = cases["dev"], cases["published_dev"]
    rows = []
    points = [(0.0, *family["stock"])] + [(a, f"results/{family['prefix']}-{a}", f"extra/{family['prefix']}-{a}") for a in GRID] \
        + [(1.0, *family["tuned"])]
    for a, result_dir, extra_dir in points:
        result_path, extra_path = OUT / result_dir / "result.json", OUT / extra_dir / "extra.json"
        if not result_path.exists() or not extra_path.exists():
            print(f"a = {a}: pending ({result_dir} or {extra_dir})", file=sys.stderr)
            continue
        result, extra = json.loads(result_path.read_text(encoding="utf-8")), json.loads(extra_path.read_text(encoding="utf-8"))
        if extra["model"] != result["model"] or extra["tuned"]["setting"] != result["tuning"]["setting"]:
            raise SystemExit(f"{extra_dir} does not belong to {result_dir}")
        row = {"a": a, "result": result, "extra": extra, "setting": result["tuning"]["setting"],
               "dev": right_of(dev, OUT / result_dir / "tuned.dev.jsonl", result["tuned"]["dev"]["right"]),
               "published": right_of(published, OUT / result_dir / "tuned.published_dev.jsonl", result["tuned"]["published_dev"]["right"]),
               "control_dev": right_of(dev, OUT / result_dir / "control.dev.jsonl", result["control"]["dev"]["right"]),
               "control_published": right_of(published, OUT / result_dir / "control.published_dev.jsonl",
                                             result["control"]["published_dev"]["right"]),
               "stop": extra["tuned"]["stop"], "stop_control": extra["control"]["stop"]}
        row["eligible"] = eligible(row["stop"], row["stop_control"])
        row["stop_right"] = row["stop"]["right"]
        row["key"] = a
        rows.append(row)
    by_a = {row["a"]: row for row in rows}
    if 0.0 not in by_a or 1.0 not in by_a:
        print(f"{key}: the a = 0 or a = 1 row is pending", file=sys.stderr)
        return
    stock, tuned = by_a[0.0], by_a[1.0]
    control_dev = stock["result"]["control"]["dev"]
    control_groups = group_counts(control_dev)
    stop_control = stock["stop_control"]
    span = tuned["result"]["tuned"]["dev"]["right"] - stock["result"]["tuned"]["dev"]["right"]

    print(f"\n### {family['title']}\n")
    print(f"Stopping cases: the control gets {stop_control['groups']['clean']['right']} clean and "
          f"{stop_control['groups']['clean_symbols']['right']} clean-symbol cases right, and {stop_control['right']} of {stop_control['cases']} in all.")
    print(f"Dev: the control gets {control_groups['clean']} clean and {control_groups['clean_symbols']} clean-symbol cases right, "
          f"{control_dev['right']} of {control_dev['cases']} in all, and {stock['result']['control']['published_dev']['right']} of 751 published misspellings.\n")

    print("Selection on the stopping cases, at each coefficient's tuning-split setting.\n")
    print("| a | setting: weight; margins from typed, to typed, other; space after | tuning split right | stopping clean | stopping clean symbols | stopping right | eligible |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        print(f"| {row['a']} | {setting_text(row['setting'])} | {row['result']['tuning']['tune']['right']} | {row['stop']['groups']['clean']['right']} | "
              f"{row['stop']['groups']['clean_symbols']['right']} | {row['stop']['right']} | {'yes' if row['eligible'] else 'no'} |")
    chosen = choose([row for row in rows if row["a"] in GRID])
    print(f"\nChosen coefficient: {chosen['a'] if chosen else 'none (the grid does not hold an eligible value)'}\n")

    print("Dev at each coefficient's tuning-split setting.\n")
    print("| a | clean of 973 | clean symbols of 429 | letter slips of 2,100 | space slips of 1,500 | symbol slips of 1,197 | apostrophe missing of 300 | real-word slips of 300 | all of 6,799 | share of the gain kept | clean rule | published of 751 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    print("| control | " + " | ".join(str(control_groups[g]) for g in GROUP_COLUMNS) + f" | {control_dev['right']} | | | {stock['result']['control']['published_dev']['right']} |")
    family_output = {"chosen": chosen["a"] if chosen else None, "rows": []}
    for row in rows:
        summary = row["result"]["tuned"]["dev"]
        counts = group_counts(summary)
        share = (summary["right"] - stock["result"]["tuned"]["dev"]["right"]) / span
        clean_rule = counts["clean"] >= control_groups["clean"] and counts["clean_symbols"] >= control_groups["clean_symbols"]
        row["share"], row["clean_rule"], row["counts"] = share, clean_rule, counts
        print(f"| {row['a']} | " + " | ".join(str(counts[g]) for g in GROUP_COLUMNS) + f" | {summary['right']} | {share:.2f} | "
              f"{'met' if clean_rule else 'not met'} | {row['result']['tuned']['published_dev']['right']} |")
        family_output["rows"].append({"a": row["a"], "setting": row["setting"], "eligible": row["eligible"], "stop_right": row["stop_right"],
                                      "dev": summary["right"], "counts": counts, "share": share, "clean_rule": clean_rule,
                                      "published": row["result"]["tuned"]["published_dev"]["right"]})
    passing = [row["a"] for row in rows if row["a"] in GRID and row["clean_rule"] and row["share"] > 0.5]
    print(f"\nGrid values that meet the clean rule and keep more than half the gain on dev: {passing if passing else 'none'}\n")
    family_output["passing_on_dev"] = passing

    print("Right dev cases per generated category.\n")
    categories = list(control_dev["categories"])
    print("| category (cases) | control | " + " | ".join(f"a = {row['a']}" for row in rows) + " |")
    print("| --- | --- |" + " --- |" * len(rows))
    for category in categories:
        cells = [str(row["result"]["tuned"]["dev"]["categories"][category]["right"]) for row in rows]
        print(f"| {category} ({control_dev['categories'][category]['cases']}) | {control_dev['categories'][category]['right']} | " + " | ".join(cells) + " |")

    print("\nClean dev cases against the control, published misspellings, and the half-gain interval.\n")
    print("| a | clean: wrong only by the arm / wrong only by the control (p) | clean symbols: the same (p) | half-gain interval | published: Birkbeck, Holbrook, Aspell | published against control: only arm / only control (p) | published against a = 1: only arm / only a = 1 (p) |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        cells = []
        for group, members in CLEAN_GROUPS.items():
            ids = [c["id"] for c in dev if c["category"] in members]
            repaired, broken, p = paired(row["dev"], row["control_dev"], ids)
            cells.append(f"{broken} / {repaired} ({p:.2g})")
        low, high = bootstrap_half_gain(dev, row["dev"], stock["dev"], tuned["dev"])
        sources = row["result"]["tuned"]["published_dev"]["categories"]
        source_text = ", ".join(str(sources[f"real_misspelling_{s}"]["right"]) for s in ("birkbeck", "holbrook", "aspell"))
        a_only, c_only, p_control = paired(row["published"], row["control_published"])
        a_only_1, one_only, p_one = paired(row["published"], tuned["published"])
        print(f"| {row['a']} | {cells[0]} | {cells[1]} | {low:+.0f} to {high:+.0f} | {source_text} | {a_only} / {c_only} ({p_control:.2g}) | "
              f"{a_only_1} / {one_only} ({p_one:.2g}) |")

    print("\nDev at the common setting of the family, " + setting_text(tuned["setting"]) + ".\n")
    print("| a | clean | clean symbols | real-word slips | all of 6,799 | published of 751 |")
    print("| --- | --- | --- | --- | --- | --- |")
    for row in rows:
        common = row["extra"].get("common")
        summary, published_right = (common["dev"], common["published_dev"]["right"]) if common else \
            (row["result"]["tuned"]["dev"], row["result"]["tuned"]["published_dev"]["right"])
        if common and common["setting"] != tuned["setting"]:
            raise SystemExit(f"a = {row['a']}: the common setting differs from the tuned setting of a = 1")
        if not common and row["a"] != 1.0:
            raise SystemExit(f"a = {row['a']}: the common-setting scores are missing")
        counts = group_counts(summary)
        print(f"| {row['a']} | {counts['clean']} | {counts['clean_symbols']} | {counts['real_word_slip']} | {summary['right']} | {published_right} |")

    candidates = []
    print("\nCalibration-only candidates: the fine-tune (a = 1) at the best tuning-split setting of each re-ranker weight.\n")
    print("| weight | setting | tuning split right | stopping clean | stopping clean symbols | stopping right | eligible | dev clean | dev clean symbols | dev all | clean rule | published |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for entry in tuned["extra"]["weight_candidates"]:
        if entry["setting"] is None:
            print(f"| {entry['weight']} | none keeps the clean groups of the tuning split | | | | | | | | | | |")
            continue
        counts = group_counts(entry["dev"])
        candidate = {"key": entry["weight"], "eligible": eligible(entry["stop"], stop_control), "stop_right": entry["stop"]["right"],
                     "dev": entry["dev"]["right"], "counts": counts, "published": entry["published_dev"]["right"], "setting": entry["setting"],
                     "clean_rule": counts["clean"] >= control_groups["clean"] and counts["clean_symbols"] >= control_groups["clean_symbols"]}
        candidates.append(candidate)
        print(f"| {entry['weight']} | {setting_text(entry['setting'])} | {entry['tune']['right']} | {entry['stop']['groups']['clean']['right']} | "
              f"{entry['stop']['groups']['clean_symbols']['right']} | {entry['stop']['right']} | {'yes' if candidate['eligible'] else 'no'} | "
              f"{counts['clean']} | {counts['clean_symbols']} | {entry['dev']['right']} | {'met' if candidate['clean_rule'] else 'not met'} | {candidate['published']} |")
    chosen_candidate = choose(candidates)
    print(f"\nChosen calibration-only candidate: {'weight ' + str(chosen_candidate['key']) if chosen_candidate else 'none'}\n")
    family_output["chosen_candidate"] = chosen_candidate
    family_output["candidates"] = candidates
    output[key] = family_output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("families", nargs="*", default=list(FAMILIES))
    parser.add_argument("--json", type=Path)
    arguments = parser.parse_args()
    cases = {name: read_cases(name) for name in ("dev", "published_dev")}
    output = {}
    for key in arguments.families:
        family_report(key, cases, output)
    if arguments.json:
        arguments.json.write_text(json.dumps(output, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

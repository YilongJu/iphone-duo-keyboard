"""Chooses the setting of one model from its scored grid, under a ceiling on changed correct words.

The grid holds the 2,160 settings of scripts/lm-rerank/rerank.py. Each row gives the right
generated tuning cases and the changed words of the clean running text of the tune bucket.
The rules, each named:

shipped        the setting that the keyboard ships: weight 1.0, margins 0 / 4 / 2, space-after on.
control-rule   the rule of round 2: at least as many right cases as the engine alone in the groups
               clean and clean symbols, and at most as many changed words as the engine alone.
ceiling-0.3    the changed words are at most 0.3 percent of the words of the tune running text.
ceiling-0.2    the same with 0.2 percent.

Among the settings that a rule allows, the setting with the most right generated tuning cases
wins. A tie goes to the fewer changed words, then to the earlier row of the grid. A rule that
allows no setting gives no setting.

Usage, for a grid of this harness or of scripts/lm-finetune2/evaluate2.py:
    python3 scripts/lm-domain/select_setting.py --grid RESULT/grid.jsonl --words 8487 \
        --control-clean 957 --control-clean-symbols 427 --control-changed-words 66
"""
import argparse
import json
import math
from pathlib import Path

SHIPPED = {"weight": 1.0, "margin_from_typed": 0, "margin_to_typed": 4, "margin_other": 2, "space_after": 1}
CEILINGS = {"ceiling-0.3": 0.003, "ceiling-0.2": 0.002}
RULES = ("shipped", "control-rule", *CEILINGS)


def same_setting(first: dict, second: dict) -> bool:
    return all(float(first[name]) == float(second[name]) for name in SHIPPED)


def select(rows: list[dict], words: int, control: dict) -> dict:
    """`rows` are grid rows: {"setting", "right", "groups": {"clean", "clean_symbols", ...},
    "changed_words"}. `control` gives the engine alone on the tuning sets: {"clean",
    "clean_symbols", "changed_words"}. The answer names, per rule, the row and the limit."""
    def best(allowed: list[dict]) -> dict | None:
        if not allowed:
            return None
        return min(allowed, key=lambda row: (-row["right"], row["changed_words"], row["index"]))

    rows = [{**row, "index": index} for index, row in enumerate(rows)]
    chosen = {}
    shipped = [row for row in rows if same_setting(row["setting"], SHIPPED)]
    if len(shipped) != 1:
        raise SystemExit(f"the grid holds the shipped setting {len(shipped)} times")
    chosen["shipped"] = {"row": shipped[0], "allowed": 1}
    keeps = [row for row in rows if row["groups"]["clean"] >= control["clean"]
             and row["groups"]["clean_symbols"] >= control["clean_symbols"]
             and row["changed_words"] <= control["changed_words"]]
    chosen["control-rule"] = {"row": best(keeps), "allowed": len(keeps), "limit_changed_words": control["changed_words"]}
    for rule, share in CEILINGS.items():
        limit = math.floor(share * words)
        allowed = [row for row in rows if row["changed_words"] <= limit]
        chosen[rule] = {"row": best(allowed), "allowed": len(allowed), "limit_changed_words": limit}
    return chosen


def frontier(rows: list[dict]) -> list[dict]:
    """The settings that no other setting of the grid passes on both counts: for each count of
    changed words, the most right generated tuning cases at that count or fewer."""
    result, most = [], -1
    for changed in sorted({row["changed_words"] for row in rows}):
        top = max((row for row in rows if row["changed_words"] == changed), key=lambda row: row["right"])
        if top["right"] > most:
            most = top["right"]
            result.append({"changed_words": changed, "right": top["right"], "setting": top["setting"]})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--words", type=int, required=True, help="words of the tune running text")
    parser.add_argument("--control-clean", type=int, required=True)
    parser.add_argument("--control-clean-symbols", type=int, required=True)
    parser.add_argument("--control-changed-words", type=int, required=True)
    arguments = parser.parse_args()
    rows = [json.loads(line) for line in arguments.grid.read_text(encoding="utf-8").splitlines() if line]
    control = {"clean": arguments.control_clean, "clean_symbols": arguments.control_clean_symbols,
               "changed_words": arguments.control_changed_words}
    chosen = select(rows, arguments.words, control)
    for rule, entry in chosen.items():
        row = entry["row"]
        print(rule, json.dumps({"allowed": entry["allowed"], "limit_changed_words": entry.get("limit_changed_words"),
                                "setting": row and row["setting"], "right": row and row["right"],
                                "changed_words": row and row["changed_words"]}))
    print("frontier", json.dumps(frontier(rows)))


if __name__ == "__main__":
    main()

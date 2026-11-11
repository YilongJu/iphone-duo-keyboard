"""Prints the tables of one result file of apostrophe_words.py as Markdown.

Usage: python3 scripts/lm-rerank/apostrophe_words_table.py build/lm-rerank/apostrophe-words/rerank/result.dev.json
"""
import json
import sys
from pathlib import Path

CATEGORIES = ["apostrophe_dropped_ambiguous", "clean_ambiguous_word", "apostrophe_added",
              "clean_ambiguous_contraction", "apostrophe_dropped"]
EXISTING_GROUPS = ["clean", "letter_slips", "space_slips", "symbol_slips", "clean_symbols"]
# The categories of the existing dev cases that no group holds.
EXISTING_ALONE = ["apostrophe_missing", "real_word_slip"]


def cell(entry) -> str:
    return f"{entry[0]}/{entry[1]}" if entry else ""


def main():
    result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    runs = result["runs"]
    half = result["half"]
    print(f"### Right {half} cases of the apostrophe words per category\n")
    print("| Run | Way of typing | " + " | ".join(CATEGORIES) + " | all |")
    print("| --- | --- |" + " --- |" * (len(CATEGORIES) + 1))
    for name, entry in runs.items():
        for way in ("word", "next_word"):
            tally = entry["group"][way]
            print(f"| {name} | {way.replace('_', ' ')} | " + " | ".join(cell(tally["categories"].get(c)) for c in CATEGORIES)
                  + f" | {tally['right']}/{tally['cases']} |")
    print()
    print("### Intended text among the readings of the last correction (oracle)\n")
    print("| Readings | Way of typing | " + " | ".join(CATEGORIES) + " | all |")
    print("| --- | --- |" + " --- |" * (len(CATEGORIES) + 1))
    for name, report in result["readings"].items():
        for way in ("word", "next_word"):
            tally = report[way]
            print(f"| {name} | {way.replace('_', ' ')} | " + " | ".join(cell(tally["categories"].get(c)) for c in CATEGORIES)
                  + f" | {tally['right']}/{tally['cases']} |")
    print()
    if any("existing" in entry for entry in runs.values()):
        print("### Right existing dev cases per group\n")
        print("| Run | " + " | ".join(EXISTING_GROUPS + EXISTING_ALONE) + " | all dev cases |")
        print("| --- |" + " --- |" * (len(EXISTING_GROUPS) + len(EXISTING_ALONE) + 1))
        for name, entry in runs.items():
            if "existing" not in entry:
                continue
            groups = entry["existing"]["groups"]
            alone = entry["existing"]["categories"]
            print(f"| {name} | " + " | ".join([f"{groups[g]['right']}/{groups[g]['cases']}" for g in EXISTING_GROUPS]
                                            + [f"{alone[c]['right']}/{alone[c]['cases']}" for c in EXISTING_ALONE])
                  + f" | {entry['existing']['right']}/{entry['existing']['cases']} |")
        print()
    if "chosen" in result:
        print(f"Settings that keep every existing category and the new controls: "
              f"{', '.join(result.get('allowed', [])) or 'none'}. Chosen: {result.get('chosen')}.\n")
        lost = result.get("existing_lost_against_shipped", {})
        print("Existing dev cases right in the shipped run and wrong in this run: "
              + ", ".join(f"{name} {len(ids)}" for name, ids in lost.items()) + ".\n")
        print(f"A keyboard that always shows the contraction gets {result['always_contraction']} of "
              f"{result['cases']} new cases right, and one that never does gets {result['never_contraction']}.\n")
    shown = [name for name in ("engine", "shipped", result.get("chosen")) if name in runs]
    shown += [name for name in runs if half == "test" and name.startswith("step ") and name not in shown]
    print("### Right cases per pair\n")
    header = [f"{name}, {way.replace('_', ' ')}" for name in shown for way in ("word", "next_word")]
    print("| Pair | Category | " + " | ".join(header) + " |")
    print("| --- | --- |" + " --- |" * len(header))
    pairs = runs["engine"]["group"]["word"]["pairs"]
    for pair in pairs:
        for category in CATEGORIES:
            if category not in pairs[pair]:
                continue
            values = [cell(runs[name]["group"][way]["pairs"][pair][category]) for name in shown for way in ("word", "next_word")]
            print(f"| {pair} | {category} | " + " | ".join(values) + " |")


if __name__ == "__main__":
    main()

"""Prints the tables of one result file of apostrophe_words.py as Markdown.

Usage: python3 scripts/lm-rerank/apostrophe_words_table.py build/lm-rerank/apostrophe-words/rerank/result.dev.json
"""
import json
import sys
from pathlib import Path

CATEGORIES = ["apostrophe_dropped_ambiguous", "clean_ambiguous_word", "apostrophe_added",
              "clean_ambiguous_contraction", "apostrophe_dropped"]
EXISTING_GROUPS = ["clean", "letter_slips", "space_slips", "symbol_slips", "clean_symbols"]


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
        print("| Run | " + " | ".join(EXISTING_GROUPS) + " | all dev cases |")
        print("| --- |" + " --- |" * (len(EXISTING_GROUPS) + 1))
        for name, entry in runs.items():
            if "existing" not in entry:
                continue
            groups = entry["existing"]["groups"]
            print(f"| {name} | " + " | ".join(f"{groups[g]['right']}/{groups[g]['cases']}" for g in EXISTING_GROUPS)
                  + f" | {entry['existing']['right']}/{entry['existing']['cases']} |")
        print()
        print(f"Margins that keep every existing group: {', '.join(result.get('allowed', [])) or 'none'}. "
              f"Chosen: {result.get('chosen')}.\n")
    shown = [name for name in ("engine", "shipped", result.get("chosen")) if name in runs]
    shown += [name for name in runs if half == "test" and name.startswith("apostrophe step") and name not in shown]
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

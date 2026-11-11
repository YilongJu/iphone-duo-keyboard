"""Prints the tables of one result of domain_pack.py as Markdown.

Usage:
    python3 scripts/lm-rerank/domain_pack_table.py build/lm-rerank/domain-pack/result.dev.json
"""
import json
import sys
from pathlib import Path

GROUPS = ["domain_clean", "domain_slips", "domain_phrases", "required", "neighbour_controls", "term_for_everyday_word",
          "capitals"]
EXISTING_GROUPS = ["clean", "letter_slips", "space_slips", "symbol_slips", "clean_symbols"]
EXISTING_ALONE = ["apostrophe_missing", "real_word_slip"]


def cell(pair) -> str:
    return f"{pair[0]}/{pair[1]}"


def main():
    result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    runs = result["configurations"]
    half = result["half"]
    print(f"Results of the vocabulary pack on the {half} half, {result['stream_sentences']} stream sentences.")
    print()
    print(f"Table 1. Right {half} cases of the new groups.")
    print()
    print("| Configuration | " + " | ".join(GROUPS) + " | all |")
    print("| --- |" + " --- |" * (len(GROUPS) + 1))
    for name, entry in runs.items():
        groups = entry["domain"]["groups"]
        print(f"| {name} | " + " | ".join(cell(groups[g]) for g in GROUPS)
              + f" | {entry['domain']['right']}/{entry['domain']['cases']} |")
    print()
    print(f"Table 2. Right {half} cases of each category.")
    print()
    names = list(runs)
    print("| Category | " + " | ".join(names) + " |")
    print("| --- |" + " --- |" * len(names))
    for category in next(iter(runs.values()))["domain"]["categories"]:
        print(f"| `{category}` | " + " | ".join(cell(runs[name]["domain"]["categories"][category]) for name in names) + " |")
    print()
    print(f"Table 3. Changed words of clean running text on the {half} half: per 1,000 typed words, the count, "
          "and the changed sentences with those that hold a changed word of the pack.")
    print()
    kinds = list(next(iter(runs.values()))["stream"])
    print("| Configuration | " + " | ".join(f"{kind}, per 1,000 | {kind}, words | {kind}, sentences" for kind in kinds) + " |")
    print("| --- |" + " --- |" * (3 * len(kinds)))
    for name, entry in runs.items():
        cells = []
        for kind in kinds:
            stream = entry["stream"][kind]
            cells += [str(stream["changed_words_per_1000"]), f"{stream['changed_words']} of {stream['words']}",
                      f"{stream['changed_sentences']} of {stream['sentences']}, {stream['changed_sentences_with_a_pack_word']}"]
        print(f"| {name} | " + " | ".join(cells) + " |")
    print()
    if "existing" in next(iter(runs.values())):
        print("Table 4. Right existing dev cases. The last two categories belong to no group.")
        print()
        print("| Configuration | " + " | ".join(EXISTING_GROUPS + EXISTING_ALONE) + " | all dev cases "
              "| apostrophe words, word | apostrophe words, next word |")
        print("| --- |" + " --- |" * (len(EXISTING_GROUPS) + len(EXISTING_ALONE) + 3))
        for name, entry in runs.items():
            existing = entry["existing"]
            cells = [f"{existing['groups'][g]['right']}/{existing['groups'][g]['cases']}" for g in EXISTING_GROUPS]
            cells += [f"{existing['categories'][c]['right']}/{existing['categories'][c]['cases']}" for c in EXISTING_ALONE]
            apostrophe = entry["apostrophe"]
            print(f"| {name} | " + " | ".join(cells) + f" | {existing['right']}/{existing['cases']} "
                  f"| {apostrophe['word']['right']}/{apostrophe['word']['cases']} "
                  f"| {apostrophe['next_word']['right']}/{apostrophe['next_word']['cases']} |")
        print()
        categories = list(next(iter(runs.values()))["existing"]["categories"])
        apostrophe_categories = list(next(iter(runs.values()))["apostrophe"]["word"]["categories"])
        print("Table 5. Right existing dev cases of each category, and the apostrophe words of each category.")
        print()
        print("| Category | " + " | ".join(names) + " |")
        print("| --- |" + " --- |" * len(names))
        for category in categories:
            print(f"| `{category}` | " + " | ".join(
                f"{runs[n]['existing']['categories'][category]['right']}/{runs[n]['existing']['categories'][category]['cases']}"
                for n in names) + " |")
        for way in ("word", "next_word"):
            for category in apostrophe_categories:
                print(f"| `{category}`, {way.replace('_', ' ')} | " + " | ".join(
                    cell(runs[n]["apostrophe"][way]["categories"][category]) for n in names) + " |")
        print()
        for name, entry in runs.items():
            differ = entry.get("existing_cases_that_differ_from_the_typing_without_capitals")
            if differ is not None:
                print(f"{name}: {len(differ)} existing cases differ in their letters from the typing that does not keep "
                      f"the typed capitals.")
        print()
    print("Table 6. Cases that the pack turns from right to wrong (lost) and from wrong to right (gained).")
    print()
    print("| Chooser | Set | lost | gained |")
    print("| --- | --- | --- | --- |")
    for chooser, effect in result["pack_effect"].items():
        for kind, entry in effect.items():
            print(f"| {chooser} | {kind} | {len(entry['lost'])} | {entry['gained_count']} |")
    print()
    for chooser, effect in result["pack_effect"].items():
        for kind, entry in effect.items():
            if not entry["lost"]:
                continue
            print(f"Lost with the pack, {chooser}, {kind}:")
            print()
            print("| Case | Category | Typed | Intended | Pack off | Pack on |")
            print("| --- | --- | --- | --- | --- | --- |")
            for row in entry["lost"][:60]:
                print(f"| {row['id']} | `{row['category']}` | {row['typed']} | {row['intended']} | {row['pack_off']} | {row['pack_on']} |")
            if len(entry["lost"]) > 60:
                print(f"| and {len(entry['lost']) - 60} more | | | | | |")
            print()
    agreement = result.get("merged_lexicon")
    if agreement:
        print("Table 7. The supplement against the comparison lexicon with the pack merged in, engine alone.")
        print()
        print("| Set | cases | same output | right with the supplement | right with the merged lexicon |")
        print("| --- | --- | --- | --- | --- |")
        for kind, row in agreement["sets"].items():
            print(f"| {kind} | {row['cases']} | {row['same']} | {row['right_supplement']} | {row['right_merged']} |")
        print()
        print(f"Stream, changed words per 1,000 with the merged lexicon: {agreement['stream']}.")
        print()


if __name__ == "__main__":
    main()

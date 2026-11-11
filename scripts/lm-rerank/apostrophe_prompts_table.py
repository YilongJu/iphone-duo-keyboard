"""Tables of the apostrophe step under each prompt, from result.dev.json of apostrophe_words.py
--steps prompts: for each prompt the setting that the design's rule picks, and its counts per pair.

The rule is the one of apostrophe_words.py `select`: every category of the existing dev cases keeps
at least the shipped count, and so do the controls of the new cases with the next word typed. Among
those settings the most right new cases with the next word typed count, the first on a tie.

Usage: python3 scripts/lm-rerank/apostrophe_prompts_table.py result.dev.json
"""
import json
import sys

PROMPTS = {"same": "(a) as today", "stock": "(b) stock prompt", "reading": "(c) reading as the typed span"}
PAIRS = ["its/it's", "were/we're", "well/we'll", "ill/i'll", "hell/he'll", "id/i'd", "lets/let's", "shed/she'd"]
CONTROLS = ["clean_ambiguous_word", "clean_ambiguous_contraction"]


def prompt_of(name: str) -> str:
    last = name.split(" ")[-1]
    return last if last in PROMPTS else "same"


def main():
    result = json.load(open(sys.argv[1], encoding="utf-8"))
    runs = result["runs"]
    base = runs["shipped"]

    def allowed(entry):
        existing = all(entry["existing"]["categories"][c]["right"] >= base["existing"]["categories"][c]["right"]
                       for c in base["existing"]["categories"])
        controls = all(entry["group"]["next_word"]["categories"][c][0] >= base["group"]["next_word"]["categories"][c][0]
                       for c in CONTROLS)
        return existing and controls

    rows = []
    for prompt, label in PROMPTS.items():
        names = [n for n in runs if n.startswith("step ") and prompt_of(n) == prompt]
        ok = [n for n in names if allowed(runs[n])]
        best_any = max(names, key=lambda n: runs[n]["group"]["next_word"]["right"]) if names else None
        chosen = max(ok, key=lambda n: runs[n]["group"]["next_word"]["right"]) if ok else None
        if names:
            rows.append((label, names, ok, chosen, best_any))

    print("Table A. The setting each prompt takes under the rule, and the best setting of each prompt "
          "without the rule.\n")
    print("| Prompt | settings | allowed by the rule | chosen | existing dev, chosen | new cases, next word, chosen "
          "| best without the rule | new cases, next word, best | existing dev, best |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for label, names, ok, chosen, best in rows:
        c = runs[chosen] if chosen else None
        b = runs[best]
        print(f"| {label} | {len(names)} | {len(ok)} | {chosen or 'none'} | "
              f"{c['existing']['right'] if c else '-'} | {c['group']['next_word']['right'] if c else '-'} | "
              f"{best} | {b['group']['next_word']['right']} | {b['existing']['right']} |")
    print(f"\nShipped run (step off): existing {base['existing']['right']}, new cases with the next word "
          f"{base['group']['next_word']['right']}.\n")

    print("Table B. Right dev cases per pair with the next word typed, at the setting each prompt takes "
          "under the rule. Dropped: the person meant the contraction. Control: the person meant the word "
          "without the apostrophe, as \"its stays its\".\n")
    head = "| Pair | " + " | ".join(f"{label}, dropped | {label}, control" for label, *_ in rows) + " |"
    print(head)
    print("| --- |" + " --- |" * (2 * len(rows)))
    for pair in PAIRS:
        cells = []
        for label, names, ok, chosen, best in rows:
            if chosen is None:
                cells += ["-", "-"]
                continue
            p = runs[chosen]["group"]["next_word"]["pairs"][pair]
            d = p.get("apostrophe_dropped_ambiguous")
            k = p.get("clean_ambiguous_word")
            cells += [f"{d[0]}/{d[1]}" if d else "-", f"{k[0]}/{k[1]}" if k else "-"]
        print(f"| {pair} | " + " | ".join(cells) + " |")

    print("\nTable C. The same pairs at the best setting of each prompt without the rule, with its existing "
          "dev count.\n")
    print(head)
    print("| --- |" + " --- |" * (2 * len(rows)))
    for pair in PAIRS:
        cells = []
        for label, names, ok, chosen, best in rows:
            p = runs[best]["group"]["next_word"]["pairs"][pair]
            d = p.get("apostrophe_dropped_ambiguous")
            k = p.get("clean_ambiguous_word")
            cells += [f"{d[0]}/{d[1]}" if d else "-", f"{k[0]}/{k[1]}" if k else "-"]
        print(f"| {pair} | " + " | ".join(cells) + " |")

    print("\nTable D. Every setting: existing dev cases lost against the shipped run, and new cases with the "
          "next word typed.\n")
    print("| Setting | existing dev | lost categories | new cases, next word | its dropped | its control |")
    print("| --- | --- | --- | --- | --- | --- |")
    for name, entry in runs.items():
        if not name.startswith("step "):
            continue
        lost = [c for c in base["existing"]["categories"]
                if entry["existing"]["categories"][c]["right"] < base["existing"]["categories"][c]["right"]]
        lost += [c for c in CONTROLS
                 if entry["group"]["next_word"]["categories"][c][0] < base["group"]["next_word"]["categories"][c][0]]
        its = entry["group"]["next_word"]["pairs"]["its/it's"]
        print(f"| {name} | {entry['existing']['right']} | {', '.join(lost) or 'none'} | "
              f"{entry['group']['next_word']['right']} | {its['apostrophe_dropped_ambiguous'][0]}/40 | "
              f"{its['clean_ambiguous_word'][0]}/40 |")


if __name__ == "__main__":
    main()

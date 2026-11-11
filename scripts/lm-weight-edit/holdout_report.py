"""Prints the tables of the held-out read (read_holdout.py of the second fine-tuning round) for
the arms of holdout-plan.json, from build/lm-weight-edit/holdout.

Table A gives the counts per arm. Table B applies the criteria of the design against the control:
the clean rule and the share of the generated-case gain kept. Table C gives paired counts against
the control and against the fine-tune of the same base, with the exact McNemar test.

Usage: python scripts/lm-weight-edit/holdout_report.py
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build" / "lm-weight-edit" / "holdout"
DATA = ROOT.parent / "lm-finetune2" / "build" / "lm-finetune2" / "data"
FILES = {"generated": "cases.generated.holdout.jsonl", "stream": "cases.stream.holdout.jsonl",
         "github": "cases.github.holdout.jsonl", "mitton": "cases.mitton-remainder.holdout.jsonl"}
CLEAN = {"clean": ["clean_common", "clean_rare", "clean_names_and_terms", "clean_two_words"],
         "clean_symbols": ["clean_symbol_token", "clean_bracket_or_dot_word"]}
# Each arm's a = 0 and a = 1 rows, for the share of the gain kept and the paired tests.
BASES = {"s": ("s-stock", "s-lora"), "d": ("d-stock", "d-lora")}


def normal(text: str) -> str:
    return text.strip().replace("’", "'").lower()


def mcnemar(first: int, second: int) -> float:
    n = first + second
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(first, second) + 1)) / 2 ** n)


def main():
    result = json.loads((OUT / "result.json").read_text(encoding="utf-8"))
    arms = result["arms"]
    cases = {name: [json.loads(line) for line in (DATA / file).read_text(encoding="utf-8").splitlines() if line]
             for name, file in FILES.items()}
    right = {}
    for arm in arms:
        for name, members in cases.items():
            predictions = {r["id"]: r["output"] for r in map(json.loads, (OUT / f"{arm}.{name}.jsonl").read_text(encoding="utf-8").splitlines())}
            right[(arm, name)] = {c["id"]: normal(predictions[c["id"]]) == normal(c["intended"]) for c in members}
            if sum(right[(arm, name)].values()) != arms[arm][name]["right"]:
                raise SystemExit(f"{arm} {name}: the predictions do not give the stored count")

    def group(arm: str, name: str) -> int:
        return arms[arm]["generated"]["groups"][name]["right"]

    control = arms["control"]
    print("Table A. Counts per arm on the held-out set.\n")
    print("| Arm | clean of 972 | clean symbols of 429 | letter slips of 2,074 | space slips of 1,476 | symbol slips of 1,196 | "
          "apostrophe missing of 298 | real-word slips of 300 | generated, all of 6,745 | changed words of 26,060 (closed, open) | "
          "changed sentences of 4,000 | `github_misspelling` of 1,500 | `github_real_word` of 1,000 | Birkbeck of 600 | Holbrook of 121 |")
    print("| --- |" + " --- |" * 14)
    for name, arm in arms.items():
        stream = arm["stream"]["categories"]
        print(f"| `{name}` | " + " | ".join(str(group(name, g)) for g in ("clean", "clean_symbols", "letter_slips", "space_slips",
                                                                         "symbol_slips", "apostrophe_missing", "real_word_slip"))
              + f" | {arm['generated']['right']} | {arm['stream']['stream']['changed_words']} ({stream['clean_stream_closed']['changed_words']}, "
              f"{stream['clean_stream_open']['changed_words']}) | {arm['stream']['stream']['changed_sentences']} | "
              f"{arm['github']['categories']['github_misspelling']['right']} | {arm['github']['categories']['github_real_word']['right']} | "
              f"{arm['mitton']['categories']['real_misspelling_birkbeck']['right']} | {arm['mitton']['categories']['real_misspelling_holbrook']['right']} |")

    print("\nTable B. The criteria of the design on the held-out set, against the control.\n")
    print("| Arm | clean rule | share of the generated gain kept | clean: wrong only by the arm / only by the control (p) | "
          "clean symbols: the same (p) | sentences changed only by the arm / only by the control (p) |")
    print("| --- | --- | --- | --- | --- | --- |")
    for name in arms:
        if name == "control":
            continue
        stock, tuned = BASES[name[0]]
        rule = all(group(name, g) >= group("control", g) for g in CLEAN)
        share = (arms[name]["generated"]["right"] - arms[stock]["generated"]["right"]) / \
            (arms[tuned]["generated"]["right"] - arms[stock]["generated"]["right"])
        cells = []
        for members in CLEAN.values():
            ids = [c["id"] for c in cases["generated"] if c["category"] in members]
            broken = sum(right[("control", "generated")][i] and not right[(name, "generated")][i] for i in ids)
            repaired = sum(right[(name, "generated")][i] and not right[("control", "generated")][i] for i in ids)
            cells.append(f"{broken} / {repaired} ({mcnemar(broken, repaired):.2g})")
        mine, theirs = right[(name, "stream")], right[("control", "stream")]
        only_arm = sum(theirs[i] and not mine[i] for i in mine)
        only_control = sum(mine[i] and not theirs[i] for i in mine)
        print(f"| `{name}` | {'met' if rule else 'not met'} | {share:.2f} | {cells[0]} | {cells[1]} | "
              f"{only_arm} / {only_control} ({mcnemar(only_arm, only_control):.2g}) |")

    def pair(first: str, second: str, set_name: str, keep) -> str:
        ids = [c["id"] for c in cases[set_name] if keep(c)]
        a, b = right[(first, set_name)], right[(second, set_name)]
        only_first = sum(a[i] and not b[i] for i in ids)
        only_second = sum(b[i] and not a[i] for i in ids)
        return f"{only_first} / {only_second} ({mcnemar(only_first, only_second):.2g})"

    print("\nTable C. Paired counts: right only by the arm / right only by the reference, with the exact McNemar p.\n")
    print("| Arm | `github_misspelling` against the control | `github_misspelling` against the fine-tune | Mitton pairs against the control | "
          "Mitton pairs against the fine-tune | clean sentences unchanged, against the fine-tune | generated cases against the fine-tune |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for name in arms:
        if name == "control":
            continue
        tuned = BASES[name[0]][1]
        misspelling = lambda c: c["category"] == "github_misspelling"  # noqa: E731
        everything = lambda c: True  # noqa: E731
        cells = [pair(name, "control", "github", misspelling), pair(name, tuned, "github", misspelling),
                 pair(name, "control", "mitton", everything), pair(name, tuned, "mitton", everything),
                 pair(name, tuned, "stream", everything), pair(name, tuned, "generated", everything)]
        print(f"| `{name}` | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()

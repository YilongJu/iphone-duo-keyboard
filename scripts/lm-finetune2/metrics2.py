"""The counts of round 2: right cases per category and group, and changed words of clean running text.

A stream case holds one whole sentence typed without a slip. Its count of changed words is the
edit distance between the words the field holds and the words typed (a changed, missing or extra
word counts 1).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "typing-evaluation"))
from score import GROUPS  # noqa: E402

STREAM_CATEGORIES = ("clean_stream_closed", "clean_stream_open")
CLEAN = ["clean_common", "clean_rare", "clean_names_and_terms", "clean_two_words"]
GENERATED_GROUPS = {"clean": CLEAN, **GROUPS["english"], "apostrophe_missing": ["apostrophe_missing"],
                    "real_word_slip": ["real_word_slip"]}
# The slip groups of the generated cases outside real_word_slip.
NON_WORD_SLIP_GROUPS = ("letter_slips", "space_slips", "symbol_slips", "apostrophe_missing")


def normal(text: str) -> str:
    return text.strip().replace("’", "'").lower()


def changed_words(output: str, intended: str) -> int:
    first, second = normal(output).split(), normal(intended).split()
    previous = list(range(len(second) + 1))
    for i, a in enumerate(first, 1):
        current = [i]
        for j, b in enumerate(second, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def summarize(cases: list[dict], predictions: dict[str, str]) -> dict:
    categories: dict[str, dict] = {}
    for case in cases:
        entry = categories.setdefault(case["category"], {"cases": 0, "right": 0})
        entry["cases"] += 1
        right = normal(predictions[case["id"]]) == normal(case["intended"])
        entry["right"] += int(right)
        if case["category"] in STREAM_CATEGORIES:
            entry["words"] = entry.get("words", 0) + len(case["intended"].split())
            entry["changed_words"] = entry.get("changed_words", 0) + changed_words(predictions[case["id"]], case["intended"])
    groups = {}
    for name, members in GENERATED_GROUPS.items():
        present = [categories[m] for m in members if m in categories]
        if present:
            groups[name] = {"cases": sum(e["cases"] for e in present), "right": sum(e["right"] for e in present)}
    summary = {"cases": len(cases), "right": sum(e["right"] for e in categories.values()), "categories": categories, "groups": groups}
    streams = [categories[name] for name in STREAM_CATEGORIES if name in categories]
    if streams:
        summary["stream"] = {"sentences": sum(e["cases"] for e in streams), "words": sum(e["words"] for e in streams),
                             "changed_words": sum(e["changed_words"] for e in streams),
                             "changed_sentences": sum(e["cases"] - e["right"] for e in streams)}
    if all(name in groups for name in NON_WORD_SLIP_GROUPS):
        summary["non_word_slips"] = {"cases": sum(groups[name]["cases"] for name in NON_WORD_SLIP_GROUPS),
                                     "right": sum(groups[name]["right"] for name in NON_WORD_SLIP_GROUPS)}
    return summary

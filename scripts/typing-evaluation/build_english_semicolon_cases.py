"""Builds the English cases for a semicolon key typed in place of the apostrophe key:
cases/english-semicolon.dev.jsonl and cases/english-semicolon.test.jsonl.

The wide layout has the semicolon key right beside the apostrophe key, and each key is 0.7 key
widths wide. A finger that aims at the apostrophe can land on the semicolon: "don;t" for
"don't". The semicolon key ends a word, so a keyboard that reads one word at a time never sees
"don;t" as one word.

The cases come from two case files of the same half, so the script needs no network:
- english-apostrophe-words.HALF.jsonl: each case whose intended word holds an apostrophe gives
  one case of the category `semicolon_for_apostrophe`. The person types the contraction with
  ";" for "'", one space, and the next word of the sentence: "it;s clear" for "it's clear".
- english.HALF.jsonl: a clean case of one typed word with a word before it gives two controls,
  with a semicolon that the person typed on purpose between the two words. In
  `clean_semicolon_then_space` a space follows the semicolon, as in "works; then". In
  `clean_semicolon_without_space` no space follows, as in "works;then". Both must stay as typed.
  The script takes the first CONTROLS such cases of the file.

Each case holds the fields of build_english_cases.py. The scorer reports the first category as
the group `semicolon_slips` and the two controls as the group `clean_semicolons`.

Usage, from the repository root:
    python scripts/typing-evaluation/build_english_semicolon_cases.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases"
CONTROLS = 400


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def is_plain_word(word: str) -> bool:
    return word.isascii() and word.isalpha() and word.islower() and len(word) >= 2


def build(half: str) -> list[dict]:
    cases = []

    def add(category: str, context: str, typed: str, intended: str, source: str) -> None:
        number = sum(1 for case in cases if case["category"] == category)
        cases.append({"id": f"ensemi-{half}-{category}-{number:04d}", "split": half, "category": category,
                      "context": context, "typed": typed, "intended": intended, "source": source})

    for case in load(CASES / f"english-apostrophe-words.{half}.jsonl"):
        word = case["intended"]
        if "'" not in word or " " in word:
            continue
        if not case["next_word"].replace("'", "").isalpha() or not case["next_word"].isascii():
            raise SystemExit(f"{case['id']}: the next word {case['next_word']!r} is not a plain word")
        add("semicolon_for_apostrophe", case["context"], f"{word.replace(chr(39), ';')} {case['next_word']}",
            f"{word} {case['next_word']}", case["source"])

    controls = 0
    for case in load(CASES / f"english.{half}.jsonl"):
        if not case["category"].startswith("clean") or case["typed"] != case["intended"]:
            continue
        before = case["context"].split(" ")
        if not case["context"] or not is_plain_word(case["typed"]) or not is_plain_word(before[-1]):
            continue
        if controls >= CONTROLS:
            continue
        controls += 1
        context = " ".join(before[:-1])
        for category, between in (("clean_semicolon_then_space", "; "), ("clean_semicolon_without_space", ";")):
            text = f"{before[-1]}{between}{case['typed']}"
            add(category, context, text, text, case["source"])
    if controls < CONTROLS:
        raise SystemExit(f"{half}: only {controls} clean cases give a control, and the file needs {CONTROLS}")
    return cases


def main():
    for half in ("dev", "test"):
        cases = build(half)
        path = CASES / f"english-semicolon.{half}.jsonl"
        path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")
        counts = {}
        for case in cases:
            counts[case["category"]] = counts.get(case["category"], 0) + 1
        print(f"wrote {path.name}: {counts}")


if __name__ == "__main__":
    main()

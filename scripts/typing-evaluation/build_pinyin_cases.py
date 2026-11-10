"""Builds the Pinyin typing test cases in cases/pinyin.dev.jsonl and cases/pinyin.test.jsonl.

One case holds the Pinyin letters a person typed, with or without a slip (`typed`), and the
Chinese text the person meant (`intended`). A keyboard gets `typed` and must produce `intended`
as its first candidate.

Sources:
- Sentences: Tatoeba Mandarin export, CC BY 2.0 FR, https://tatoeba.org. A sentence is cut at
  its punctuation, and each run of Chinese characters between two marks is one clause.
- Pinyin of each clause: the pypinyin package, which picks the reading of a character from the
  phrase around it.

A sentence with an even Tatoeba id goes to the dev half and one with an odd id to the test half.

Usage, from the repository root:
    uv run --with pypinyin python scripts/typing-evaluation/build_pinyin_cases.py
"""
import bz2
import json
import random
import re
import urllib.request
from pathlib import Path

from pypinyin import Style, lazy_pinyin

import keyboard_noise as noise

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = ROOT / "build" / "typing-evaluation" / "cmn_sentences.tsv.bz2"
SOURCE_URL = "https://downloads.tatoeba.org/exports/per_language/cmn/cmn_sentences.tsv.bz2"
DICTIONARY = ROOT / "Shared" / "pinyin-dictionary.txt"
OUTPUT_DIR = HERE / "cases"

CASES_PER_CATEGORY = 300
SEED = 20261110
CLAUSE = re.compile(r"[一-鿿]+")

# Sound pairs that speakers of some dialects do not tell apart. A keyboard's "fuzzy Pinyin"
# setting covers these. They are not finger slips, so they form their own category.
FUZZY_INITIALS = [("zh", "z"), ("ch", "c"), ("sh", "s"), ("n", "l"), ("h", "f"), ("r", "l")]
FUZZY_FINALS = [("ang", "an"), ("eng", "en"), ("ing", "in")]


def load_syllables() -> set[str]:
    syllables = set()
    for line in DICTIONARY.read_text(encoding="utf-8").splitlines():
        spelling = line.split("\t")[0]
        if " " not in spelling:
            syllables.add(spelling)
    return syllables


def to_syllables(clause: str, valid: set[str]) -> list[str] | None:
    """Toneless Pinyin of a clause, or None when a reading is not a standard syllable."""
    syllables = []
    for syllable in lazy_pinyin(clause, style=Style.NORMAL):
        # The dictionary writes "lue" and "nue" for the sounds pypinyin writes as "lve" and "nve".
        syllable = {"lve": "lue", "nve": "nue"}.get(syllable, syllable)
        if syllable not in valid or syllable in ("n", "ng", "m", "hm", "hng"):
            return None
        syllables.append(syllable)
    return syllables if len(syllables) == len(clause) else None


def is_simplified_common(clause: str) -> bool:
    """True when every character is in GB2312, the common Simplified Chinese set."""
    try:
        clause.encode("gb2312")
    except UnicodeEncodeError:
        return False
    return True


def load_clauses(valid: set[str]) -> dict[str, list[dict]]:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(SOURCE_URL, CACHE)
    halves = {"dev": [], "test": []}
    seen = set()
    with bz2.open(CACHE, "rt", encoding="utf-8") as lines:
        for line in lines:
            sentence_id, _, text = line.rstrip("\n").split("\t", 2)
            for clause in CLAUSE.findall(text):
                if not 2 <= len(clause) <= 20 or clause in seen or not is_simplified_common(clause):
                    continue
                seen.add(clause)
                syllables = to_syllables(clause, valid)
                if syllables is None:
                    continue
                half = "dev" if int(sentence_id) % 2 == 0 else "test"
                halves[half].append({"text": clause, "syllables": syllables, "source": f"tatoeba:{sentence_id}"})
    return halves


def parses_exactly(letters: str, valid: set[str]) -> bool:
    """True when the letters split into whole standard syllables with nothing left over."""
    reachable = [True] + [False] * len(letters)
    for end in range(1, len(letters) + 1):
        reachable[end] = any(reachable[start] and letters[start:end] in valid for start in range(max(0, end - 6), end))
    return reachable[-1]


def fuzzy_sound(syllables: list[str], rng: random.Random, valid: set[str]) -> str | None:
    """Swaps one sound of one syllable for the sound it is often confused with."""
    options = []
    for index, syllable in enumerate(syllables):
        for first, second in FUZZY_INITIALS:
            for old, new in ((first, second), (second, first)):
                # "z" must not match the start of "zh", and so on for the other pairs.
                if syllable.startswith(old) and not (len(old) == 1 and syllable[1:2] == "h"):
                    swapped = new + syllable[len(old):]
                    if swapped in valid and swapped != syllable:
                        options.append((index, swapped))
        for first, second in FUZZY_FINALS:
            for old, new in ((first, second), (second, first)):
                if syllable.endswith(old) and not (old.endswith("n") and syllable.endswith(old + "g")):
                    swapped = syllable[:len(syllable) - len(old)] + new
                    if swapped in valid and swapped != syllable:
                        options.append((index, swapped))
    if not options:
        return None
    index, swapped = rng.choice(options)
    return "".join(syllables[:index] + [swapped] + syllables[index + 1:])


def build_half(half: str, clauses: list[dict], valid: set[str]) -> list[dict]:
    cases = []

    def collect(category, minimum_length, maximum_length, make_typed):
        rng = random.Random(f"{SEED}-{half}-{category}")
        order = [clause for clause in clauses if minimum_length <= len(clause["text"]) <= maximum_length]
        rng.shuffle(order)
        number = 0
        for clause in order:
            letters = "".join(clause["syllables"])
            typed = make_typed(clause, letters, rng)
            if typed is None or (typed == letters) != category.startswith("clean"):
                continue
            cases.append({
                "id": f"zh-{half}-{category}-{number:04d}", "split": half, "category": category,
                "typed": typed, "intended": clause["text"], "intended_pinyin": " ".join(clause["syllables"]),
                "typed_parses_exactly": parses_exactly(typed, valid), "source": clause["source"],
            })
            number += 1
            if number == CASES_PER_CATEGORY:
                return
        raise SystemExit(f"{half}/{category}: only {number} cases, wanted {CASES_PER_CATEGORY}")

    collect("clean_short", 2, 3, lambda clause, letters, rng: letters)
    collect("clean_medium", 4, 7, lambda clause, letters, rng: letters)
    collect("clean_long", 8, 20, lambda clause, letters, rng: letters)
    for name, operator in noise.LETTER_OPERATORS.items():
        collect(name, 4, 20, lambda clause, letters, rng, operator=operator: operator(letters, rng))
    collect("two_errors", 6, 20, lambda clause, letters, rng: noise.two_errors(letters, rng, minimum_gap=5))
    collect("fuzzy_sound", 4, 20, lambda clause, letters, rng: fuzzy_sound(clause["syllables"], rng, valid))
    return cases


def main():
    valid = load_syllables()
    clauses = load_clauses(valid)
    OUTPUT_DIR.mkdir(exist_ok=True)
    for half in ("dev", "test"):
        cases = build_half(half, clauses[half], valid)
        path = OUTPUT_DIR / f"pinyin.{half}.jsonl"
        path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}: {len(cases)} cases from {len(clauses[half])} clauses")
        for category in dict.fromkeys(case["category"] for case in cases):
            group = [case for case in cases if case["category"] == category]
            exact = sum(case["typed_parses_exactly"] for case in group)
            print(f"  {category:24s} {len(group):4d}   typed is valid Pinyin in {exact:3d}   e.g. {group[0]['typed']} -> {group[0]['intended']}")


if __name__ == "__main__":
    main()

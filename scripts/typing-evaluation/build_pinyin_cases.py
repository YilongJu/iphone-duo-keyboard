"""Builds the Pinyin typing test cases in cases/pinyin.dev.jsonl and cases/pinyin.test.jsonl.

One case holds the Pinyin letters a person typed, with or without a slip (`typed`), and the
Chinese text the person meant (`intended`). A keyboard gets `typed` and must produce `intended`
as its first candidate.

The cases are paired. The script first picks base clauses, and each base clause gives one clean
case (its Pinyin typed right) and one case per slip type (the same Pinyin with that slip). A slip
case names its clean case in `twin`, so a score can tell "did not repair the slip" from "cannot
produce this clause at all".

Sources:
- Sentences: Tatoeba Mandarin export, CC BY 2.0 FR, https://tatoeba.org. A sentence is cut at
  its punctuation, and each run of Chinese characters between two marks is one clause.
- Simplified Chinese filter: a clause is kept when the OpenCC Traditional-to-Simplified
  conversion leaves it unchanged.
- Pinyin of each clause: the pypinyin package, which picks the reading of a character from the
  phrase around it. The set of standard syllables also comes from pypinyin: every toneless
  reading of a character in GB2312, the common character set.

A sentence with an even Tatoeba id goes to the dev half and one with an odd id to the test half.

Usage, from the repository root:
    uv run --with pypinyin --with opencc-python-reimplemented python scripts/typing-evaluation/build_pinyin_cases.py
"""
import bz2
import json
import random
import re
import urllib.request
from pathlib import Path

from opencc import OpenCC
from pypinyin import Style, lazy_pinyin, pinyin

import keyboard_noise as noise

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = ROOT / "build" / "typing-evaluation" / "cmn_sentences.tsv.bz2"
SOURCE_URL = "https://downloads.tatoeba.org/exports/per_language/cmn/cmn_sentences.tsv.bz2"
OUTPUT_DIR = HERE / "cases"

SEED = 20261110
CLAUSE = re.compile(r"[一-鿿]+")
# A slip in very short Pinyin leaves too little to read, so shorter Pinyin gets a clean case only.
SLIP_MINIMUM_LETTERS = 5
# Base clauses per half, by clause length in characters.
LENGTH_BINS = [("2-3", 2, 3, 150), ("4-7", 4, 7, 300), ("8-20", 8, 20, 300)]

# Sound pairs that speakers of some dialects do not tell apart. A keyboard's "fuzzy Pinyin"
# setting covers these. They are not finger slips, so they form their own category.
FUZZY_INITIALS = [("zh", "z"), ("ch", "c"), ("sh", "s"), ("n", "l"), ("h", "f"), ("r", "l")]
FUZZY_FINALS = [("ang", "an"), ("eng", "en"), ("ing", "in")]
# Interjection readings without a vowel, which people do not type as Pinyin.
NOT_TYPED = {"n", "ng", "m", "hm", "hng"}
# People type the sound "ü" after l and n in two ways ("lve" or "lue"), and engines differ in
# which one they accept, so clauses with these two syllables are left out.
TWO_SPELLINGS = {"lve", "nve"}


def standard_syllables() -> set[str]:
    """Every toneless reading that pypinyin lists for a character of GB2312."""
    syllables = set()
    for high in range(0xB0, 0xF8):
        for low in range(0xA1, 0xFF):
            try:
                character = bytes([high, low]).decode("gb2312")
            except UnicodeDecodeError:
                continue
            for reading in pinyin(character, style=Style.NORMAL, heteronym=True)[0]:
                if reading.isascii() and reading.isalpha():
                    syllables.add(reading)
    return syllables - NOT_TYPED


def to_syllables(clause: str, valid: set[str]) -> list[str] | None:
    """Toneless Pinyin of a clause, or None when a reading is not a standard syllable."""
    syllables = lazy_pinyin(clause, style=Style.NORMAL)
    if len(syllables) != len(clause):
        return None
    if any(syllable not in valid or syllable in TWO_SPELLINGS for syllable in syllables):
        return None
    return syllables


def load_clauses(valid: set[str]) -> dict[str, list[dict]]:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(SOURCE_URL, CACHE)
    to_simplified = OpenCC("t2s")
    halves = {"dev": [], "test": []}
    seen = set()
    with bz2.open(CACHE, "rt", encoding="utf-8") as lines:
        for line in lines:
            sentence_id, _, text = line.rstrip("\n").split("\t", 2)
            for clause in CLAUSE.findall(text):
                if not 2 <= len(clause) <= 20 or clause in seen:
                    continue
                seen.add(clause)
                if to_simplified.convert(clause) != clause:
                    continue
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
    slip_makers = dict(noise.LETTER_OPERATORS)
    slip_makers["two_errors"] = lambda letters, rng: noise.two_errors(letters, rng, minimum_gap=5)

    for bin_name, shortest, longest, wanted in LENGTH_BINS:
        rng = random.Random(f"{SEED}-{half}-{bin_name}")
        pool = [clause for clause in clauses if shortest <= len(clause["text"]) <= longest]
        if len(pool) < wanted:
            raise SystemExit(f"{half}/{bin_name}: only {len(pool)} clauses, wanted {wanted}")
        for number, clause in enumerate(rng.sample(pool, wanted)):
            letters = "".join(clause["syllables"])
            base_id = f"zh-{half}-{bin_name}-{number:04d}"

            def add(category, typed, twin):
                case = {
                    "id": f"{base_id}-{category}", "split": half, "category": category, "length_bin": bin_name,
                    "typed": typed, "intended": clause["text"], "intended_pinyin": " ".join(clause["syllables"]),
                    "typed_parses_exactly": parses_exactly(typed, valid), "source": clause["source"],
                }
                if twin is not None:
                    case["twin"] = twin
                cases.append(case)

            add("clean", letters, None)
            clean_id = cases[-1]["id"]
            if len(letters) < SLIP_MINIMUM_LETTERS:
                continue
            for category, maker in slip_makers.items():
                typed = maker(letters, rng)
                if typed is not None and typed != letters:
                    add(category, typed, clean_id)
            typed = fuzzy_sound(clause["syllables"], rng, valid)
            if typed is not None:
                add("fuzzy_sound", typed, clean_id)
    return cases


def main():
    valid = standard_syllables()
    clauses = load_clauses(valid)
    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"{len(valid)} standard syllables")
    for half in ("dev", "test"):
        cases = build_half(half, clauses[half], valid)
        path = OUTPUT_DIR / f"pinyin.{half}.jsonl"
        path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")
        lengths = [len(case["typed"]) for case in cases]
        print(f"wrote {path.relative_to(ROOT)}: {len(cases)} cases from {len(clauses[half])} clauses, typed length {min(lengths)} to {max(lengths)} letters")
        for category in dict.fromkeys(case["category"] for case in cases):
            group = [case for case in cases if case["category"] == category]
            exact = sum(case["typed_parses_exactly"] for case in group)
            print(f"  {category:24s} {len(group):4d}   typed is valid Pinyin in {exact:3d}   e.g. {group[-1]['typed']} -> {group[-1]['intended']}")


if __name__ == "__main__":
    main()

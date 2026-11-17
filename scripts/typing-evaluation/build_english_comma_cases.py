"""Builds the English cases with a letter key typed in place of the comma key or the period key
right after a word: cases/english-comma-slip.dev.jsonl and cases/english-comma-slip.test.jsonl.

A finger that aims at the comma key right after a word can land on a letter key beside it:
"hellom" for "hello,". The keyboard reads the word when the person types the space after it. A
keyboard gets `context` and `typed` and must produce `intended`, the word and its comma, as in
the cases of build_english_cases.py. The same slip can hit the period key at the end of a
sentence: "hellol" for "hello.". These files stand apart from the other case files, so the
scores on those files do not change.

The letters beside the two keys come from Shared/keyboard-layout.json (symbol_keys.py):
- Wide layout: the comma key sits right of "m" in the bottom row, and "k" and "l" sit above it.
  "m" shares the whole side edge of the comma key, 0.9 key widths from its center. "k" and "l"
  each touch a part of its top edge, 1.10 and 1.14 key widths away. So "m" gets weight 2, and
  "k" and "l" get weight 1 each. The period key has one letter beside it, "l".
- Compact layout: the comma key sits in the row of the space bar, right under "n", and the
  period key right under "m".

Slip categories. Each case is a word that a Tatoeba sentence writes with the mark right after it:
- comma_slip_wide: a comma inside the sentence, typed as k, l or m by the weights above.
- comma_slip_compact: the same comma, typed as n.
- period_slip_wide: the period that ends the sentence, typed as l.
- period_slip_compact: the same period, typed as m.
- comma_slip_real_word: a comma inside the sentence, typed as a letter beside the comma key that
  turns the word into another common word, as "tool" for "too,". Reported alone.

Clean category, where any change is an error:
- clean_comma_neighbor_word: a word of three or more letters that ends in k, l, m or n, with a
  space right after it in the sentence. Half of these words hold a common word without their
  last letter, as "them" holds "the" and "form" holds "for". The other half do not, as "call".

Which text counts as a slip. A slip case needs a typed text under TYPED_MAXIMUM_ZIPF (3.0), the
limit of the letter slips of build_english_cases.py. A typed text at that limit or over it is a
common word, and its case goes to comma_slip_real_word. The word before the mark has two letters
or more, because a one-letter word right before a comma is rare and the engine reads a one-letter
word only exactly. One typed text appears at most REPEATS_PER_TYPED_TEXT times in a category.

The sentences come from the Tatoeba export of build_english_cases.py, with the same limits: 4 to
12 plain words, every word among the 60,000 most frequent wordfreq tokens. A sentence with an even
id feeds the dev half and one with an odd id the test half. Tatoeba holds many sentences under two
ids, so a test sentence with the words of a dev sentence stays out.

Usage, from the repository root:
    uv run --with wordfreq python scripts/typing-evaluation/build_english_comma_cases.py
"""
import bz2
import json
import random
from pathlib import Path

from wordfreq import top_n_list

import build_english_cases as base
import symbol_keys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT_DIR = HERE / "cases"

CASES_PER_CATEGORY = 300
REPEATS_PER_TYPED_TEXT = 3
# A word without its last letter counts as a common word from this frequency on, as in
# build_english_symbol_cases.py.
REAL_WORD_ZIPF = 3.0

# The letter weights of the comma key in the wide layout, from the key geometry above.
COMMA_WEIGHTS_WIDE = {"m": 2.0, "k": 1.0, "l": 1.0}
# The letter beside the comma key in the compact layout, and beside the period key in each layout.
COMMA_LETTER_COMPACT = "n"
PERIOD_LETTER_WIDE = "l"
PERIOD_LETTER_COMPACT = "m"


def check_layout() -> None:
    """Stops when the layout file no longer puts these letters beside the two keys."""
    layout = json.loads(symbol_keys.LAYOUT.read_text(encoding="utf-8"))
    wide = symbol_keys.neighbors_in_style(layout["wide"])
    compact = symbol_keys.neighbors_in_style(layout["compact"])
    expected = {
        ("wide", ","): sorted(COMMA_WEIGHTS_WIDE), ("wide", "."): [PERIOD_LETTER_WIDE],
        ("compact", ","): [COMMA_LETTER_COMPACT], ("compact", "."): [PERIOD_LETTER_COMPACT],
    }
    for (style, key), letters in expected.items():
        found = (wide if style == "wide" else compact).get(key)
        if found != letters:
            raise SystemExit(f"{symbol_keys.LAYOUT.name}: the {style} layout puts {found} beside {key!r}, this script expects {letters}")


def load_sentences(vocabulary: set[str]) -> dict[str, list[tuple[int, list[str], list[str]]]]:
    """The sentences of build_english_cases.load_sentences, each with its raw tokens in lower
    case, so a word shows the punctuation that the sentence writes after it."""
    if not base.CACHE.exists():
        raise SystemExit(f"{base.CACHE} is missing: run build_english_cases.py first, which downloads it")
    halves = {"dev": [], "test": []}
    with bz2.open(base.CACHE, "rt", encoding="utf-8") as lines:
        for line in lines:
            sentence_id, _, text = line.rstrip("\n").split("\t", 2)
            if not text.isascii():
                continue
            words = base.tokenize(text)
            if words is None or not 4 <= len(words) <= 12 or any(word not in vocabulary for word in words):
                continue
            raw = text.lower().replace("’", "'").split()
            halves["dev" if int(sentence_id) % 2 == 0 else "test"].append((int(sentence_id), words, raw))
    return halves


def common(word: str) -> bool:
    return base.plain(word) and base.zipf(word) >= base.TARGET_MINIMUM_ZIPF


def comma_places(words: list[str], raw: list[str]) -> list[int]:
    """The places of the words that the sentence writes with a comma right after them, and
    another word after the comma."""
    return [index for index in range(len(words) - 1)
            if raw[index] == words[index] + "," and common(words[index]) and len(words[index]) >= 2]


def period_places(words: list[str], raw: list[str]) -> list[int]:
    """The place of the last word when the sentence ends with a period right after it."""
    index = len(words) - 1
    if raw[index] == words[index] + "." and common(words[index]) and len(words[index]) >= 2:
        return [index]
    return []


def clean_places(words: list[str], raw: list[str]) -> list[int]:
    """The places of the words of three letters or more that end in a letter beside the comma
    key, with a space and another word right after them."""
    letters = set(COMMA_WEIGHTS_WIDE) | {COMMA_LETTER_COMPACT}
    return [index for index in range(len(words) - 1)
            if raw[index] == words[index] and len(words[index]) >= 3 and words[index][-1] in letters
            and common(words[index])]


def is_slip(typed: str) -> bool:
    return base.zipf(typed) < base.TYPED_MAXIMUM_ZIPF


def build_half(half: str, sentences) -> list[dict]:
    cases = []

    def add(category, words, index, typed, intended, sentence_id, **extra):
        number = sum(1 for case in cases if case["category"] == category)
        cases.append({
            "id": f"encomma-{half}-{category}-{number:04d}", "split": half, "category": category,
            "context": " ".join(words[:index]), "typed": typed, "intended": intended,
            "source": f"tatoeba:{sentence_id}", **extra,
        })

    def from_sentences(category, places, maker, count, seed_name=None):
        """Takes one place per sentence, in a seeded random order, until `count` cases."""
        rng = random.Random(f"{base.SEED}-{half}-{seed_name or category}")
        order = sentences[:]
        rng.shuffle(order)
        made = 0
        for sentence_id, words, raw in order:
            found = places(words, raw)
            if not found:
                continue
            index = rng.choice(found)
            result = maker(words[index], rng)
            if result is None:
                continue
            typed, intended, extra = result
            repeats = sum(1 for case in cases if case["category"] == category and case["typed"] == typed)
            if repeats >= REPEATS_PER_TYPED_TEXT:
                continue
            add(category, words, index, typed, intended, sentence_id, **extra)
            made += 1
            if made == count:
                return
        raise SystemExit(f"{half}/{seed_name or category}: only {made} cases, wanted {count}")

    def slip(mark, letter_of):
        def maker(word, rng):
            letter = letter_of(rng)
            typed = word + letter
            return (typed, word + mark, {"letter": letter}) if is_slip(typed) else None
        return maker

    def wide_comma_letter(rng):
        letters = sorted(COMMA_WEIGHTS_WIDE)
        return rng.choices(letters, weights=[COMMA_WEIGHTS_WIDE[letter] for letter in letters])[0]

    from_sentences("comma_slip_wide", comma_places, slip(",", wide_comma_letter), CASES_PER_CATEGORY)
    from_sentences("comma_slip_compact", comma_places, slip(",", lambda rng: COMMA_LETTER_COMPACT), CASES_PER_CATEGORY)
    from_sentences("period_slip_wide", period_places, slip(".", lambda rng: PERIOD_LETTER_WIDE), CASES_PER_CATEGORY)
    from_sentences("period_slip_compact", period_places, slip(".", lambda rng: PERIOD_LETTER_COMPACT), CASES_PER_CATEGORY)

    def real_word(word, rng):
        letters = [letter for letter in sorted(set(COMMA_WEIGHTS_WIDE) | {COMMA_LETTER_COMPACT})
                   if not is_slip(word + letter)]
        if not letters:
            return None
        letter = rng.choice(letters)
        return word + letter, word + ",", {"letter": letter}

    from_sentences("comma_slip_real_word", comma_places, real_word, CASES_PER_CATEGORY)

    # Half of the clean words hold a common word without their last letter.
    for with_real_prefix in (True, False):
        def clean(word, rng, flag=with_real_prefix):
            if (base.zipf(word[:-1]) >= REAL_WORD_ZIPF) != flag:
                return None
            return word, word, {"letter": word[-1], "real_prefix": flag}
        from_sentences("clean_comma_neighbor_word", clean_places, clean, CASES_PER_CATEGORY // 2,
                       seed_name=f"clean_comma_neighbor_word-{with_real_prefix}")
    return cases


def main():
    check_layout()
    vocabulary = set(top_n_list("en", 60000))
    sentences = load_sentences(vocabulary)
    dev_texts = {tuple(words) for _, words, _ in sentences["dev"]}
    kept = [sentence for sentence in sentences["test"] if tuple(sentence[1]) not in dev_texts]
    print(f"left out {len(sentences['test']) - len(kept)} test sentences with the words of a dev sentence")
    sentences["test"] = kept
    OUTPUT_DIR.mkdir(exist_ok=True)
    for half in ("dev", "test"):
        cases = build_half(half, sentences[half])
        path = OUTPUT_DIR / f"english-comma-slip.{half}.jsonl"
        path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}: {len(cases)} cases from {len(sentences[half])} sentences")
        counts: dict[str, dict[str, int]] = {}
        for case in cases:
            row = counts.setdefault(case["category"], {})
            row[case["letter"]] = row.get(case["letter"], 0) + 1
        for category, row in counts.items():
            sample = next(case for case in cases if case["category"] == category)
            letters = " ".join(f"{letter} {count}" for letter, count in sorted(row.items()))
            print(f"  {category:28s} {sum(row.values()):4d}   letters: {letters:24s} e.g. {sample['typed']!r} -> {sample['intended']!r}")


if __name__ == "__main__":
    main()

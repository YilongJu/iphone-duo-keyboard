"""Builds the English typing test cases in cases/english.dev.jsonl and cases/english.test.jsonl.

One case holds the words before the typed span (`context`), the characters a person typed with a
slip (`typed`), and the text the person meant (`intended`). A keyboard gets `context` and `typed`
and must produce `intended`.

Sources:
- Sentences: Tatoeba English export, CC BY 2.0 FR, https://tatoeba.org.
- Word frequencies: the wordfreq package (Zipf scale: 3 means once per million words, 6 means
  once per thousand).

A sentence with an even Tatoeba id goes to the dev half and one with an odd id to the test half,
so the two halves do not share a sentence.

Usage, from the repository root:
    uv run --with wordfreq python scripts/typing-evaluation/build_english_cases.py
"""
import bz2
import json
import random
import re
import urllib.request
from pathlib import Path

from wordfreq import top_n_list, zipf_frequency

import keyboard_noise as noise

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = ROOT / "build" / "typing-evaluation" / "eng_sentences.tsv.bz2"
SOURCE_URL = "https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences.tsv.bz2"
UNKNOWN_TOKENS = HERE / "inputs" / "names_and_terms.txt"
OUTPUT_DIR = HERE / "cases"

CASES_PER_CATEGORY = 300
SEED = 20261110
WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
EDGE_PUNCTUATION = ".,!?;:\"()[]"

# A target word is common enough that any keyboard's word list holds it.
TARGET_MINIMUM_ZIPF = 3.5
# A slip that produces a real, reasonably common word is a different problem (the keyboard needs
# the sentence to see it). The letter categories leave those slips out, and the category
# `real_word_slip` holds them.
TYPED_MAXIMUM_ZIPF = 3.0
INTENDED_OVER_TYPED_ZIPF = 2.0
# Two parts that are both common words, such as "to day", read as two intended words.
COMMON_WORD_ZIPF = 4.0
# Words of 2 and 3 letters are the most frequent words of all. Their slips get their own category.
SHORT_WORD_MINIMUM_ZIPF = 5.0


def zipf(word: str) -> float:
    return zipf_frequency(word, "en")


def tokenize(text: str) -> list[str] | None:
    """Lower-case words of a sentence, or None when the sentence holds anything but plain words."""
    words = []
    for raw in text.lower().replace("’", "'").split():
        word = raw.strip(EDGE_PUNCTUATION)
        if not WORD.fullmatch(word):
            return None
        words.append(word)
    return words


def load_sentences(vocabulary: set[str]) -> dict[str, list[tuple[int, list[str]]]]:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(SOURCE_URL, CACHE)
    halves = {"dev": [], "test": []}
    with bz2.open(CACHE, "rt", encoding="utf-8") as lines:
        for line in lines:
            sentence_id, _, text = line.rstrip("\n").split("\t", 2)
            if not text.isascii():
                continue
            words = tokenize(text)
            if words is None or not 4 <= len(words) <= 12 or any(word not in vocabulary for word in words):
                continue
            halves["dev" if int(sentence_id) % 2 == 0 else "test"].append((int(sentence_id), words))
    return halves


def plain(word: str) -> bool:
    return word.isalpha()


def letter_slip_is_fair(intended: str, typed: str) -> bool:
    return typed != intended and zipf(typed) < TYPED_MAXIMUM_ZIPF and zipf(intended) - zipf(typed) >= INTENDED_OVER_TYPED_ZIPF


def make_letter_case(words, index, operator, rng, minimum_length):
    word = words[index]
    if not plain(word) or len(word) < minimum_length or zipf(word) < TARGET_MINIMUM_ZIPF:
        return None
    typed = operator(word, rng)
    if typed is None or not letter_slip_is_fair(word, typed):
        return None
    return typed, word


def make_short_word_case(words, index, rng):
    word = words[index]
    if not plain(word) or not 2 <= len(word) <= 3 or zipf(word) < SHORT_WORD_MINIMUM_ZIPF:
        return None
    # A dropped letter leaves one letter of a two-letter word, which nobody could read back.
    names = [name for name in sorted(noise.LETTER_OPERATORS) if name != "deletion" or len(word) == 3]
    typed = noise.LETTER_OPERATORS[rng.choice(names)](word, rng)
    if typed is None or not letter_slip_is_fair(word, typed):
        return None
    return typed, word


def make_real_word_case(words, index, rng):
    word = words[index]
    if not plain(word) or len(word) < 3 or zipf(word) < TARGET_MINIMUM_ZIPF:
        return None
    typed = noise.LETTER_OPERATORS[rng.choice(sorted(noise.LETTER_OPERATORS))](word, rng)
    if typed is None or typed == word or zipf(typed) < COMMON_WORD_ZIPF:
        return None
    return typed, word


def make_two_word_case(words, index, operator, rng):
    if index + 1 >= len(words):
        return None
    left, right = words[index], words[index + 1]
    if not (plain(left) and plain(right)) or min(zipf(left), zipf(right)) < TARGET_MINIMUM_ZIPF:
        return None
    intended = f"{left} {right}"
    typed = operator(intended, rng)
    if typed is None or typed == intended:
        return None
    parts = typed.split(" ")
    if all(zipf(part) >= COMMON_WORD_ZIPF for part in parts):
        return None
    return typed, intended


def make_clean_two_word_case(words, index):
    if index + 1 >= len(words):
        return None
    left, right = words[index], words[index + 1]
    if not (plain(left) and plain(right)) or min(zipf(left), zipf(right)) < TARGET_MINIMUM_ZIPF:
        return None
    return f"{left} {right}", f"{left} {right}"


def make_split_word_case(words, index, operator, rng):
    word = words[index]
    if not plain(word) or len(word) < 5 or zipf(word) < TARGET_MINIMUM_ZIPF:
        return None
    typed = operator(word, rng)
    if typed is None:
        return None
    if all(zipf(part) >= COMMON_WORD_ZIPF for part in typed.split(" ")):
        return None
    return typed, word


def make_apostrophe_case(words, index):
    word = words[index]
    if "'" not in word:
        return None
    typed = word.replace("'", "")
    if zipf(word) - zipf(typed) < 1.0:
        return None
    return typed, word


def make_clean_common_case(words, index):
    word = words[index]
    return (word, word) if plain(word) and len(word) >= 3 and zipf(word) >= 4.5 else None


def build_half(half: str, sentences, rare_words, unknown_tokens) -> list[dict]:
    cases = []

    def add(category, number, context, typed, intended, source):
        cases.append({
            "id": f"en-{half}-{category}-{number:04d}", "split": half, "category": category,
            "context": context, "typed": typed, "intended": intended, "source": source,
        })

    def from_sentences(category, maker):
        rng = random.Random(f"{SEED}-{half}-{category}")
        order = sentences[:]
        rng.shuffle(order)
        number = 0
        for sentence_id, words in order:
            index = rng.randrange(len(words))
            made = maker(words, index, rng)
            if made is None:
                continue
            typed, intended = made
            add(category, number, " ".join(words[:index]), typed, intended, f"tatoeba:{sentence_id}")
            number += 1
            if number == CASES_PER_CATEGORY:
                return
        raise SystemExit(f"{half}/{category}: only {number} cases, wanted {CASES_PER_CATEGORY}")

    def from_word_list(category, words):
        rng = random.Random(f"{SEED}-{half}-{category}")
        picks = rng.sample(words, min(CASES_PER_CATEGORY, len(words)))
        for number, word in enumerate(picks):
            sentence_id, sentence = rng.choice(sentences)
            cut = rng.randint(0, min(4, len(sentence)))
            add(category, number, " ".join(sentence[:cut]), word, word, f"tatoeba:{sentence_id}")

    from_sentences("clean_common", lambda words, index, rng: make_clean_common_case(words, index))
    from_word_list("clean_rare", rare_words[half])
    from_word_list("clean_names_and_terms", unknown_tokens[half])
    from_sentences("clean_two_words", lambda words, index, rng: make_clean_two_word_case(words, index))
    for name, operator in noise.LETTER_OPERATORS.items():
        from_sentences(name, lambda words, index, rng, operator=operator: make_letter_case(words, index, operator, rng, 4))
    from_sentences("two_errors", lambda words, index, rng: make_letter_case(words, index, noise.two_errors, rng, 7))
    from_sentences("short_word_slip", make_short_word_case)
    for name, operator in noise.SPACE_OPERATORS_TWO_WORDS.items():
        from_sentences(name, lambda words, index, rng, operator=operator: make_two_word_case(words, index, operator, rng))
    for name, operator in noise.SPACE_OPERATORS_ONE_WORD.items():
        from_sentences(name, lambda words, index, rng, operator=operator: make_split_word_case(words, index, operator, rng))
    from_sentences("apostrophe_missing", lambda words, index, rng: make_apostrophe_case(words, index))
    from_sentences("real_word_slip", make_real_word_case)
    return cases


def main():
    vocabulary = set(top_n_list("en", 60000))
    sentences = load_sentences(vocabulary)
    # Rare real words, which a keyboard must leave as typed. Even ranks go to dev, odd ranks to test.
    ranked = [word for word in top_n_list("en", 60000)[20000:] if word.isalpha() and word.isascii() and len(word) >= 4]
    rare_words = {"dev": ranked[0::2], "test": ranked[1::2]}
    tokens = [line.strip() for line in UNKNOWN_TOKENS.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    unknown_tokens = {"dev": tokens[0::2], "test": tokens[1::2]}

    OUTPUT_DIR.mkdir(exist_ok=True)
    for half in ("dev", "test"):
        cases = build_half(half, sentences[half], rare_words, unknown_tokens)
        path = OUTPUT_DIR / f"english.{half}.jsonl"
        path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")
        counts = {}
        for case in cases:
            counts[case["category"]] = counts.get(case["category"], 0) + 1
        lengths = [len(case["typed"]) for case in cases]
        contexts = [len(case["context"].split()) for case in cases]
        print(f"wrote {path.relative_to(ROOT)}: {len(cases)} cases from {len(sentences[half])} sentences, "
              f"typed length {min(lengths)} to {max(lengths)}, context {min(contexts)} to {max(contexts)} words")
        for category, count in counts.items():
            sample = next(case for case in cases if case["category"] == category)
            print(f"  {category:24s} {count:4d}   e.g. {sample['typed']!r} -> {sample['intended']!r}")


if __name__ == "__main__":
    main()

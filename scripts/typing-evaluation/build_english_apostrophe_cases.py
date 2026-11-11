"""Builds the English cases for words with and without an apostrophe:
cases/english-apostrophe-words.dev.jsonl and cases/english-apostrophe-words.test.jsonl.

A person often types a contraction without its apostrophe: "its" for "it's", "whats" for
"what's". For some contractions the form without the apostrophe is itself a common word ("its",
"were", "well", "ill"), so the keyboard must read the sentence to choose. These files stand apart
from english.dev.jsonl and english.test.jsonl, so the scores on those files do not change.

Each case holds the fields of build_english_cases.py and three more:
- `pair`: the form without the apostrophe and the contraction, as "its/it's".
- `next_word`: the word right after the target word in the sentence. The target word is never
  the last word, and no punctuation stands between the target word and the next word. A
  keyboard that corrects a word when the next word is typed needs this word.
- `kind`: the same value as `category`.

Categories:
- apostrophe_dropped_ambiguous: the contraction typed without its apostrophe, where that form
  is a common word ("its" for "it's").
- clean_ambiguous_word: the common word typed right ("its" for "its"). This is the control of
  the category above. Each pair has the same count in both, so a keyboard that always adds the
  apostrophe, or never adds it, gets half of the two categories right.
- apostrophe_dropped: the contraction typed without its apostrophe, where that form is not a
  common word ("whats" for "what's").
- apostrophe_added: the contraction typed where the person meant the common word ("it's" for
  "its"), for the two pairs where people make this slip often: its/it's and lets/let's.
- clean_ambiguous_contraction: the contraction typed right ("it's" for "it's"). This is the
  control of apostrophe_added, with the same count per pair.

The sentences and the split are those of build_english_cases.py: Tatoeba English, a sentence
with an even id feeds the dev half and one with an odd id the test half, 4 to 12 plain words,
every word among the 60,000 most frequent wordfreq tokens. The one change: the contractions of
this file also count as known words, because wordfreq splits "y'all" and "ma'am" into two tokens
and ranks "where're" below place 60,000.

Usage, from the repository root:
    uv run --with wordfreq python scripts/typing-evaluation/build_english_apostrophe_cases.py
"""
import bz2
import json
import random
from pathlib import Path

from wordfreq import top_n_list

import build_english_cases as base

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT_DIR = HERE / "cases"

# Cases per pair and category in each half, at most. A pair with fewer sentences gets fewer.
CASES_PER_AMBIGUOUS_PAIR = 40
CASES_PER_OTHER_PAIR = 20

# Contractions whose form without the apostrophe is a common English word. The list is written
# by hand, because the lexicon also holds forms that are not words, such as "youre".
AMBIGUOUS = ["it's", "we're", "we'll", "i'll", "he'll", "she'll", "we'd", "i'd", "let's", "she'd", "who're", "why's"]
# The two pairs that also get apostrophe_added and clean_ambiguous_contraction.
SLIP_BOTH_WAYS = ["it's", "let's"]
# Contractions whose form without the apostrophe is not a common word. "cant" and "wont" are
# English words, but rare ones, and the lexicon does not hold them.
OTHER = [
    "what's", "what're", "what'll", "what'd", "how's", "how'd", "how're", "where's", "where'd", "where're",
    "who's", "who'll", "who'd", "when's", "why'd", "there's", "there're", "there'll", "there'd", "here's",
    "that's", "that'll", "that'd", "it'll", "it'd", "would've", "could've", "should've", "might've",
    "must've", "y'all", "o'clock", "ma'am", "i'm", "i've", "you've", "they've", "we've", "they'd", "you'd",
    "you'll", "they'll", "he's", "she's", "you're", "they're", "he'd", "won't", "can't",
]


def bare(contraction: str) -> str:
    return contraction.replace("'", "")


def load_sentences(vocabulary: set[str]) -> dict[str, list[tuple[int, list[str], list[bool]]]]:
    """The sentences of build_english_cases.load_sentences, each with a flag per word that says
    whether the word stood alone in the text, without punctuation or quote marks on it."""
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
            bare_flags = [raw == word for raw, word in zip(text.lower().replace("’", "'").split(), words)]
            halves["dev" if int(sentence_id) % 2 == 0 else "test"].append((int(sentence_id), words, bare_flags))
    return halves


def places(sentences, form: str, rng: random.Random) -> list[tuple[int, list[str], int]]:
    """One place per sentence where `form` stands alone and another word follows it right after
    a space, in a seeded random order."""
    found = []
    for sentence_id, words, alone in sentences:
        spots = [index for index, word in enumerate(words[:-1]) if word == form and alone[index]]
        if spots:
            found.append((sentence_id, words, rng.choice(spots)))
    rng.shuffle(found)
    return found


def build_half(half: str, sentences) -> tuple[list[dict], dict[str, dict[str, int]]]:
    cases = []
    counts: dict[str, dict[str, int]] = {}

    def add(category, contraction, typed, intended, sentence_id, words, index):
        number = sum(1 for case in cases if case["category"] == category)
        cases.append({
            "id": f"enapo-{half}-{category}-{number:04d}", "split": half, "category": category, "kind": category,
            "pair": f"{bare(contraction)}/{contraction}", "context": " ".join(words[:index]),
            "typed": typed, "intended": intended, "next_word": words[index + 1], "source": f"tatoeba:{sentence_id}",
        })
        counts.setdefault(f"{bare(contraction)}/{contraction}", {})
        counts[f"{bare(contraction)}/{contraction}"][category] = counts[f"{bare(contraction)}/{contraction}"].get(category, 0) + 1

    def seeded(contraction, role):
        return random.Random(f"{base.SEED}-{half}-apostrophe-{contraction}-{role}")

    for contraction in AMBIGUOUS:
        word = bare(contraction)
        with_apostrophe = places(sentences, contraction, seeded(contraction, "contraction"))
        without = places(sentences, word, seeded(contraction, "word"))
        # The two categories of a pair share one count, so they balance. A pair that also gets
        # apostrophe_added splits the sentences of the contraction between its two categories.
        if contraction in SLIP_BOTH_WAYS:
            count = min(CASES_PER_AMBIGUOUS_PAIR, len(with_apostrophe) // 2, len(without) // 2)
        else:
            count = min(CASES_PER_AMBIGUOUS_PAIR, len(with_apostrophe), len(without))
        for sentence_id, words, index in with_apostrophe[:count]:
            add("apostrophe_dropped_ambiguous", contraction, word, contraction, sentence_id, words, index)
        for sentence_id, words, index in without[:count]:
            add("clean_ambiguous_word", contraction, word, word, sentence_id, words, index)
        if contraction in SLIP_BOTH_WAYS:
            for sentence_id, words, index in without[count:2 * count]:
                add("apostrophe_added", contraction, contraction, word, sentence_id, words, index)
            for sentence_id, words, index in with_apostrophe[count:2 * count]:
                add("clean_ambiguous_contraction", contraction, contraction, contraction, sentence_id, words, index)

    for contraction in OTHER:
        found = places(sentences, contraction, seeded(contraction, "contraction"))
        for sentence_id, words, index in found[:CASES_PER_OTHER_PAIR]:
            add("apostrophe_dropped", contraction, bare(contraction), contraction, sentence_id, words, index)
    return cases, counts


def main():
    overlap = set(AMBIGUOUS) & set(OTHER)
    if overlap or len(set(AMBIGUOUS + OTHER)) != len(AMBIGUOUS + OTHER):
        raise SystemExit(f"a contraction is listed twice: {sorted(overlap)}")
    vocabulary = set(top_n_list("en", 60000)) | set(AMBIGUOUS) | set(OTHER)
    sentences = load_sentences(vocabulary)
    OUTPUT_DIR.mkdir(exist_ok=True)
    for half in ("dev", "test"):
        cases, counts = build_half(half, sentences[half])
        path = OUTPUT_DIR / f"english-apostrophe-words.{half}.jsonl"
        path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")
        by_category = {}
        for case in cases:
            by_category[case["category"]] = by_category.get(case["category"], 0) + 1
        print(f"wrote {path.relative_to(ROOT)}: {len(cases)} cases from {len(sentences[half])} sentences")
        for category, count in by_category.items():
            print(f"  {category:32s} {count:4d}")
        for pair, row in counts.items():
            print(f"    {pair:18s} " + "  ".join(f"{name} {value}" for name, value in row.items()))
        missing = [c for c in AMBIGUOUS + OTHER if f"{bare(c)}/{c}" not in counts]
        if missing:
            print(f"  pairs without a case: {', '.join(missing)}")


if __name__ == "__main__":
    main()

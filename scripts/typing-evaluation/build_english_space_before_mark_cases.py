"""Builds the English cases with a space typed between a word and the closing mark after it:
cases/english-space-before-mark.dev.jsonl and cases/english-space-before-mark.test.jsonl.

A person often types "hello ," for "hello,". The keyboard takes such a space away when the
person types the mark right after it. A case starts with an empty field. The keyboard gets each
key of `typed`, with no space after the last one, and the whole field must then equal `intended`.
The files stand apart from the other English files, so the scores on those files do not change.

The sentences come from the Tatoeba English export (CC BY 2.0 FR, https://tatoeba.org), as in
build_english_cases.py. A sentence with an even id feeds the dev half and one with an odd id
the test half. Every word of a sentence is a run of letters and apostrophes with a word
frequency of at least TARGET_MINIMUM_ZIPF, so the keyboard has no reason to correct a word.

Categories with a space to take away, where `intended` is the sentence:
- space_before_comma: one space before one comma of the sentence.
- space_before_end_mark: one space before the ".", "?" or "!" that ends the sentence.
- space_before_closing_bracket: one space before a ")".

The cases type every key at once, so two spaces in a row give the double-space period, as
they do on iOS. Two spaces typed slowly before a mark are left to the unit tests in
Tests/KeyboardTextControllerTests.swift.

Clean categories, where `typed` equals `intended` and any change is an error:
- clean_marks_against_word: the sentence as written, the same sentences as the categories above.
  The score of this category is the score the categories above reach when every space goes.
- clean_spaced_dash: a sentence with " - " or " -- " between two words.
- clean_spaced_ellipsis: a sentence with " ..." after a word.
- clean_emoticon: a sentence without its end mark, then a space and ":)", ";)", ":(" or ":D".
  Tatoeba holds three sentences with an emoticon, so the emoticon is added to the sentence.

Usage, from the repository root:
    uv run --with wordfreq python scripts/typing-evaluation/build_english_space_before_mark_cases.py
"""
import bz2
import json
import random
import re
from pathlib import Path

from wordfreq import zipf_frequency

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = ROOT / "build" / "typing-evaluation" / "eng_sentences.tsv.bz2"
OUTPUT_DIR = HERE / "cases"

CASES_PER_CATEGORY = 40
TARGET_MINIMUM_ZIPF = 3.5
WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
# A token of a sentence: an optional "(", a word, then the marks after it.
TOKEN = re.compile(r"(\(?)([A-Za-z]+(?:'[A-Za-z]+)?)([,.?!)]*)")
SPACED_MARKS = {"-", "--", "..."}
EMOTICONS = [":)", ";)", ":(", ":D"]


def common(word: str) -> bool:
    return zipf_frequency(word.lower(), "en") >= TARGET_MINIMUM_ZIPF


def plain_tokens(text: str) -> list[tuple[str, str, str]] | None:
    """The tokens of a sentence of plain common words, or None. A spaced dash or ellipsis comes
    back as its own token with an empty word."""
    tokens = []
    for raw in text.split(" "):
        if raw in SPACED_MARKS or (raw.startswith("...") and set(raw) <= set(".?!")):
            tokens.append(("", "", raw))
            continue
        match = TOKEN.fullmatch(raw)
        if not match or not common(match.group(2)):
            return None
        tokens.append(match.groups())
    if not 4 <= sum(1 for token in tokens if token[1]) <= 14:
        return None
    return tokens


def load_sentences() -> dict[str, list[tuple[int, str, list]]]:
    halves = {"dev": [], "test": []}
    with bz2.open(CACHE, "rt", encoding="utf-8") as lines:
        for line in lines:
            sentence_id, _, text = line.rstrip("\n").split("\t", 2)
            if not text.isascii() or "  " in text:
                continue
            tokens = plain_tokens(text)
            if tokens is None:
                continue
            halves["dev" if int(sentence_id) % 2 == 0 else "test"].append((int(sentence_id), text, tokens))
    return halves


def join(tokens) -> str:
    return " ".join(opening + word + marks for opening, word, marks in tokens)


def with_spaces(tokens, index: int, spaces: int) -> str:
    """The sentence with `spaces` spaces between the word of token `index` and its marks."""
    opening, word, marks = tokens[index]
    changed = list(tokens)
    changed[index] = (opening, word + " " * spaces, marks)
    return join(changed)


def build_half(half: str, sentences, rng: random.Random) -> list[dict]:
    cases = []
    counts: dict[str, int] = {}

    def add(category, typed, intended, source):
        number = counts.get(category, 0)
        if number >= CASES_PER_CATEGORY:
            return False
        counts[category] = number + 1
        cases.append({
            "id": f"enspace-{half}-{category}-{number:04d}", "split": half, "category": category,
            "context": "", "typed": typed, "intended": intended, "source": source,
        })
        return True

    shuffled = list(sentences)
    rng.shuffle(shuffled)
    for sentence_id, text, tokens in shuffled:
        source = f"tatoeba:{sentence_id}"
        spaced = any(not word for _, word, _ in tokens)
        if spaced:
            if any(marks in ("-", "--") for _, word, marks in tokens if not word):
                add("clean_spaced_dash", text, text, source)
            else:
                add("clean_spaced_ellipsis", text, text, source)
            continue
        if join(tokens) != text:
            continue
        commas = [i for i, (_, _, marks) in enumerate(tokens) if marks.startswith(",")]
        brackets = [i for i, (_, _, marks) in enumerate(tokens) if marks.startswith(")")]
        last = len(tokens) - 1
        ends = [last] if tokens[last][2] in (".", "?", "!") else []
        used = False
        if commas and add("space_before_comma", with_spaces(tokens, rng.choice(commas), 1), text, source):
            used = True
        elif ends and add("space_before_end_mark", with_spaces(tokens, last, 1), text, source):
            used = True
        elif brackets and add("space_before_closing_bracket", with_spaces(tokens, rng.choice(brackets), 1), text, source):
            used = True
        elif ends and not commas and not brackets:
            body = text[:-1]
            emoticon = rng.choice(EMOTICONS)
            add("clean_emoticon", f"{body} {emoticon}", f"{body} {emoticon}", f"{source} with an emoticon added")
        if used:
            add("clean_marks_against_word", text, text, source)
    return cases


def main():
    halves = load_sentences()
    for half, sentences in halves.items():
        cases = build_half(half, sentences, random.Random(f"space-before-mark-{half}"))
        path = OUTPUT_DIR / f"english-space-before-mark.{half}.jsonl"
        path.write_text("".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8", newline="\n")
        tally: dict[str, int] = {}
        for case in cases:
            tally[case["category"]] = tally.get(case["category"], 0) + 1
        print(path.name, tally)


if __name__ == "__main__":
    main()

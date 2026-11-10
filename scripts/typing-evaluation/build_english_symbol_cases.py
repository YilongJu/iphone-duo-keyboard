"""Builds the English cases with a symbol or digit key in place of a letter:
cases/english-symbols.dev.jsonl and cases/english-symbols.test.jsonl.

A finger that aims at a letter can land on a symbol or digit key beside it: "[lease" for
"please", ";ike" for "like", "2hat" for "what". A keyboard gets `context` and `typed` and must
produce `intended`, as in the cases of build_english_cases.py. The files stand apart from
english.dev.jsonl and english.test.jsonl, so the scores on those files do not change.

The symbol keys beside each letter come from Shared/keyboard-layout.json (symbol_keys.py), for
the wide layout and the compact layout together. The sentences, the word-frequency limits and
the split are those of build_english_cases.py: a Tatoeba sentence with an even id feeds the dev
half and one with an odd id the test half.

Slip categories:
- symbol_first_letter: a symbol or digit key in place of the first letter.
- symbol_inner_letter: a digit or "[" in place of a letter after the first one.
- symbol_first_letter_two_words: two typed words, with the slip on the first letter of the second.
- symbol_plus_letter_slip: a symbol or digit in place of the first letter and one letter slip
  in the rest of the word.

Clean categories, where any change is an error:
- clean_symbol_token: a real token with a digit or a symbol, from inputs/symbol_tokens.txt.
- clean_bracket_or_dot_word: a real word right after "[", ".", ",", ";" or "-", as in "[note".

Which text counts as a slip. "[art" can be "part" with a slip or "art" after a bracket, and only
word frequency separates the two. A slip case needs the intended word to be at least
SLIP_ZIPF_GAP more frequent than the word that follows the symbol ("please" over "lease": 1.49).
A clean case needs every word that a neighbor letter would give to be at most CLEAN_ZIPF_GAP
more frequent than the typed word ("part" over "art": 0.49). Text between the two limits is
left out. A token with a digit is judged as a whole, by the rule for letter slips: wordfreq
lists real tokens such as "5pm", and "2hat" is not one of them.

Usage, from the repository root:
    uv run --with wordfreq python scripts/typing-evaluation/build_english_symbol_cases.py
"""
import json
import random
from pathlib import Path

from wordfreq import top_n_list

import build_english_cases as base
import keyboard_noise as noise
import symbol_keys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYMBOL_TOKENS = HERE / "inputs" / "symbol_tokens.txt"
OUTPUT_DIR = HERE / "cases"

CASES_PER_CATEGORY = 300
# One typed text appears at most this often in a category, so a few frequent words such as
# "you" do not fill it.
REPEATS_PER_TYPED_TEXT = 3
SLIP_ZIPF_GAP = 1.25
CLEAN_ZIPF_GAP = 0.5
# A word this frequent counts as a real word that a neighbor letter would give.
REAL_WORD_ZIPF = 3.0
# The symbols that people type right before a word on purpose.
SYMBOLS_BEFORE_A_WORD = "[.,;-"

NEIGHBORS = symbol_keys.symbol_neighbors()
INNER_SYMBOLS = sorted(symbol for symbol in NEIGHBORS if symbol_keys.may_stand_inside_a_word(symbol))


def common(word: str) -> bool:
    return base.plain(word) and base.zipf(word) >= base.TARGET_MINIMUM_ZIPF


def first_letter_slip(word: str, symbol: str) -> str | None:
    """Types `symbol` in place of the first letter, when its key is beside that letter and the
    result reads as a slip."""
    if not common(word) or len(word) < 3 or word[0] not in NEIGHBORS[symbol]:
        return None
    typed = symbol + word[1:]
    if symbol.isdigit():
        return typed if base.letter_slip_is_fair(word, typed) else None
    return typed if base.zipf(word) - base.zipf(word[1:]) >= SLIP_ZIPF_GAP else None


def make_first_letter_case(words, index, rng, symbol):
    typed = first_letter_slip(words[index], symbol)
    return None if typed is None else (typed, words[index])


def make_inner_letter_case(words, index, rng, symbol):
    word = words[index]
    if not common(word) or len(word) < 4:
        return None
    positions = [position for position in range(1, len(word)) if word[position] in NEIGHBORS[symbol]]
    if not positions:
        return None
    position = rng.choice(positions)
    typed = word[:position] + symbol + word[position + 1:]
    if symbol.isdigit() and not base.letter_slip_is_fair(word, typed):
        return None
    return typed, word


def make_two_word_case(words, index, rng, symbol):
    if index + 1 >= len(words) or not common(words[index]):
        return None
    typed = first_letter_slip(words[index + 1], symbol)
    if typed is None:
        return None
    return f"{words[index]} {typed}", f"{words[index]} {words[index + 1]}"


def make_symbol_plus_letter_case(words, index, rng, symbol):
    word = words[index]
    if len(word) < 6:
        return None
    first = first_letter_slip(word, symbol)
    if first is None:
        return None
    rest = noise.LETTER_OPERATORS[rng.choice(sorted(noise.LETTER_OPERATORS))](word[1:], rng)
    # A rest that spells the whole word, as in "0open", reads as a digit typed before the word.
    if rest is None or rest == word[1:] or rest == word or not base.letter_slip_is_fair(word, rest):
        return None
    typed = first[0] + rest
    if first[0].isdigit() and not base.letter_slip_is_fair(word, typed):
        return None
    return typed, word


def make_clean_symbol_word_case(words, index, rng, symbol, with_real_neighbor):
    """A real word right after a symbol. `with_real_neighbor` asks for a word that a neighbor
    letter turns into another real word, as "art" after "[" is one key from "part"."""
    word = words[index]
    if not common(word) or len(word) < 2:
        return None
    gaps = [base.zipf(letter + word) - base.zipf(word) for letter in NEIGHBORS[symbol]]
    if max(gaps) > CLEAN_ZIPF_GAP:
        return None
    real_neighbor = any(base.zipf(letter + word) >= REAL_WORD_ZIPF for letter in NEIGHBORS[symbol])
    if real_neighbor != with_real_neighbor:
        return None
    return symbol + word, symbol + word


def build_half(half: str, sentences, symbol_tokens) -> list[dict]:
    cases = []

    def add(category, context, typed, intended, source):
        number = sum(1 for case in cases if case["category"] == category)
        cases.append({
            "id": f"ensym-{half}-{category}-{number:04d}", "split": half, "category": category,
            "context": context, "typed": typed, "intended": intended, "source": source,
        })

    def from_sentences(category, maker, count, seed_name=None):
        rng = random.Random(f"{base.SEED}-{half}-{seed_name or category}")
        order = sentences[:]
        rng.shuffle(order)
        made_count = 0
        for sentence_id, words in order:
            index = rng.randrange(len(words))
            made = maker(words, index, rng)
            if made is None:
                continue
            typed, intended = made
            repeats = sum(1 for case in cases if case["category"] == category and case["typed"] == typed)
            if repeats >= REPEATS_PER_TYPED_TEXT:
                continue
            add(category, " ".join(words[:index]), typed, intended, f"tatoeba:{sentence_id}")
            made_count += 1
            if made_count == count:
                return
        raise SystemExit(f"{half}/{seed_name or category}: only {made_count} cases, wanted {count}")

    def per_symbol(category, maker, symbols):
        # Every symbol key gets the same count of cases, so the keys beside rare first
        # letters, such as "[" beside "p", count as much as the digits above "t" and "w".
        for symbol in symbols:
            from_sentences(
                category, lambda words, index, rng, symbol=symbol: maker(words, index, rng, symbol),
                CASES_PER_CATEGORY // len(symbols), seed_name=f"{category}-{symbol}")

    per_symbol("symbol_first_letter", make_first_letter_case, sorted(NEIGHBORS))
    per_symbol("symbol_inner_letter", make_inner_letter_case, INNER_SYMBOLS)
    per_symbol("symbol_first_letter_two_words", make_two_word_case, sorted(NEIGHBORS))
    per_symbol("symbol_plus_letter_slip", make_symbol_plus_letter_case, sorted(NEIGHBORS))

    rng = random.Random(f"{base.SEED}-{half}-clean_symbol_token")
    for token in symbol_tokens:
        sentence_id, sentence = rng.choice(sentences)
        cut = rng.randint(0, min(4, len(sentence)))
        add("clean_symbol_token", " ".join(sentence[:cut]), token, token, f"tatoeba:{sentence_id}")

    # Each symbol gets the same count, half of it with a word that is one key from another word.
    per_bucket = CASES_PER_CATEGORY // (2 * len(SYMBOLS_BEFORE_A_WORD))
    for symbol in SYMBOLS_BEFORE_A_WORD:
        for with_real_neighbor in (True, False):
            from_sentences(
                "clean_bracket_or_dot_word",
                lambda words, index, rng, symbol=symbol, flag=with_real_neighbor: make_clean_symbol_word_case(words, index, rng, symbol, flag),
                per_bucket, seed_name=f"clean_bracket_or_dot_word-{symbol}-{with_real_neighbor}")
    return cases


def main():
    for symbol in SYMBOLS_BEFORE_A_WORD:
        if symbol not in NEIGHBORS:
            raise SystemExit(f"the layout file does not put {symbol!r} beside a letter")
    vocabulary = set(top_n_list("en", 60000))
    sentences = base.load_sentences(vocabulary)
    tokens = [line.strip() for line in SYMBOL_TOKENS.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("# ")]
    if len(tokens) != len(set(tokens)):
        raise SystemExit(f"{SYMBOL_TOKENS.name} lists a token twice")
    symbol_tokens = {"dev": tokens[0::2], "test": tokens[1::2]}

    OUTPUT_DIR.mkdir(exist_ok=True)
    for half in ("dev", "test"):
        cases = build_half(half, sentences[half], symbol_tokens[half])
        path = OUTPUT_DIR / f"english-symbols.{half}.jsonl"
        path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")
        counts = {}
        for case in cases:
            counts[case["category"]] = counts.get(case["category"], 0) + 1
        print(f"wrote {path.relative_to(ROOT)}: {len(cases)} cases from {len(sentences[half])} sentences")
        for category, count in counts.items():
            sample = next(case for case in cases if case["category"] == category)
            print(f"  {category:32s} {count:4d}   e.g. {sample['typed']!r} -> {sample['intended']!r}")


if __name__ == "__main__":
    main()

"""Builds Shared/lexicon-english.bin, the English word data of the typing engine.

Sources:
- SymSpell frequency_dictionary_en_82_765.txt and frequency_bigramdictionary_en_243_342.txt
  (MIT license, https://github.com/wolfgarbe/SymSpell): a list of correctly spelled words with
  book counts, and word pairs with book counts.
- The wordfreq package: how often each token appears in everyday text, on the Zipf scale
  (3 means once per million words, 6 means once per thousand).
- Wikipedia's machine-readable list of common misspellings (CC BY-SA 4.0).

The word list has three parts:
1. Every SymSpell word, except a contraction written without its apostrophe when the
   contraction is at least ten times as frequent ("doesnt" next to "doesn't"). The keyboard
   must see such a token as a slip.
2. Every wordfreq token at Zipf 3.5 or more that is not a listed misspelling and not such a
   contraction. This part adds contractions, names and chat words that a book list lacks.
3. Every rarer wordfreq token, down to Zipf 2.0, that does not look like a slip of a common
   word: it is not a listed misspelling, and no word at least 100 times as frequent sits one
   edit away. Everyday text holds many slips ("teh" is as frequent as many real rare words),
   and this rule keeps them out while it lets real rare words and names in.

Usage, from the repository root:
    uv run --with wordfreq python scripts/typing-engine/build_english_lexicon.py
"""
import math
import re
import urllib.request
from pathlib import Path

from wordfreq import top_n_list, zipf_frequency

from lexicon_format import MODEL_MIXED, write_lexicon

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "build" / "typing-engine"
OUTPUT = ROOT / "Shared" / "lexicon-english.bin"
SYMSPELL = "https://raw.githubusercontent.com/wolfgarbe/SymSpell/master/SymSpell/"
WORDS_FILE = "frequency_dictionary_en_82_765.txt"
PAIRS_FILE = "frequency_bigramdictionary_en_243_342.txt"
MISSPELLINGS_URL = "https://en.wikipedia.org/w/index.php?title=Wikipedia:Lists_of_common_misspellings/For_machines&action=raw"
MISSPELLINGS_FILE = "wikipedia_misspellings.txt"
WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
COMMON_TOKEN_ZIPF = 3.5
RARE_TOKEN_ZIPF = 2.0
# A rare token one edit away from a word this much more frequent is taken for a slip of that word.
SLIP_ZIPF_GAP = 2.0
# A contraction this much more frequent than its form without the apostrophe wins over that form.
CONTRACTION_ZIPF_GAP = 1.0
ALPHABET = "abcdefghijklmnopqrstuvwxyz"


def fetch(url: str, name: str) -> list[str]:
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "duo-keyboard-build/1.0"})
        with urllib.request.urlopen(request) as response:
            path.write_bytes(response.read())
    return path.read_text(encoding="utf-8-sig").splitlines()


def one_edit_away(word: str) -> set[str]:
    """Every string one slip away: a letter dropped, added or changed, or two letters swapped."""
    cuts = [(word[:index], word[index:]) for index in range(len(word) + 1)]
    result = {left + right[1:] for left, right in cuts if right}
    result |= {left + right[1] + right[0] + right[2:] for left, right in cuts if len(right) > 1}
    result |= {left + letter + right[1:] for left, right in cuts if right for letter in ALPHABET}
    result |= {left + letter + right for left, right in cuts for letter in ALPHABET}
    result.discard(word)
    return result


# The endings of English contractions after the apostrophe.
CONTRACTION_ENDINGS = {"s", "re", "ll", "d", "ve", "m"}


def is_other_ending_of_a_contraction(word: str, frequent_neighbors: set[str]) -> bool:
    """True for a contraction, as "what'd", whose frequent neighbors one slip away are all
    contractions of the same word with another ending, as "what's". Such a token is a rarer
    contraction and not a slip. "get's" stays out, because "gets" is one of its neighbors."""
    if word.count("'") != 1 or not frequent_neighbors:
        return False
    stem, ending = word.split("'")
    if ending not in CONTRACTION_ENDINGS:
        return False
    for neighbor in frequent_neighbors:
        if neighbor.count("'") != 1:
            return False
        other_stem, other_ending = neighbor.split("'")
        if other_stem != stem or other_ending not in CONTRACTION_ENDINGS:
            return False
    return True


def main():
    book_counts = {}
    for line in fetch(SYMSPELL + WORDS_FILE, WORDS_FILE):
        word, count = line.split()
        if WORD.fullmatch(word):
            book_counts[word] = int(count)
    book_total = sum(book_counts.values())

    misspellings = {
        line.strip().split("->")[0]
        for line in fetch(MISSPELLINGS_URL, MISSPELLINGS_FILE) if "->" in line and not line.startswith("<")
    }

    def everyday_zipf(word: str) -> float:
        return zipf_frequency(word, "en")

    def zipf(word: str) -> float:
        """Zipf frequency: wordfreq when it knows the word, the book count otherwise."""
        value = everyday_zipf(word)
        return value if value > 0 else math.log10(book_counts[word] / book_total * 1e9)

    everyday = [word for word in top_n_list("en", 400000) if WORD.fullmatch(word) and everyday_zipf(word) >= RARE_TOKEN_ZIPF]
    # The most frequent contraction of each form without the apostrophe: "you're" for "youre",
    # and not the rarer "your'e".
    contraction_of = {}
    for word in everyday:
        if "'" in word:
            bare = word.replace("'", "")
            if bare not in contraction_of or everyday_zipf(word) > everyday_zipf(contraction_of[bare]):
                contraction_of[bare] = word

    def is_weaker_contraction_form(word: str) -> bool:
        full = contraction_of.get(word)
        return full is not None and everyday_zipf(full) - everyday_zipf(word) >= CONTRACTION_ZIPF_GAP

    words = {word for word in book_counts if not is_weaker_contraction_form(word)}
    part_one = len(words)
    for word in everyday:
        if everyday_zipf(word) >= COMMON_TOKEN_ZIPF and word not in misspellings and not is_weaker_contraction_form(word):
            words.add(word)
    part_two = len(words) - part_one

    # For each common word, every string one slip away, with the common word's frequency.
    slip_source: dict[str, float] = {}
    for word in words:
        frequency = zipf(word)
        if frequency >= RARE_TOKEN_ZIPF + SLIP_ZIPF_GAP:
            for neighbor in one_edit_away(word):
                if frequency > slip_source.get(neighbor, 0.0):
                    slip_source[neighbor] = frequency
    for word in everyday:
        if word in words or word in misspellings or is_weaker_contraction_form(word):
            continue
        if slip_source.get(word, 0.0) - everyday_zipf(word) >= SLIP_ZIPF_GAP:
            frequent_neighbors = {neighbor for neighbor in one_edit_away(word)
                                  if neighbor in words and zipf(neighbor) - everyday_zipf(word) >= SLIP_ZIPF_GAP}
            if not is_other_ending_of_a_contraction(word, frequent_neighbors):
                continue
        words.add(word)
    part_three = len(words) - part_one - part_two

    # Zipf is log10 of the frequency per billion words, so 10 ** (zipf - 9) is a probability.
    entries = [(word, word, (zipf(word) - 9) * math.log(10), 0.0) for word in sorted(words)]

    pairs = {}
    for line in fetch(SYMSPELL + PAIRS_FILE, PAIRS_FILE):
        first, second, count = line.split()
        if first in words and second in words and first in book_counts:
            # The chance that `second` follows `first`, from counts of one book corpus.
            pairs[(first, second)] = math.log(min(1.0, int(count) / book_counts[first]))

    stats = write_lexicon(OUTPUT, entries, pairs, MODEL_MIXED)
    print(f"words: {part_one} from the book list, {part_two} common everyday tokens, {part_three} rare everyday tokens")
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {stats}")
    for probe in ["teh", "recieve", "alot", "doesnt", "dont", "cant", "its", "xcode", "umar", "imax", "lago", "getters", "backend", "kubernetes", "lol", "wanna", "don't", "i'm"]:
        print(f"  {probe:12s} {'in' if probe in words else 'out'}")


if __name__ == "__main__":
    main()

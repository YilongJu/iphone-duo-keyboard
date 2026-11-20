"""Builds Shared/pinyin-dictionary.txt, the word list that the keyboard reads at its start.

The keyboard's Pinyin engine (Shared/PinyinEngine.swift) uses the list for the candidates that
the typing engine does not give: the words whose syllables start with typed first letters, the
words that complete a syllable, and the reading of letters with an apostrophe. The list holds
the most frequent words of the Pinyin lexicon (Shared/lexicon-pinyin.bin), from the same data:

- The language model and the dictionary of libime (LGPL-2.1-or-later): the words, their
  readings with their shares, and their probabilities.
- The Wanxiang word lists (CC BY 4.0): the weight of a word, which grows with how often people
  write it, and the additions of scripts/pinyin-dictionary/modern_words.py
  (scripts/pinyin-dictionary/pinyin-updates.tsv.gz).

The frequency of a word of two or more characters is its Wanxiang weight. The libime model
reads many frequent words as two words, as the word for "hello", and puts them at its floor, so
its probabilities do not order the words that first letters stand for. A word without a
weight, and every single character, gets the weight that fits its probability in the model,
by the line of modern_words.py.

The list holds the WORDS most frequent words of two or more characters, and every single
character that is in the GB2312 character set or that the model puts above its floor. A reading
with less than LOWEST_SHARE of a word's uses stays out. The keyboard keeps the whole list in
memory, so the count of words equals that of the list before it, which came from the Android
Open Source Project.

A line holds "syllables<TAB>word<TAB>frequency", with the most frequent word first. The
keyboard reads the file top to bottom, so the candidates for a spelling keep that order. A
reading with the syllable "lve" or "nve" is also listed with "lue" or "nue", because people
type both.

Usage, from the repository root, with the libime files in build/libime-data:
    python3 scripts/pinyin-dictionary/build_dictionary.py
"""
import gzip
import re
import sys
from pathlib import Path

import modern_words

ROOT = Path(__file__).resolve().parents[2]
LIBIME = ROOT / "build" / "libime-data"
OUTPUT = ROOT / "Shared" / "pinyin-dictionary.txt"

WORDS = 48000
LOWEST_SHARE = 0.05
# The margin above the model's floor from which a character outside GB2312 counts as in use.
CHARACTER_ABOVE_FLOOR = 0.3
# A syllable that only marks the sound "r" at the end of a word. Nobody types it as a syllable.
LEFT_OUT_SYLLABLES = {"r"}
SYLLABLE_VARIANTS = {"lve": "lue", "nve": "nue"}
# The dictionary also lists the letters A to Z and words with a letter in them. The list holds
# words of Chinese characters only.
CHINESE_WORD = re.compile(r"[㐀-䶿一-鿿]+")


def in_gb2312(character: str) -> bool:
    try:
        character.encode("gb2312")
    except UnicodeEncodeError:
        return False
    return True


def main():
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    model = modern_words.read_model_words()
    floor = model["<unk>"]
    # Each reading of a word as its syllables and the base-10 log of its share.
    readings: dict[str, list[tuple[tuple[str, ...], float]]] = {}
    for line in (LIBIME / "dict_sc.txt").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) == 2:
            fields.append("0")
        if len(fields) != 3:
            raise SystemExit(f"unexpected dictionary line: {line!r}")
        word, syllables, share = fields[0], tuple(fields[1].split("'")), float(fields[2])
        if word in model and len(syllables) == len(word) and CHINESE_WORD.fullmatch(word):
            readings.setdefault(word, []).append((syllables, share))
    lexicon_words = set(readings)
    _, weight = modern_words.read_weights()
    slope, intercept, _ = modern_words.fit_weights(model, lexicon_words, weight)

    def weight_of_probability(value: float) -> float:
        return 10 ** ((value - intercept) / slope)

    frequency = {word: weight_of_probability(model[word]) for word in readings}
    with gzip.open(modern_words.UPDATES, "rt", encoding="utf-8") as file:
        update_lines = file.read().splitlines()
    for line in update_lines:
        word, pinyin, value = line.split("\t")
        if pinyin:
            readings.setdefault(word, []).append((tuple(pinyin.split("'")), 0.0))
            frequency[word] = weight_of_probability(float(value))
    for word in frequency:
        if len(word) >= 2 and weight.get(word, 0.0) >= 1.0:
            frequency[word] = weight[word]

    longer = sorted((word for word in frequency if len(word) >= 2), key=lambda word: (-frequency[word], word))[:WORDS]
    single = [word for word in frequency
              if len(word) == 1 and (in_gb2312(word) or model[word] > floor + CHARACTER_ABOVE_FLOOR)]
    entries = []
    for word in longer + single:
        for syllables, share in readings[word]:
            if 10 ** share < LOWEST_SHARE or any(syllable in LEFT_OUT_SYLLABLES for syllable in syllables):
                continue
            spellings = {syllables, tuple(SYLLABLE_VARIANTS.get(syllable, syllable) for syllable in syllables)}
            for spelling in sorted(spellings):
                entries.append((frequency[word] * 10 ** share, " ".join(spelling), word))
    if any(not all(part.isascii() and part.isalpha() and part.islower() for part in key.split(" ")) for _, key, _ in entries):
        raise SystemExit("a reading holds a character that is not a lower-case letter")

    entries.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    text = "".join(f"{key}\t{word}\t{value:.5g}\n" for value, key, word in entries)
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    syllable_set = {key for _, key, _ in entries if " " not in key}
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(entries)} lines, {len(longer)} words of two or more characters "
          f"down to the weight {frequency[longer[-1]]:.4g}, {len(single)} characters, {len(syllable_set)} syllables, "
          f"{len(text.encode('utf-8'))} bytes")
    print("first lines: " + " | ".join(text.splitlines()[:8]))


if __name__ == "__main__":
    main()

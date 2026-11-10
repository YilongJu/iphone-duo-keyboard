"""Builds Shared/lexicon-pinyin.bin, the Chinese word data of the typing engine.

Source: Shared/pinyin-dictionary.txt, which scripts/pinyin-dictionary/build_dictionary.py makes
from the Android Open Source Project's Pinyin dictionary (Apache License 2.0). Each line holds a
spelling as syllables, a word and the word's frequency.

A word's spelling in the lexicon is its syllables written together, as a person types them:
"ni hao" becomes "nihao".

Usage, from the repository root:
    python scripts/typing-engine/build_pinyin_lexicon.py
"""
import math
from pathlib import Path

from lexicon_format import MODEL_MIXED, write_lexicon

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "Shared" / "pinyin-dictionary.txt"
OUTPUT = ROOT / "Shared" / "lexicon-pinyin.bin"


def main():
    rows = []
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        spelling, word, frequency = line.split("\t")
        rows.append((spelling.replace(" ", ""), word, float(frequency)))
    total = sum(frequency for _, _, frequency in rows)
    entries = [(spelling, word, math.log(frequency / total), 0.0) for spelling, word, frequency in rows]
    stats = write_lexicon(OUTPUT, entries, {}, MODEL_MIXED)
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {stats}")


if __name__ == "__main__":
    main()

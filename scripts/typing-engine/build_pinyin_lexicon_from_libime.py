"""Builds Shared/lexicon-pinyin.bin from the libime dictionary and language model.

Sources, both LGPL-2.1-or-later, from https://download.fcitx-im.org/data/:
- dict-20260907.tar.zst: Chinese words with their Pinyin.
- lm_sc.arpa-20260629.tar.zst: a word language model in ARPA text form, with the probability
  of each word, of each word after one word, and of each word after two words.

The engine uses the first two levels: a word's own probability, and its probability after the
word before it. The script keeps the word pairs that change the probability most.

Usage, from the repository root, on a machine that holds the unpacked files:
    python3 scripts/typing-engine/build_pinyin_lexicon_from_libime.py FOLDER PAIRS
"""
import sys
from pathlib import Path

folder = Path(sys.argv[1])
files = sorted(path for path in folder.rglob("*") if path.is_file() and path.suffix != ".zst")
print("files:", [str(path.relative_to(folder)) for path in files])
raise SystemExit("The converter is not written yet: this first run only shows the file formats.")

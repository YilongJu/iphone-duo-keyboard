"""Runs the keyboard's sentence search on sample Pinyin, in Python, to judge the output by eye.

The search matches Shared/PinyinEngine.swift: split the letters into syllables with the longest
syllable first, then pick the cut into dictionary words whose frequencies have the largest product.

Usage, from the repository root:
    python scripts/pinyin-dictionary/try_sentences.py [pinyin ...]
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = [
    "nihaoma",
    "jintiantianqizenmeyang",
    "womenmingtianqubeijingkaihui",
    "woxianghewomendepengyouyiqiquchifan",
    "woxiangmaiyigexindeshouji",
    "zhegejianpanhenhaoyong",
    "qingwennizhidaozenmezouma",
    "tashiwodelaoshi",
    "xiexienidebangzhu",
]

entries = {}
syllables = set()
rows = []
for line in (ROOT / "Shared" / "pinyin-dictionary.txt").read_text(encoding="utf-8").splitlines():
    key, word, frequency = line.split("\t")
    rows.append((key, word, float(frequency)))
total = sum(frequency for _, _, frequency in rows)
for key, word, frequency in rows:
    entries.setdefault(key, []).append((word, math.log(frequency / total)))
    if " " not in key:
        syllables.add(key)
syllables -= {"n", "ng"}
longest_word = max(len(word) for _, word, _ in rows)


def parse(letters):
    if not letters:
        return []
    for length in range(min(6, len(letters)), 0, -1):
        if letters[:length] in syllables:
            rest = parse(letters[length:])
            if rest is not None:
                return [letters[:length]] + rest
    return None


def sentence(parsed):
    best = [None] * (len(parsed) + 1)
    best[0] = ("", 0.0)
    for end in range(1, len(parsed) + 1):
        for start in range(max(0, end - longest_word), end):
            top = entries.get(" ".join(parsed[start:end]))
            if best[start] is None or not top:
                continue
            score = best[start][1] + top[0][1]
            if best[end] is None or score > best[end][1]:
                best[end] = (best[start][0] + top[0][0], score)
    return best[-1][0] if best[-1] else None


for letters in sys.argv[1:] or SAMPLES:
    parsed = parse(letters)
    print(letters, "->", sentence(parsed) if parsed else "no split into syllables")

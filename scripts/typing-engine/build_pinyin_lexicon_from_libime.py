"""Builds Shared/lexicon-pinyin.bin from the libime dictionary and language model.

Sources, both LGPL-2.1-or-later, from https://download.fcitx-im.org/data/:
- dict-20260907.tar.zst, file dict_sc.txt: one line per word reading, as word, Pinyin with an
  apostrophe between syllables, and the base-10 log of the share of that reading.
- lm_sc.arpa-20260629.tar.zst, file lm_sc.arpa: a word language model in ARPA text form. A line
  holds the base-10 log probability of a word (or of the last word of a pair or a triple given
  the words before it), the words, and a back-off weight.

The engine uses the first two levels: a word's own probability with its back-off weight, and a
word's probability after one word. The script keeps the pairs that change the probability most:
a pair's weight is the chance of seeing the pair times how far its listed log probability sits
above the back-off estimate.

A word's spelling is its Pinyin written without apostrophes, as a person types it. A spelling
with "lve" or "nve" is also listed with "lue" or "nue", and the other way round, because people
type both.

Usage, from the repository root, on a machine that holds the unpacked files:
    python3 scripts/typing-engine/build_pinyin_lexicon_from_libime.py FOLDER PAIRS
"""
import heapq
import math
import re
import sys
from pathlib import Path

from lexicon_format import MODEL_BACK_OFF, write_lexicon

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "Shared" / "lexicon-pinyin.bin"
LN10 = math.log(10)
SPELLING = re.compile(r"[a-z]+")
# The other common way to type the two syllables with the sound "ü" after l and n.
SPELLING_VARIANTS = [("lve", "lue"), ("nve", "nue"), ("lue", "lve"), ("nue", "nve")]


def read_language_model(path: Path, pair_limit: int):
    words: dict[str, tuple[float, float]] = {}
    pairs_heap: list[tuple[float, str, str, float]] = []
    section = 0
    listed_pairs = 0
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            line = line.rstrip("\n")
            if line.startswith("\\"):
                section = {"\\1-grams:": 1, "\\2-grams:": 2}.get(line, 0 if line != "\\data\\" else -1)
                if line == "\\3-grams:":
                    break
                continue
            if not line or section <= 0:
                continue
            fields = line.split("\t")
            if section == 1:
                back_off = float(fields[2]) if len(fields) > 2 else 0.0
                words[fields[1]] = (float(fields[0]), back_off)
            else:
                first, _, second = fields[1].partition(" ")
                if first not in words or second not in words:
                    continue
                listed_pairs += 1
                log_probability = float(fields[0])
                estimate = words[first][1] + words[second][0]
                gain = log_probability - estimate
                if gain <= 0:
                    # The back-off estimate already gives this pair at least this much.
                    continue
                weight = 10 ** (words[first][0] + log_probability) * gain
                item = (weight, first, second, log_probability)
                if len(pairs_heap) < pair_limit:
                    heapq.heappush(pairs_heap, item)
                elif item > pairs_heap[0]:
                    heapq.heapreplace(pairs_heap, item)
    return words, pairs_heap, listed_pairs


def main():
    folder = Path(sys.argv[1])
    pair_limit = int(sys.argv[2])
    report = []

    words, pairs_heap, listed_pairs = read_language_model(folder / "lm_sc.arpa", pair_limit)
    report.append(f"language model: {len(words)} words, {listed_pairs} pairs between known words, {len(pairs_heap)} pairs kept")

    entries = []
    known_texts = set()
    skipped_unknown = skipped_spelling = 0
    for line in (folder / "dict_sc.txt").read_text(encoding="utf-8").splitlines():
        text, pinyin, reading_log_share = line.split("\t")
        if text not in words:
            skipped_unknown += 1
            continue
        spelling = pinyin.replace("'", "")
        if not SPELLING.fullmatch(spelling):
            skipped_spelling += 1
            continue
        log_probability = (words[text][0] + float(reading_log_share)) * LN10
        back_off = words[text][1] * LN10
        spellings = {spelling}
        for old, new in SPELLING_VARIANTS:
            if old in spelling:
                spellings.add(spelling.replace(old, new))
        for one in sorted(spellings):
            entries.append((one, text, log_probability, back_off))
        known_texts.add(text)
    report.append(
        f"dictionary: {len(entries)} spellings of {len(known_texts)} words kept, "
        f"{skipped_unknown} lines skipped because the language model does not know the word, "
        f"{skipped_spelling} lines skipped because the Pinyin holds other characters")

    pairs = {
        (first, second): log_probability * LN10
        for _, first, second, log_probability in pairs_heap
        if first in known_texts and second in known_texts
    }
    stats = write_lexicon(OUTPUT, entries, pairs, MODEL_BACK_OFF)
    report.append(f"wrote {OUTPUT.relative_to(ROOT)}: {stats}")
    for line in report:
        print(line)
    (folder / "lexicon-report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

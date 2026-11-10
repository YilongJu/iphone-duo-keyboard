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

The language model also holds two marks, "<s>" for the start of a sentence and "</s>" for its
end, with the chance of each word at the start and of the end after each word. The lexicon keeps
both marks under spellings that nobody can type (the bytes 1 and 2), so the engine can ask how
likely a word is to open or to close a sentence.

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
SENTENCE_START = "<s>"
SENTENCE_END = "</s>"
# Spellings of the two marks in the letter tree. Typed text never holds these bytes.
MARK_SPELLINGS = {SENTENCE_START: "\x01", SENTENCE_END: "\x02"}


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
                # The start mark has no probability of its own in the file. A sentence starts as
                # often as it ends, so the end mark's probability stands in for the weight.
                first_log_probability = words[SENTENCE_END][0] if first == SENTENCE_START else words[first][0]
                weight = 10 ** (first_log_probability + log_probability) * gain
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
    two_field_lines = []
    for line in (folder / "dict_sc.txt").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) == 2:
            # A line without the third field gives a word and its Pinyin only. The script reads
            # it as the word's single reading, which is a log share of 0, and reports the count.
            two_field_lines.append(line)
            fields.append("0")
        if len(fields) != 3:
            raise SystemExit(f"unexpected dictionary line: {line!r}")
        text, pinyin, reading_log_share = fields
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
    report.append(
        f"dictionary lines with two fields, read as a word's single reading: {len(two_field_lines)}"
        + (f", first: {two_field_lines[0]!r}" if two_field_lines else ""))

    marks_in_file = sorted(word for word in words if word.startswith("<"))
    report.append(f"marks in the language model: {marks_in_file}")
    missing = [mark for mark in MARK_SPELLINGS if mark not in words]
    if missing:
        print("\n".join(report))
        raise SystemExit(f"the language model does not list the marks {missing}")
    for mark, spelling in MARK_SPELLINGS.items():
        entries.append((spelling, mark, words[mark][0] * LN10, words[mark][1] * LN10))
        known_texts.add(mark)

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

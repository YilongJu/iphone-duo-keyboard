"""Builds Shared/lexicon-pinyin.bin from the libime dictionary and language model.

Sources, both LGPL-2.1-or-later, from https://download.fcitx-im.org/data/:
- dict-20260907.tar.zst, file dict_sc.txt: one line per word reading, as word, Pinyin with an
  apostrophe between syllables, and the base-10 log of the share of that reading.
- lm_sc.arpa-20260629.tar.zst, file lm_sc.arpa: a word language model in ARPA text form. A line
  holds the base-10 log probability of a word (or of the last word of a pair or a triple given
  the words before it), the words, and a back-off weight.

The engine uses all three levels: a word's own probability with its back-off weight, a word's
probability after one word with the pair's back-off weight, and a word's probability after two
words. The script keeps the pairs and the triples that change the probability most. The weight
of a pair or a triple is the chance of seeing it times the distance between its listed log
probability and the back-off estimate that the engine uses without it. With --gain higher, the
default, the script keeps only the entries that sit above their estimate. With --gain any it
also keeps the entries below.

A kept triple needs the pair of its first two words, so the script keeps that pair too. With
triples, every kept pair holds its back-off weight. Without triples the lexicon is a pair model,
and the pairs hold a back-off weight of 0.

A word's spelling is its Pinyin written without apostrophes, as a person types it. A spelling
with "lve" or "nve" is also listed with "lue" or "nue", and the other way round, because people
type both. A word with several readings has a reading cost for each: the log of the reading's
share. The word's own log probability holds the cost, and the lexicon lists it apart as well,
so the engine can add it to the value of a pair or a triple.

The language model can also hold two marks, "<s>" for the start of a sentence and "</s>" for
its end, with the chance of each word at the start and of the end after each word. The lexicon
keeps the marks that the model lists under spellings that nobody can type (the bytes 1 and 2),
so the engine can ask how likely a word is to open or to close a sentence.

Usage, from the repository root, on a machine that holds the unpacked files:
    python3 scripts/typing-engine/build_pinyin_lexicon_from_libime.py FOLDER PAIRS [TRIPLES] [--gain any]
"""
import argparse
import heapq
import math
import re
from pathlib import Path

from lexicon_format import MODEL_BACK_OFF, write_lexicon_with_triples

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
SECTIONS = {"\\1-grams:": 1, "\\2-grams:": 2, "\\3-grams:": 3}


def read_language_model(path: Path, pair_limit: int, triple_limit: int, any_gain: bool):
    """Reads the model. Returns the words, the kept pairs, the kept triples and counts.

    The function numbers the words while it reads, so the table of all pairs has small keys.
    """
    words: dict[str, tuple[float, float]] = {}
    numbers: dict[str, int] = {}
    all_pairs: dict[int, tuple[float, float]] = {}
    pairs_heap: list[tuple[float, str, str, float]] = []
    triples_heap: list[tuple[float, str, str, str, float]] = []
    counts = {"pairs": 0, "pairs_above": 0, "triples": 0, "triples_above": 0}
    section = 0

    def weight_of(seen_log_probability: float, gain: float) -> float | None:
        """The weight of an entry, or None for an entry that the script does not keep."""
        if gain > 0:
            return 10 ** seen_log_probability * gain
        if any_gain and gain < 0:
            return 10 ** seen_log_probability * -gain
        return None

    def own_log_probability(word: str) -> float:
        # The start mark has no probability of its own in the file. A sentence starts as often
        # as it ends, so the end mark's probability stands in for the weight.
        return words[SENTENCE_END][0] if word == SENTENCE_START else words[word][0]

    with path.open(encoding="utf-8") as lines:
        for line in lines:
            line = line.rstrip("\n")
            if line.startswith("\\"):
                section = SECTIONS.get(line, 0)
                continue
            if not line or section == 0:
                continue
            fields = line.split("\t")
            if section == 1:
                back_off = float(fields[2]) if len(fields) > 2 else 0.0
                numbers[fields[1]] = len(words)
                words[fields[1]] = (float(fields[0]), back_off)
            elif section == 2:
                first, _, second = fields[1].partition(" ")
                if first not in words or second not in words:
                    continue
                counts["pairs"] += 1
                log_probability = float(fields[0])
                back_off = float(fields[2]) if len(fields) > 2 else 0.0
                all_pairs[numbers[first] * len(words) + numbers[second]] = (log_probability, back_off)
                # Without the pair, the engine uses the first word's back-off weight plus the
                # second word's own log probability.
                estimate = words[first][1] + words[second][0]
                gain = log_probability - estimate
                counts["pairs_above"] += gain > 0
                weight = weight_of(own_log_probability(first) + log_probability, gain)
                if weight is None:
                    continue
                item = (weight, first, second, log_probability)
                if len(pairs_heap) < pair_limit:
                    heapq.heappush(pairs_heap, item)
                elif pairs_heap and item > pairs_heap[0]:
                    heapq.heapreplace(pairs_heap, item)
            else:
                first, second, third = fields[1].split(" ")
                if first not in words or second not in words or third not in words:
                    continue
                counts["triples"] += 1
                log_probability = float(fields[0])
                context = all_pairs.get(numbers[first] * len(words) + numbers[second])
                if context is None:
                    raise SystemExit(f"the triple {fields[1]!r} has no pair for its first two words")
                # Without the triple, the engine uses the pair's back-off weight plus the chance
                # of the third word after the second.
                after_second = all_pairs.get(numbers[second] * len(words) + numbers[third])
                estimate = context[1] + (after_second[0] if after_second is not None else words[second][1] + words[third][0])
                gain = log_probability - estimate
                counts["triples_above"] += gain > 0
                weight = weight_of(own_log_probability(first) + context[0] + log_probability, gain)
                if weight is None:
                    continue
                item = (weight, first, second, third, log_probability)
                if len(triples_heap) < triple_limit:
                    heapq.heappush(triples_heap, item)
                elif triples_heap and item > triples_heap[0]:
                    heapq.heapreplace(triples_heap, item)

    def listed_pair(first: str, second: str) -> tuple[float, float]:
        return all_pairs[numbers[first] * len(words) + numbers[second]]

    triples = {(first, second, third): log_probability for _, first, second, third, log_probability in triples_heap}
    pairs = {(first, second): listed_pair(first, second) for _, first, second, _ in pairs_heap}
    counts["pairs_by_weight"] = len(pairs)
    for first, second, _ in triples:
        if (first, second) not in pairs:
            pairs[(first, second)] = listed_pair(first, second)
    counts["pairs_for_triples"] = len(pairs) - counts["pairs_by_weight"]
    return words, pairs, triples, counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path, help="the folder with lm_sc.arpa and dict_sc.txt")
    parser.add_argument("pairs", type=int, help="the number of word pairs to keep by weight")
    parser.add_argument("triples", type=int, nargs="?", default=0, help="the number of word triples to keep by weight")
    parser.add_argument("--gain", choices=["higher", "any"], default="higher",
                        help="keep only the entries above their back-off estimate, or the entries on both sides")
    arguments = parser.parse_args()
    folder = arguments.folder
    report = [f"settings: {arguments.pairs} pairs, {arguments.triples} triples, gain {arguments.gain}"]

    words, kept_pairs, kept_triples, counts = read_language_model(
        folder / "lm_sc.arpa", arguments.pairs, arguments.triples, arguments.gain == "any")
    report.append(
        f"language model: {len(words)} words, {counts['pairs']} pairs between known words, "
        f"{counts['pairs_above']} of them above their back-off estimate, {counts['pairs_by_weight']} pairs kept by weight")
    report.append(
        f"language model: {counts['triples']} triples between known words, {counts['triples_above']} of them above "
        f"their back-off estimate, {len(kept_triples)} triples kept, {counts['pairs_for_triples']} more pairs kept "
        f"because a kept triple needs them")

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
        reading_cost = float(reading_log_share) * LN10
        spellings = {spelling}
        for old, new in SPELLING_VARIANTS:
            if old in spelling:
                spellings.add(spelling.replace(old, new))
        for one in sorted(spellings):
            entries.append((one, text, log_probability, back_off, reading_cost))
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
    # A model without the two sentence marks gives a lexicon without them, and the engine then
    # reads the first word of a text by its own probability.
    for mark, spelling in MARK_SPELLINGS.items():
        if mark not in words:
            continue
        entries.append((spelling, mark, words[mark][0] * LN10, words[mark][1] * LN10, 0.0))
        known_texts.add(mark)

    # A lexicon without triples is a pair model, and a pair model has no use for the back-off
    # weight of a pair.
    pairs = {
        (first, second): (log_probability * LN10, back_off * LN10 if kept_triples else 0.0)
        for (first, second), (log_probability, back_off) in kept_pairs.items()
        if first in known_texts and second in known_texts
    }
    triples = {
        key: log_probability * LN10 for key, log_probability in kept_triples.items()
        if all(text in known_texts for text in key)
    }
    stats = write_lexicon_with_triples(OUTPUT, entries, pairs, triples, MODEL_BACK_OFF)
    report.append(f"wrote {OUTPUT.relative_to(ROOT)}: {stats}")
    for line in report:
        print(line)
    (folder / "lexicon-report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

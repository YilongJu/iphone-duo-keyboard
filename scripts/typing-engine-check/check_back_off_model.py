"""Checks the engine's word-triple model against a second implementation in Python.

The check has three parts.

1. Scores. The script writes a small random lexicon of version 3 with several words per
   spelling, words with two spellings, pairs and triples. For random typed strings it finds
   the highest score of any reading (any way to cut the string into spellings, with any word
   of each spelling) by the rule of an ARPA back-off model: a listed triple, or the pair's
   back-off weight plus a listed pair, or both back-off weights plus the word's own log
   probability. The end of the text costs the back-off weights of the last word and the last
   pair. The engine runs with slips off, and the text it returns must reach that highest score.
2. Refused files. The script breaks one position in a copy of the lexicon at a time, and the
   engine must refuse each broken file.
3. Version 2. The script writes a lexicon of version 2 and of version 3 from the same words and
   pairs, without triples, reading costs or pair back-off weights. Both hold the same model,
   and the engine must return a text of the highest score for both.

Usage, from the repository root, after building Engine/duo_cli.c:
    python3 scripts/typing-engine-check/check_back_off_model.py [--cli build/engine/duo_cli]

The script writes its files to build/typing-engine-check/ and exits with status 1 on a failed check.
"""
import argparse
import random
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "typing-engine"))
from lexicon_format import (  # noqa: E402
    MODEL_BACK_OFF, PAIR_STEPS, TRIPLE_STEPS, write_lexicon, write_lexicon_with_triples)

OUTPUT = ROOT / "build" / "typing-engine-check"
SPELLINGS = ["a", "b", "ab", "ba", "aba", "bab", "abb", "c", "ca", "ac", "bc", "cab"]
# Settings that leave only exact readings: no slips, and no letters kept as typed.
EXACT = ["short_word_budget=0", "long_word_budget=0", "unknown_letter=-1000", "beam=64"]


def float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def make_model(generator: random.Random, with_triples: bool):
    """Random words, pairs and triples. Returns the three tables as the writer takes them."""
    texts = [f"w{index}" for index in range(40)]
    own = {text: generator.uniform(-9.0, -2.0) for text in texts}
    back_off = {text: generator.choice([0.0, generator.uniform(-3.0, -0.1)]) for text in texts}
    words = []
    for text in texts:
        spellings = generator.sample(SPELLINGS, 2 if with_triples and generator.random() < 0.3 else 1)
        costs = [0.0] if len(spellings) == 1 else [-0.1, generator.uniform(-6.0, -1.0)]
        for spelling, cost in zip(spellings, costs):
            words.append((spelling, text, own[text] + cost, back_off[text], cost))
    pairs = {}
    for first in texts:
        for second in generator.sample(texts, 12):
            weight = generator.choice([0.0, generator.uniform(-4.0, -0.1)]) if with_triples else 0.0
            pairs[(first, second)] = (generator.uniform(-7.0, -0.05), weight)
    triples = {}
    if with_triples:
        for first, second in generator.sample(sorted(pairs), len(pairs) // 2):
            for third in generator.sample(texts, generator.choice([1, 1, 2, 5, 12])):
                triples[(first, second, third)] = generator.uniform(-6.0, -0.01)
    return words, pairs, triples


class Reference:
    """The back-off model in Python, with the pair and triple values on the steps of the file."""

    def __init__(self, words, pairs, triples):
        self.by_spelling: dict[str, list] = {}
        for word in words:
            self.by_spelling.setdefault(word[0], []).append(word)
        self.pair_value = {key: -round(-value * PAIR_STEPS) / PAIR_STEPS for key, (value, _) in pairs.items()}
        self.pair_weight = {key: round(weight * PAIR_STEPS) / PAIR_STEPS for key, (_, weight) in pairs.items()}
        self.triple_value = {key: -round(-value * TRIPLE_STEPS) / TRIPLE_STEPS for key, value in triples.items()}

    def word_score(self, before, previous, word) -> tuple[float, bool]:
        """The log probability of a word after the two words before it, and whether a triple gave it."""
        _, text, own, _, cost = word
        if previous is None:
            return float32(own), False
        penalty = 0.0
        if before is not None:
            if (before[1], previous[1], text) in self.triple_value:
                return self.triple_value[(before[1], previous[1], text)] + float32(cost), True
            penalty = self.pair_weight.get((before[1], previous[1]), 0.0)
        if (previous[1], text) in self.pair_value:
            return penalty + self.pair_value[(previous[1], text)] + float32(cost), False
        return penalty + float32(previous[3]) + float32(own), False

    def end_score(self, before, previous) -> float:
        weight = float32(previous[3])
        if before is not None:
            weight += self.pair_weight.get((before[1], previous[1]), 0.0)
        return weight

    def best(self, typed: str, text: str | None = None):
        """The highest score of a reading of `typed`, and whether that reading holds a listed triple.

        With `text`, only the readings that give this text count. Returns None when there is
        no such reading.
        """
        # One table per typed position. A key holds the two last words of a reading and how
        # much of `text` the reading gave.
        tables: list[dict] = [{} for _ in range(len(typed) + 1)]
        tables[0][(None, None, 0)] = (0.0, False)
        for position in range(len(typed)):
            for (before, previous, given), (score, has_triple) in tables[position].items():
                for end in range(position + 1, len(typed) + 1):
                    for word in self.by_spelling.get(typed[position:end], []):
                        if text is not None and not text.startswith(word[1], given):
                            continue
                        value, from_triple = self.word_score(before, previous, word)
                        key = (previous, word, given + len(word[1]))
                        if key not in tables[end] or score + value > tables[end][key][0]:
                            tables[end][key] = (score + value, has_triple or from_triple)
        ends = [
            (score + self.end_score(before, previous), has_triple)
            for (before, previous, given), (score, has_triple) in tables[len(typed)].items()
            if text is None or given == len(text)
        ]
        return max(ends) if ends else None


def run(cli: Path, lexicon: Path, typed: list[str]) -> list[str]:
    lines = "".join(f"{index}\t{text}\n" for index, text in enumerate(typed))
    done = subprocess.run([str(cli), "pinyin", str(lexicon), *EXACT], input=lines, capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise SystemExit(f"FAILED: the engine stopped on {lexicon.name}: {done.stderr.strip()}")
    return [line.split("\t", 1)[1] for line in done.stdout.splitlines()]


def check_scores(cli: Path, lexicon: Path, words, pairs, triples, generator: random.Random, count: int) -> int:
    reference = Reference(words, pairs, triples)
    typed = ["".join(generator.choice(SPELLINGS) for _ in range(generator.randint(1, 5))) for _ in range(count)]
    outputs = run(cli, lexicon, typed)
    wrong = 0
    with_triple = 0
    for text, output in zip(typed, outputs):
        best, has_triple = reference.best(text)
        with_triple += has_triple
        reached = reference.best(text, output)
        if reached is None or reached[0] < best - 1e-3:
            wrong += 1
            if wrong <= 5:
                print(f"    {text!r}: the engine gave {output!r} with score {reached and reached[0]}, and the highest score is {best}")
    print(f"  {lexicon.name}: {len(typed) - wrong} of {len(typed)} outputs reach the highest score; "
          f"the best reading holds a listed triple in {with_triple} of them")
    return wrong


def check_refused(cli: Path, lexicon: Path) -> int:
    data = lexicon.read_bytes()
    _, _, nodes, words, _, pairs, _, contexts, triples, _ = struct.unpack_from("<10I", data, 0)
    pair_table = 40 + nodes * 12 + words * 16 + (words + 1) * 4
    context_table = pair_table + pairs * 8
    triple_table = context_table + (contexts + 1) * 8
    first_context_pair = pair_table + 8 * struct.unpack_from("<I", data, context_table)[0]
    breaks = {
        "a pair's second word past the last word": (pair_table, struct.pack("<I", words)),
        "a context row's pair past the last pair": (context_table, struct.pack("<I", pairs)),
        "a context row's first triple past the last triple": (context_table + 8 * (contexts // 2) + 4, struct.pack("<I", triples + 1)),
        "context rows out of order": (context_table + 8, struct.pack("<I", 0)),
        "a closing row with a wrong triple count": (context_table + 8 * contexts + 4, struct.pack("<I", triples - 1)),
        "a triple's third word past the last word": (triple_table + 4 * (triples // 2), struct.pack("<I", (1 << 20) - 1)),
        "a context row whose pair lacks the mark of a pair that opens triples": (
            first_context_pair, struct.pack("<I", struct.unpack_from("<I", data, first_context_pair)[0] & 0x7FFFFFFF)),
        "a file that ends 4 bytes early": (None, None),
    }
    wrong = 0
    for name, (offset, value) in breaks.items():
        broken = bytearray(data)
        if offset is None:
            broken = broken[:-4]
        else:
            broken[offset:offset + len(value)] = value
        path = OUTPUT / "broken.bin"
        path.write_bytes(broken)
        done = subprocess.run([str(cli), "pinyin", str(path)], input="0\tab\n", capture_output=True, text=True, encoding="utf-8")
        refused = done.returncode == 1 and "not a valid lexicon file" in done.stderr
        print(f"  {name}: {'refused' if refused else 'NOT refused'}")
        wrong += not refused
    return wrong


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", type=Path, default=ROOT / "build" / "engine" / "duo_cli")
    parser.add_argument("--cases", type=int, default=300)
    arguments = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    generator = random.Random(20261109)
    failures = 0

    print("1. Scores of a lexicon with triples")
    for round_index in range(3):
        words, pairs, triples = make_model(generator, with_triples=True)
        lexicon = OUTPUT / f"triples-{round_index}.bin"
        stats = write_lexicon_with_triples(lexicon, words, pairs, triples, MODEL_BACK_OFF)
        print(f"  {lexicon.name}: {stats}")
        failures += check_scores(arguments.cli, lexicon, words, pairs, triples, generator, arguments.cases)

    print("2. Broken files")
    failures += check_refused(arguments.cli, OUTPUT / "triples-0.bin")

    print("3. The same pair model in version 2 and in version 3")
    words, pairs, _ = make_model(generator, with_triples=False)
    # Pair values on the steps of version 3, so both files hold the same numbers.
    pairs = {key: (-round(-value * PAIR_STEPS) / PAIR_STEPS, 0.0) for key, (value, _) in pairs.items()}
    version_2 = OUTPUT / "pairs-version-2.bin"
    version_3 = OUTPUT / "pairs-version-3.bin"
    write_lexicon(version_2, [word[:4] for word in words], {key: value for key, (value, _) in pairs.items()}, MODEL_BACK_OFF)
    write_lexicon_with_triples(version_3, words, pairs, {}, MODEL_BACK_OFF)
    for lexicon in (version_2, version_3):
        failures += check_scores(arguments.cli, lexicon, words, pairs, {}, random.Random(7), arguments.cases)

    if failures:
        print(f"FAILED: {failures} checks")
        raise SystemExit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()

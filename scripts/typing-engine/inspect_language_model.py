"""Prints what the libime language model says about given word sequences.

The script answers one question: which reading of some typed Pinyin does the language model
prefer, and by how much. For each word sequence it prints the lines of lm_sc.arpa that a
back-off model reads, the lines of dict_sc.txt for the words, and the score of the sequence
under two models:
- the triple model: a word's chance given the two words before it, as an ARPA back-off model
  defines it. This is the model libime uses.
- the pair model: a word's chance given one word before it, from the same file.

All scores are base-10 logs, as in the file. The first word of a sequence has no word before
it, which is how libime starts a sentence with this model.

With --counts in place of the sequences, the script prints counts over the whole model: how many
pairs carry a back-off weight, how many pairs open a triple, and the range of every value. The
lexicon format stores the pair and triple values in a few bits, and these ranges show that the
values fit.

Usage, from the repository root, on a machine that holds the unpacked files:
    python3 scripts/typing-engine/inspect_language_model.py FOLDER "我 恨 他" "我 很 他"
    python3 scripts/typing-engine/inspect_language_model.py FOLDER --counts
"""
import sys
from collections import Counter
from pathlib import Path


def print_counts(path: Path):
    section = 0
    listed = [0, 0, 0, 0]
    low = [float("inf")] * 4
    high = [float("-inf")] * 4
    back_off_low = [float("inf")] * 4
    back_off_high = [float("-inf")] * 4
    with_back_off = [0, 0, 0, 0]
    triples_per_pair: Counter = Counter()
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            line = line.rstrip("\n")
            if line.startswith("\\"):
                section = {"\\1-grams:": 1, "\\2-grams:": 2, "\\3-grams:": 3}.get(line, 0)
                continue
            if section == 0:
                continue
            fields = line.split("\t")
            if len(fields) < 2:
                continue
            value = float(fields[0])
            listed[section] += 1
            low[section] = min(low[section], value)
            high[section] = max(high[section], value)
            if len(fields) > 2:
                back_off = float(fields[2])
                if back_off != 0.0:
                    with_back_off[section] += 1
                back_off_low[section] = min(back_off_low[section], back_off)
                back_off_high[section] = max(back_off_high[section], back_off)
            if section == 3:
                triples_per_pair[fields[1].rsplit(" ", 1)[0]] += 1
    for size in (1, 2, 3):
        print(f"{size}-word entries: {listed[size]}, log10 p from {low[size]} to {high[size]}, "
              f"{with_back_off[size]} with a back-off weight other than 0, from {back_off_low[size]} to {back_off_high[size]}")
    print(f"pairs that open one or more triples: {len(triples_per_pair)}")
    sizes = Counter(min(count, 10) for count in triples_per_pair.values())
    print("pairs by their count of triples (10 stands for 10 or more): " + ", ".join(f"{size}: {sizes[size]}" for size in sorted(sizes)))
    print(f"the most triples behind one pair: {max(triples_per_pair.values())}")


def collect(path: Path, wanted: set[str]):
    """Reads the file once. Returns the header lines and the wanted entries by their words."""
    header = []
    found: dict[str, tuple[float, float | None]] = {}
    in_header = True
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            if in_header:
                line = line.rstrip("\n")
                if line.startswith("ngram "):
                    header.append(line)
                elif line.endswith("-grams:"):
                    in_header = False
                continue
            first_tab = line.find("\t")
            if first_tab < 0:
                continue
            second_tab = line.find("\t", first_tab + 1)
            words = line[first_tab + 1:second_tab] if second_tab >= 0 else line[first_tab + 1:].rstrip("\n")
            if words in wanted:
                back_off = float(line[second_tab + 1:]) if second_tab >= 0 else None
                found[words] = (float(line[:first_tab]), back_off)
    return header, found


def show(found, words: str) -> str:
    if words not in found:
        return f"    {words}: not listed"
    log_probability, back_off = found[words]
    return f"    {words}: log10 p = {log_probability}" + (f", back-off = {back_off}" if back_off is not None else "")


def back_off_of(found, words: str) -> float:
    entry = found.get(words)
    return entry[1] if entry is not None and entry[1] is not None else 0.0


def score(found, sequence: list[str], order: int):
    """The score of the sequence and one line of explanation per word."""
    total = 0.0
    steps = []
    for index, word in enumerate(sequence):
        history = sequence[max(0, index - order + 1):index]
        penalty = 0.0
        terms = []
        while True:
            key = " ".join(history + [word])
            if key in found:
                value = found[key][0] + penalty
                terms.append(f"p({key}) {found[key][0]}")
                break
            if not history:
                raise SystemExit(f"the language model does not list the word {word!r}")
            weight = back_off_of(found, " ".join(history))
            penalty += weight
            terms.append(f"back-off({' '.join(history)}) {weight}")
            history = history[1:]
        total += value
        steps.append(f"      {word}: {value:.4f} = " + " + ".join(terms))
    return total, steps


def main():
    folder = Path(sys.argv[1])
    if sys.argv[2:] == ["--counts"]:
        print_counts(folder / "lm_sc.arpa")
        return
    sequences = [argument.split() for argument in sys.argv[2:] if argument.strip()]
    wanted = set()
    for sequence in sequences:
        for size in (1, 2, 3):
            for start in range(len(sequence) - size + 1):
                wanted.add(" ".join(sequence[start:start + size]))
    header, found = collect(folder / "lm_sc.arpa", wanted)
    print("language model header:")
    for line in header:
        print("    " + line)

    words = sorted({word for sequence in sequences for word in sequence})
    readings: dict[str, list[str]] = {word: [] for word in words}
    for line in (folder / "dict_sc.txt").read_text(encoding="utf-8").splitlines():
        text = line.split(maxsplit=1)[0] if line else ""
        if text in readings:
            readings[text].append(line)
    print("dictionary lines (word, Pinyin, log10 share of the reading):")
    for word in words:
        print(f"    {word}: " + (" | ".join(readings[word]) if readings[word] else "not listed"))

    for sequence in sequences:
        print("sequence: " + " ".join(sequence))
        for size in (1, 2, 3):
            for start in range(len(sequence) - size + 1):
                print(show(found, " ".join(sequence[start:start + size])))
        for name, order in (("triple model", 3), ("pair model", 2)):
            total, steps = score(found, sequence, order)
            print(f"    {name}: log10 = {total:.4f}, natural log = {total * 2.302585093:.4f}")
            for step in steps:
                print(step)


if __name__ == "__main__":
    main()

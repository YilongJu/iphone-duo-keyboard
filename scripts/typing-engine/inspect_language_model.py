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

Usage, from the repository root, on a machine that holds the unpacked files:
    python3 scripts/typing-engine/inspect_language_model.py FOLDER "我 恨 他" "我 很 他"
"""
import sys
from pathlib import Path


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

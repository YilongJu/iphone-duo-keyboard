"""Checks whether the Pinyin engine offers the names and terms of terms.tsv.

For each term the script types the term's Pinyin into the engine (Engine/duo_cli.c, mode pinyin
with candidates=COUNT) and looks for the term among the candidates. The first candidate is the
text that the space bar types. The candidates after it are the words the candidate row shows.

The Pinyin of a term is the third column of terms.tsv when the line has one. Without it, the
script takes the reading of the whole term from the libime dictionary (dict_sc.txt), and for a
term that the dictionary does not hold, the most frequent reading of each character.

Usage, from the repository root, on Linux, after building Engine/duo_cli.c into build/engine/duo_cli
and unpacking the libime dictionary into build/libime-data (see .github/workflows/pinyin-lexicon.yml):
    python3 scripts/pinyin-dictionary/new-words-check/check_terms.py --out build/new-words-check/results.tsv
"""
import argparse
import collections
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TERMS = HERE / "terms.tsv"
CANDIDATES = 52
SHOWN_FIRST = 5


def read_terms() -> list[tuple[str, str, str]]:
    """The lines of terms.tsv as group, term and the given Pinyin (or an empty string)."""
    terms = []
    seen = set()
    for number, line in enumerate(TERMS.read_text(encoding="utf-8").splitlines(), start=1):
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) not in (2, 3) or not all(fields):
            raise SystemExit(f"{TERMS.name}:{number}: a line holds a group, a term and an optional Pinyin: {line!r}")
        if fields[1] in seen:
            raise SystemExit(f"{TERMS.name}:{number}: {fields[1]} is in the file twice")
        seen.add(fields[1])
        terms.append((fields[0], fields[1], fields[2] if len(fields) == 3 else ""))
    return terms


def read_dictionary(path: Path) -> dict[str, str]:
    """A reading of each word and character of dict_sc.txt, without apostrophes. A word gets
    its reading with the highest share. A character gets the reading that it has in the most
    words of the dictionary, as "nan" for the character of "south"."""
    best: dict[str, tuple[float, str]] = {}
    uses: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) == 2:
            fields.append("0")
        if len(fields) != 3:
            raise SystemExit(f"unexpected dictionary line: {line!r}")
        text, syllables, share = fields[0], fields[1].split("'"), float(fields[2])
        if len(text) >= 2:
            if text not in best or share > best[text][0]:
                best[text] = (share, "".join(syllables))
            if len(syllables) == len(text):
                for character, syllable in zip(text, syllables):
                    uses[character][syllable] += 1
        else:
            # A character that no word holds keeps the reading of its own line.
            uses[text][syllables[0]] += 0
    readings = {text: pinyin for text, (_, pinyin) in best.items()}
    for character, counts in uses.items():
        readings[character] = max(sorted(counts), key=lambda syllable: counts[syllable])
    return readings


def pinyin_of(term: str, given: str, readings: dict[str, str]) -> str:
    if given:
        return given
    if term in readings:
        return readings[term]
    missing = [character for character in term if character not in readings]
    if missing:
        raise SystemExit(f"{term}: the dictionary has no reading of {''.join(missing)}. Give the Pinyin in terms.tsv.")
    return "".join(readings[character] for character in term)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", type=Path, default=ROOT / "build" / "engine" / "duo_cli")
    parser.add_argument("--lexicon", type=Path, default=ROOT / "Shared" / "lexicon-pinyin.bin")
    parser.add_argument("--dictionary", type=Path, default=ROOT / "build" / "libime-data" / "dict_sc.txt")
    parser.add_argument("--out", type=Path, required=True, help="the result file, one line per term")
    arguments = parser.parse_args()

    terms = read_terms()
    readings = read_dictionary(arguments.dictionary)
    typed = [pinyin_of(term, given, readings) for _, term, given in terms]
    lines = "".join(f"{index}\t{letters}\n" for index, letters in enumerate(typed))
    completed = subprocess.run(
        [str(arguments.cli), "pinyin", str(arguments.lexicon), f"candidates={CANDIDATES}"],
        input=lines, capture_output=True, text=True, encoding="utf-8", check=True)
    answers = dict(line.split("\t", 1) for line in completed.stdout.splitlines())

    rows = ["group\tterm\ttyped\tplace among the candidates (0: not offered)\tfirst candidate"]
    counts: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0, 0, 0])
    for index, (group, term, _) in enumerate(terms):
        candidates = []
        for item in answers.get(str(index), "").split(" "):
            text, _, consumed = item.rpartition("/")
            # Only a candidate that covers all the typed letters types the whole term.
            if text and int(consumed) == len(typed[index]):
                candidates.append(text)
        place = candidates.index(term) + 1 if term in candidates else 0
        first = answers.get(str(index), "").split(" ")[0].rpartition("/")[0]
        rows.append(f"{group}\t{term}\t{typed[index]}\t{place}\t{first}")
        for name in (group, "all terms"):
            counts[name][0] += 1
            counts[name][1] += place == 1
            counts[name][2] += 1 <= place <= SHOWN_FIRST
            counts[name][3] += place >= 1
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text("\n".join(rows) + "\n", encoding="utf-8")

    print(f"{'group':28} terms  first  first {SHOWN_FIRST}  offered")
    for name, (total, first, shown, offered) in counts.items():
        print(f"{name:28} {total:5d}  {first:5d}  {shown:7d}  {offered:7d}")
    print(f"wrote {arguments.out}")


if __name__ == "__main__":
    main()

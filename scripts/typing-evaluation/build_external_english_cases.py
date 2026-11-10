"""Builds English cases from published misspelling lists, as a check that does not use our own slip generator.

Source: Roger Mitton's spelling-error files, https://www.dcs.bbk.ac.uk/~ROGER/corpora.html
(Birkbeck, Holbrook and Aspell). The page does not state a license, so the script fetches the
files when it runs and writes the cases to build/typing-evaluation/external/, which git ignores.
The cases stay out of the repository.

These lists hold spelling mistakes that people made on paper and on desktop keyboards. They are
not phone slips, and the engine's word list does not use them, which is the point: a score here
does not depend on any choice in our generator.

A case is kept when the wrong form and the right word are plain lower-case words, the wrong form
is at most two edits from the right word, the right word is common (Zipf 3.5 or more) and the
wrong form is not itself a common word (Zipf under 3). A right word goes to the dev half or the
test half by a hash of the word.

Usage, from the repository root:
    uv run --with wordfreq python scripts/typing-evaluation/build_external_english_cases.py
"""
import json
import random
import urllib.request
import zlib
from pathlib import Path

from wordfreq import zipf_frequency

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "build" / "typing-evaluation" / "mitton"
OUTPUT = ROOT / "build" / "typing-evaluation" / "external"
BASE_URL = "https://www.dcs.bbk.ac.uk/~ROGER/"
SOURCES = {"birkbeck": "missp.dat", "holbrook": "holbrook-missp.dat", "aspell": "aspell.dat"}
CASES_PER_SOURCE = 300
SEED = 20261110


def edits(first: str, second: str) -> int:
    """Edit distance where a swap of two neighbors counts as one edit."""
    table = [[0] * (len(second) + 1) for _ in range(len(first) + 1)]
    for i in range(len(first) + 1):
        table[i][0] = i
    for j in range(len(second) + 1):
        table[0][j] = j
    for i in range(1, len(first) + 1):
        for j in range(1, len(second) + 1):
            cost = first[i - 1] != second[j - 1]
            table[i][j] = min(table[i - 1][j] + 1, table[i][j - 1] + 1, table[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and first[i - 1] == second[j - 2] and first[i - 2] == second[j - 1]:
                table[i][j] = min(table[i][j], table[i - 2][j - 2] + 1)
    return table[-1][-1]


def read_pairs(name: str) -> list[tuple[str, str]]:
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(BASE_URL + name, headers={"User-Agent": "duo-keyboard-build/1.0"})
        with urllib.request.urlopen(request) as response:
            path.write_bytes(response.read())
    pairs = []
    right = None
    for line in path.read_text(encoding="latin-1").splitlines():
        line = line.strip()
        if line.startswith("$"):
            right = line[1:].lower()
        elif line and right is not None:
            # The Holbrook file puts a count after the wrong form.
            pairs.append((line.split()[0].lower(), right))
    return pairs


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    halves = {"dev": [], "test": []}
    for source, name in SOURCES.items():
        kept = {"dev": [], "test": []}
        for wrong, right in sorted(set(read_pairs(name))):
            if not (wrong.isalpha() and right.isalpha() and wrong.isascii() and right.isascii()) or wrong == right:
                continue
            if zipf_frequency(right, "en") < 3.5 or zipf_frequency(wrong, "en") >= 3.0 or edits(wrong, right) > 2:
                continue
            half = "dev" if zlib.crc32(right.encode()) % 2 == 0 else "test"
            kept[half].append((wrong, right))
        for half, pairs in kept.items():
            rng = random.Random(f"{SEED}-{source}-{half}")
            for number, (wrong, right) in enumerate(rng.sample(pairs, min(CASES_PER_SOURCE, len(pairs)))):
                halves[half].append({
                    "id": f"en-{half}-real_misspelling_{source}-{number:04d}", "split": half,
                    "category": f"real_misspelling_{source}", "context": "", "typed": wrong, "intended": right,
                    "source": f"mitton:{name}",
                })
            print(f"{source} {half}: {min(CASES_PER_SOURCE, len(pairs))} of {len(pairs)} usable pairs")
    for half, cases in halves.items():
        path = OUTPUT / f"english.{half}.jsonl"
        path.write_text("".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}: {len(cases)} cases")


if __name__ == "__main__":
    main()

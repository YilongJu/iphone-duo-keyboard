"""Draws the precision sample of Shared/emoji-suggestions.tsv, and counts its judgments.

A pair is one word with one of its emoji. The sample of a language is the pairs with the
smallest SHA-256 of the seed, the language, the word and the emoji. The same seed gives the
same sample for the same table. A change to the table changes only the pairs that the change
touches.

A person judges each pair of the sample as good, acceptable or bad, and writes the judgment
into judged-<language>.tsv beside this script: word, tab, emoji, tab, judgment.

Usage:
    python scripts/emoji-table/precision-sample/sample_pairs.py
        Prints the sample of each language: word, tab, emoji.
    python scripts/emoji-table/precision-sample/sample_pairs.py --check
        Checks that the judged files hold exactly the sample, and prints the counts.
Options: --seed, --count and --table choose another seed, sample size or table file.
"""

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
TABLE = ROOT / "Shared" / "emoji-suggestions.tsv"
SEED = "20261120"
COUNT = 300
LANGUAGES = ("en", "zh")
JUDGMENTS = ("good", "acceptable", "bad")


def sample(table, language, seed, count):
    """The pairs of the language with the smallest hashes, in the order of the hashes."""
    pairs = []
    for line in table.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        line_language, word, emoji_text = line.split("\t")
        if line_language == language:
            pairs += [(word, emoji) for emoji in emoji_text.split(" ")]
    if len(pairs) < count:
        sys.exit(f"{language}: the table holds {len(pairs)} pairs, fewer than the sample of {count}")

    def key(pair):
        return hashlib.sha256(f"{seed}\t{language}\t{pair[0]}\t{pair[1]}".encode("utf-8")).hexdigest()
    return sorted(pairs, key=key)[:count]


def judged(language):
    """The judged pairs of the language, as {(word, emoji): judgment}."""
    path = HERE / f"judged-{language}.tsv"
    judgments = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 3 or fields[2] not in JUDGMENTS or (fields[0], fields[1]) in judgments:
            sys.exit(f"{path.name}:{number}: a line holds a word, an emoji and one of {JUDGMENTS}, and each pair once")
        judgments[(fields[0], fields[1])] = fields[2]
    return judgments


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", default=SEED)
    parser.add_argument("--count", type=int, default=COUNT)
    parser.add_argument("--table", type=Path, default=TABLE)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    for language in LANGUAGES:
        pairs = sample(arguments.table, language, arguments.seed, arguments.count)
        if not arguments.check:
            for word, emoji in pairs:
                print(f"{language}\t{word}\t{emoji}")
            continue
        judgments = judged(language)
        missing = [pair for pair in pairs if pair not in judgments]
        extra = [pair for pair in judgments if pair not in set(pairs)]
        if missing or extra:
            sys.exit(f"judged-{language}.tsv does not hold the sample of seed {arguments.seed}: "
                     f"{len(missing)} pairs without a judgment {missing[:5]}, "
                     f"{len(extra)} pairs outside the sample {extra[:5]}")
        counts = {judgment: sum(1 for value in judgments.values() if value == judgment) for judgment in JUDGMENTS}
        bad = 100 * counts["bad"] / len(pairs)
        print(f"{language}: {len(pairs)} pairs, {counts['good']} good, {counts['acceptable']} acceptable, "
              f"{counts['bad']} bad ({bad:.1f}% bad)")


if __name__ == "__main__":
    main()

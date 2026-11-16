"""Builds Shared/emoji-suggestions.tsv, the table of emoji that the keyboard offers for a word.

The table holds a word and at most two emoji for each word, for English and for Chinese. The
words and their emoji are chosen by hand in chosen-en.tsv and chosen-zh.tsv. This script checks
every chosen pair against three sources and stops at the first pair that fails a check:

1. The Unicode CLDR emoji annotations, version 49.0.0 (cldr-json package cldr-annotations-full).
   Each chosen word must be a keyword of its emoji, or a word of the emoji's spoken name, in the
   annotations of its language. Unicode License v3: https://www.unicode.org/license.txt
2. The Unicode emoji frequency ranking, https://home.unicode.org/emoji/emoji-frequency/ (page of
   2022). Each chosen emoji must be among the most used emoji: rank FREQUENCY_LIMIT or better.
3. A word frequency list. Each English word must be among the ENGLISH_WORD_LIMIT most frequent
   words of SymSpell's frequency_dictionary_en_82_765.txt (MIT license), the list that the English
   lexicon is built from. Each Chinese word must be among the CHINESE_WORD_LIMIT most frequent
   words of Shared/pinyin-dictionary.txt.

The script downloads the sources into build/emoji-table/ and checks each file's SHA-256, so a
changed source stops the build.

Usage:
    python scripts/emoji-table/build_emoji_table.py
        Checks the chosen pairs and writes Shared/emoji-suggestions.tsv.
    python scripts/emoji-table/build_emoji_table.py --candidates en good happy
        Prints every emoji whose annotations name each word, most used first, as help for the choice.
"""

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CACHE = ROOT / "build" / "emoji-table"
OUTPUT = ROOT / "Shared" / "emoji-suggestions.tsv"
PINYIN_DICTIONARY = ROOT / "Shared" / "pinyin-dictionary.txt"

CLDR_VERSION = "49.0.0"
SOURCES = {
    "cldr-en.json":
        f"https://cdn.jsdelivr.net/npm/cldr-annotations-full@{CLDR_VERSION}/annotations/en/annotations.json",
    "cldr-zh.json":
        f"https://cdn.jsdelivr.net/npm/cldr-annotations-full@{CLDR_VERSION}/annotations/zh/annotations.json",
    "emoji-frequency.html": "https://home.unicode.org/emoji/emoji-frequency/",
    "symspell-en.txt":
        "https://raw.githubusercontent.com/wolfgarbe/SymSpell/master/SymSpell/frequency_dictionary_en_82_765.txt",
}
HASHES_FILE = HERE / "source-hashes.json"

FREQUENCY_LIMIT = 700
ENGLISH_WORD_LIMIT = 30000
CHINESE_WORD_LIMIT = 10000
MAX_EMOJI_PER_WORD = 2
# Chat words that SymSpell's list does not hold. The check of the word frequency accepts these
# by name. CLDR still has to annotate each chosen emoji with the word.
CHAT_WORDS = {"lol", "haha", "omg", "idk"}

VARIATION_SELECTOR = "️"


def fetch(name):
    """The bytes of one source file, from the cache or the network, checked against its hash."""
    url = SOURCES[name]
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.exists():
        request = urllib.request.Request(url, headers={"User-Agent": "emoji-table-build"})
        with urllib.request.urlopen(request) as response:
            path.write_bytes(response.read())
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    hashes = json.loads(HASHES_FILE.read_text(encoding="utf-8"))
    if hashes.get(name) != digest:
        sys.exit(f"{name}: SHA-256 {digest} differs from source-hashes.json ({hashes.get(name)}). "
                 f"Check the new file, then write its hash into source-hashes.json.")
    return data


def frequency_ranking():
    """The emoji of the frequency page, most used first. The page lists the emoji in table rows."""
    page = fetch("emoji-frequency.html").decode("utf-8")
    ranking = []
    for row in re.findall(r"<tr.*?</tr>", page, re.S):
        cells = re.findall(r"<td.*?</td>", row, re.S)
        if len(cells) < 2:
            continue
        text = html.unescape(re.sub(r"<[^>]+>", " ", cells[1]))
        ranking += [item for item in text.split() if item != "…"]
    if len(ranking) < 1000 or ranking[0] != "\U0001F602":
        sys.exit(f"The frequency page did not parse: {len(ranking)} emoji, first {ranking[:1]}")
    return ranking


def annotations(language):
    data = json.loads(fetch(f"cldr-{language}.json").decode("utf-8"))
    return data["annotations"]["annotations"]


def word_ranks(language):
    """Rank of each word in the frequency list of the language, 0 for the most frequent."""
    if language == "en":
        counts = {}
        for line in fetch("symspell-en.txt").decode("utf-8").splitlines():
            word, count = line.split()
            counts[word] = int(count)
    else:
        counts = {}
        for line in PINYIN_DICTIONARY.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                sys.exit(f"pinyin-dictionary.txt: unexpected line {line!r}")
            counts[parts[1]] = max(counts.get(parts[1], 0.0), float(parts[2]))
    ordered = sorted(counts, key=lambda word: (-counts[word], word))
    return {word: rank for rank, word in enumerate(ordered)}


def names_of(entry):
    """The keywords of an annotation entry and the words of its spoken names."""
    names = set(entry["default"]) | set(entry["tts"])
    for spoken in entry["tts"]:
        names |= set(spoken.split())
    return names


def candidates(language, word, ranking, notes):
    """Every emoji of the ranking whose annotations name `word`, most used first."""
    found = []
    for emoji in ranking:
        entry = notes.get(emoji.replace(VARIATION_SELECTOR, "")) or notes.get(emoji)
        if entry and word in names_of(entry):
            found.append(emoji)
    return found


def read_chosen(language):
    path = HERE / f"chosen-{language}.tsv"
    chosen = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            sys.exit(f"{path.name}:{number}: a line holds a word, a tab and its emoji: {line!r}")
        word, emoji_text = parts
        emoji = emoji_text.split(" ")
        if word in chosen:
            sys.exit(f"{path.name}:{number}: {word} is in the file twice")
        if not 1 <= len(emoji) <= MAX_EMOJI_PER_WORD or len(set(emoji)) != len(emoji):
            sys.exit(f"{path.name}:{number}: {word} needs one or two different emoji")
        chosen[word] = emoji
    return chosen


def check(language, chosen, ranking):
    notes = annotations(language)
    ranks = word_ranks(language)
    position = {emoji: index for index, emoji in enumerate(ranking)}
    limit = ENGLISH_WORD_LIMIT if language == "en" else CHINESE_WORD_LIMIT
    errors = []
    for word, emoji_list in chosen.items():
        if language == "en" and not re.fullmatch(r"[a-z]+", word):
            errors.append(f"en: {word!r} is not a lower-case word of letters")
        if ranks.get(word, limit) >= limit and not (language == "en" and word in CHAT_WORDS):
            errors.append(f"{language}: {word} is not among the {limit} most frequent words")
        for emoji in emoji_list:
            if position.get(emoji, FREQUENCY_LIMIT) >= FREQUENCY_LIMIT:
                errors.append(f"{language}: {word} {emoji}: the emoji is not among the {FREQUENCY_LIMIT} most used")
            entry = notes.get(emoji.replace(VARIATION_SELECTOR, "")) or notes.get(emoji)
            if entry is None or word not in names_of(entry):
                found = " ".join(candidates(language, word, ranking[:FREQUENCY_LIMIT], notes)) or "none"
                errors.append(f"{language}: {word} {emoji}: CLDR {CLDR_VERSION} does not annotate the emoji "
                              f"with the word. Annotated: {found}")
    if errors:
        sys.exit("\n".join(errors))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", nargs="+", metavar=("LANGUAGE", "WORD"))
    parser.add_argument("--languages", nargs="+", default=["en", "zh"], help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    ranking = frequency_ranking()
    if arguments.candidates:
        language, *words = arguments.candidates
        notes = annotations(language)
        ranks = word_ranks(language)
        for word in words:
            found = candidates(language, word, ranking[:FREQUENCY_LIMIT], notes)
            print(f"{word}\trank {ranks.get(word, 'none')}\t{' '.join(found)}")
        return
    lines = [
        "# Emoji that the keyboard offers for a word. Built by scripts/emoji-table/build_emoji_table.py",
        f"# from the Unicode CLDR {CLDR_VERSION} emoji annotations (Unicode License v3) and the Unicode",
        "# emoji frequency ranking. docs/emoji-suggestions.md describes the table.",
        "# Unicode data: Copyright (c) 1991-2026 Unicode, Inc. License: https://www.unicode.org/license.txt",
        "# Columns: language, word, emoji separated by one space.",
    ]
    counts = {}
    for language in arguments.languages:
        chosen = read_chosen(language)
        check(language, chosen, ranking)
        for word in sorted(chosen):
            lines.append(f"{language}\t{word}\t{' '.join(chosen[word])}")
        counts[language] = (len(chosen), len({e for emoji in chosen.values() for e in emoji}))
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    for language, (words, emoji) in counts.items():
        print(f"{language}: {words} words, {emoji} different emoji")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

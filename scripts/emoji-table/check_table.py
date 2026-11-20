"""Checks Shared/emoji-suggestions.tsv against the rules of its reader and of the tests.

The reader is `EmojiSuggestions.init(table:)` in Shared/EmojiSuggestions.swift. A line that
breaks its rules stops the app, so this script stops at the first such line:
1. A line is a note that starts with "#", or holds three fields with a tab between them.
2. The first field is the language "en" or "zh".
3. The second field is a word. The word is not empty, and each language holds a word once.
4. The third field holds one or two emoji with one space between them.
The script also checks that an English word is in lower-case letters, that each emoji is a
fully-qualified emoji of emoji-test.txt, and that the two emoji of a word differ.

The tests type some words and expect fixed emoji, or none. The script checks those words too:
Tests/EmojiSuggestionTests.swift, Tests/TopRowEmojiTests.swift, Tests/PredictionStripTests.swift
and Tests/ModelPredictedWordsTests.swift.

Usage:
    python scripts/emoji-table/check_table.py [TABLE]
"""

import re
import sys
from pathlib import Path

import build_emoji_table as build

TABLE = build.OUTPUT
# The words that the tests type, with the emoji that the tests expect.
EXPECTED = {
    ("en", "good"): ["\U0001F44D", "\U0001F44F"],
    ("en", "office"): ["\U0001F4BB"],
    ("zh", "好"): ["\U0001F44D"],
    ("zh", "你好"): ["\U0001F44B"],
}
# The words that the tests type and expect without emoji. The Chinese words are the first
# candidates of the test dictionary in Tests/KeyboardTextControllerTests.swift.
WITHOUT_EMOJI = {
    "en": ["the", "xyz", "goodness", "see", "you", "use", "to", "today", "tomorrow", "teh", "tox", "nextj"],
    "zh": ["我", "你", "中国", "中", "国", "先", "们", "西", "安", "嗯", "尼", "我你好"],
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else TABLE
    allowed = {entry["text"] for entry in build.emoji_list().values()}
    tables = {"en": {}, "zh": {}}
    for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if line == "" or line.startswith("#"):
            continue
        where = f"{path.name}:{number}"
        if "\r" in line:
            sys.exit(f"{where}: the line ends with a carriage return")
        parts = line.split("\t")
        if len(parts) != 3:
            sys.exit(f"{where}: {len(parts)} fields, not 3")
        language, word, emoji_text = parts
        if language not in tables:
            sys.exit(f"{where}: unknown language {language!r}")
        if not word or word != word.strip() or " " in word:
            sys.exit(f"{where}: empty word, or a word with a space")
        if language == "en" and not re.fullmatch(r"[a-z]+", word):
            sys.exit(f"{where}: {word!r} is not in lower-case letters, so the keyboard never finds it")
        if word in tables[language]:
            sys.exit(f"{where}: {word} is in the table twice")
        emoji = emoji_text.split(" ")
        if not 1 <= len(emoji) <= build.MAX_EMOJI_PER_WORD or "" in emoji or len(set(emoji)) != len(emoji):
            sys.exit(f"{where}: {word} needs one or two different emoji with one space between them")
        for item in emoji:
            if item not in allowed:
                sys.exit(f"{where}: {word} {item!r} is not a fully-qualified emoji that the table may hold")
        tables[language][word] = emoji
    errors = []
    for (language, word), emoji in EXPECTED.items():
        if tables[language].get(word) != emoji:
            errors.append(f"{language} {word}: the tests expect {' '.join(emoji)}, the table holds {tables[language].get(word)}")
    for language, words in WITHOUT_EMOJI.items():
        for word in words:
            if word in tables[language]:
                errors.append(f"{language} {word}: the tests expect no emoji, the table holds {tables[language][word]}")
    if errors:
        sys.exit("\n".join(errors))
    for language, table in tables.items():
        pairs = sum(len(emoji) for emoji in table.values())
        different = len({item for emoji in table.values() for item in emoji})
        two = sum(1 for emoji in table.values() if len(emoji) == 2)
        print(f"{language}: {len(table)} words, {pairs} pairs, {different} different emoji, {two} words with two emoji")
    print(f"{path.name} follows the rules of the reader and of the tests")


if __name__ == "__main__":
    main()

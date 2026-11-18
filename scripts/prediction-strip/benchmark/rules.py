"""Python copies of the keyboard's rules that the benchmark of the predicted words needs
(docs/prediction-strip-benchmark-design.md). Each function names its Swift source.
check_rules.py runs the cases of the Swift unit tests against these copies.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
from rerank import PreferredCapitals, should_auto_capitalize, word_before_space  # noqa: E402,F401

BENCH = ROOT / "build" / "prediction-strip" / "bench"
CHOSEN = Path(__file__).with_name("chosen.json")

# The characters that can stand right before typed letters and before the word of an emoji:
# an opening bracket or quote (typedLetters and wordForEmoji in Shared/KeyboardTextLogic.swift).
OPENING = set("([{\"“‘")
ASCII_MARKS = set(",.?!;:)]}")
CLOSING = set(")]}\"'”’")
STRAIGHT_QUOTES = set("\"'")
EMOTICON = set(")(-'/\\|*]")
BEFORE_OPENING_SINGLE_QUOTE = set(" ([{\"")


def require_half(half: str) -> None:
    """The test halves are read once, with the chosen word order. A script that reads a half
    for a run calls this first."""
    if half not in ("dev", "test"):
        raise SystemExit(f"unknown half {half!r}")
    if half == "test" and not CHOSEN.exists():
        raise SystemExit(f"the test halves stay unread until {CHOSEN} names the chosen word order")


def is_letter_or_digit(character: str) -> bool:
    """`isLetterOrDigit`. The texts of the benchmark hold ASCII only, so no emoji reaches it."""
    return character.isalpha() or character.isnumeric()


def typed_letters(before: str, after: str) -> str | None:
    """`KeyboardTextLogic.typedLetters(before:after:)`."""
    if after and (is_letter_or_digit(after[0]) or after[0] == "'"):
        return None
    start = len(before)
    while start > 0:
        character = before[start - 1]
        if not (character.isascii() and (character.isalpha() or character == "'")):
            break
        start -= 1
    letters = before[start:]
    if not letters or not letters[0].isalpha():
        return None
    if start > 0:
        preceding = before[start - 1]
        if not (preceding.isspace() or preceding in OPENING):
            return None
    capitals = sum(1 for character in letters if character.isupper())
    only_the_first = capitals == 0 or (capitals == 1 and letters[0].isupper())
    if not (only_the_first or capitals == sum(1 for character in letters if character.isalpha())):
        return None
    return letters


def prediction_context(before: str, after: str) -> tuple[str, str] | None:
    """`KeyboardTextLogic.predictionContext(before:after:)`: the previous word and the typed letters."""
    if after and (is_letter_or_digit(after[0]) or after[0] == "'"):
        return None
    typed = typed_letters(before, after)
    if typed is not None:
        return word_before_space(before[:len(before) - len(typed)]), typed
    previous = word_before_space(before)
    return (previous, "") if previous else None


def predicted_word(word: str, typed: str) -> str:
    """`KeyboardTextLogic.predictedWord(_:typed:)`."""
    letters = [character for character in typed if character.isalpha()]
    if len(letters) >= 2 and all(character.isupper() for character in letters):
        return word.upper()
    if typed[:1].isupper() or word == "i" or word.startswith("i'"):
        return word[:1].upper() + word[1:]
    return word


def word_for_emoji(text: str) -> str | None:
    """`KeyboardTextLogic.wordForEmoji(before:)`."""
    body = text[:-1] if text.endswith(" ") else text
    start = len(body)
    while start > 0 and body[start - 1].isascii() and body[start - 1].isalpha():
        start -= 1
    if start == len(body):
        return None
    if start > 0:
        preceding = body[start - 1]
        if not (preceding.isspace() or preceding in OPENING):
            return None
    return body[start:].lower()


def closes_quotation(quote: str, text: str) -> bool:
    """`KeyboardTextLogic.closesQuotation(_:before:)`. `text` is the text before the space."""
    last_break = max(text.rfind("\n"), text.rfind("\r"))
    characters = text[last_break + 1:]
    if quote == "\"":
        return characters.count("\"") % 2 == 1
    if quote != "'":
        raise SystemExit(f"closes_quotation reads only a straight quote, and got {quote!r}")
    is_open = False
    for index, character in enumerate(characters):
        if character != "'":
            continue
        previous = characters[index - 1] if index > 0 else None
        following = characters[index + 1] if index + 1 < len(characters) else None
        opens = (previous is None or previous in BEFORE_OPENING_SINGLE_QUOTE) and (
            following is not None and (is_letter_or_digit(following) or following == " "))
        closes = (previous is not None and previous != " ") and not (following is not None and following.isalpha())
        if is_open and previous == " " and following == " ":
            is_open = False
        elif opens:
            is_open = True
        elif closes:
            is_open = False
    return is_open


def space_removal(typing: str, before: str, after: str) -> str | None:
    """`KeyboardTextLogic.spaceRemoval` for a field with autocorrection: "markOnly",
    "markThenSpace" or None."""
    if len(typing) != 1:
        return None
    if not before.endswith(" ") or len(before) < 2:
        return None
    previous = before[-2]
    if not (is_letter_or_digit(previous) or previous in CLOSING):
        return None
    if typing in STRAIGHT_QUOTES:
        if not closes_quotation(typing, before[:-1]):
            return None
    elif typing not in ASCII_MARKS:
        return None
    if after and is_letter_or_digit(after[0]):
        return "markThenSpace"
    return "markOnly"


def restores_space(mark: str, following: str) -> bool:
    """`KeyboardTextLogic.restoresSpace(beforeMark:typing:)`."""
    if len(mark) != 1 or len(following) != 1:
        return False
    if is_letter_or_digit(following):
        return mark in ASCII_MARKS or mark in STRAIGHT_QUOTES or mark == "’"
    if mark in ":;" and following in EMOTICON:
        return True
    if mark in "!:?" and following == "=":
        return True
    return mark == "." and following == "/"


class EmojiTable:
    """The English emoji of Shared/emoji-suggestions.tsv (`EmojiSuggestions.english(for:)`)."""

    def __init__(self, path: Path = ROOT / "Shared" / "emoji-suggestions.tsv"):
        self.english: dict[str, list[str]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            language, word, emoji = line.split("\t")
            if language == "en":
                self.english[word] = emoji.split(" ")

    def count_before(self, text: str) -> int:
        """Count of the emoji that the strip shows for the text before the cursor."""
        word = word_for_emoji(text)
        return len(self.english.get(word, [])) if word else 0


CHUNK = re.compile(r"^([^A-Za-z0-9]*)([A-Za-z][A-Za-z']*)([^A-Za-z0-9]*)$")


def parse_chunk(chunk: str) -> tuple[str, str, str] | None:
    """The characters before the word, the word, and the characters after it, for a plain word:
    a chunk with one run of letters and apostrophes. Only opening brackets and quotes may come
    before the word, as the keyboard asks before typed letters. A chunk with a digit, with two
    runs of letters, or with another character before the word gives None, and the typist
    types it key by key. Apostrophes at the end of the word count as characters after it."""
    match = CHUNK.match(chunk)
    if match is None:
        return None
    lead, word, trail = match.groups()
    stripped = word.rstrip("'")
    trail = word[len(stripped):] + trail
    word = stripped
    if any(character not in OPENING for character in lead):
        return None
    return lead, word, trail


def tap_fits(text_with_word: str, trail: str) -> bool:
    """Whether a tap on the word gives the written text. A tap types the word and one space.
    With characters after the word, the first of them must take the place of that space, and
    the second must not bring the space back (space restore)."""
    if not trail:
        return True
    if space_removal(trail[0], text_with_word + " ", "") != "markOnly":
        return False
    return not (len(trail) > 1 and restores_space(trail[0], trail[1]))

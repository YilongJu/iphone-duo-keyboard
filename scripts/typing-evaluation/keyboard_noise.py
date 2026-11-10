"""Typing-error operators on a QWERTY touch keyboard.

Each operator takes the text a person meant to type and returns the text a slip would produce.
The operators cover the error classes the evaluation scores: a neighbor key in place of a letter,
a missing letter, a doubled letter, an extra neighbor letter, two swapped letters, and the slips
around the space bar.

Key positions are in key widths, on the phone letter layout: the second row starts half a key to
the right of the first, and the third row one and a half keys to the right.
"""
import math
import random

ROWS = [("qwertyuiop", 0.0), ("asdfghjkl", 0.5), ("zxcvbnm", 1.5)]
KEY_POSITION = {
    letter: (offset + index, float(row))
    for row, (letters, offset) in enumerate(ROWS)
    for index, letter in enumerate(letters)
}
LETTERS = "".join(letters for letters, _ in ROWS)

# The letters right above the space bar. A thumb that aims at the space bar and lands high hits
# one of these, and a thumb that aims at one of these and lands low hits the space bar.
SPACE_NEIGHBORS = "cvbnm"
# The three middle ones sit over the middle of the space bar, so they get twice the weight.
SPACE_NEIGHBOR_WEIGHTS = {"c": 1.0, "v": 2.0, "b": 2.0, "n": 2.0, "m": 1.0}

# Two keys count as neighbors up to this distance. Keys side by side are 1.0 apart, and keys one
# row apart are about 1.12 apart.
NEIGHBOR_DISTANCE = 1.15


def key_distance(first: str, second: str) -> float:
    (x1, y1), (x2, y2) = KEY_POSITION[first], KEY_POSITION[second]
    return math.hypot(x1 - x2, y1 - y2)


NEIGHBORS = {
    letter: sorted(
        other for other in LETTERS
        if other != letter and key_distance(letter, other) <= NEIGHBOR_DISTANCE
    )
    for letter in LETTERS
}


def _letter_positions(text: str) -> list[int]:
    return [index for index, character in enumerate(text) if character in KEY_POSITION]


def substitute_neighbor(text: str, rng: random.Random) -> str | None:
    """Replaces one letter with a neighbor key."""
    positions = _letter_positions(text)
    if not positions:
        return None
    index = rng.choice(positions)
    return text[:index] + rng.choice(NEIGHBORS[text[index]]) + text[index + 1:]


def delete_letter(text: str, rng: random.Random) -> str | None:
    """Drops one letter."""
    positions = _letter_positions(text)
    if len(positions) < 2:
        return None
    index = rng.choice(positions)
    return text[:index] + text[index + 1:]


def double_letter(text: str, rng: random.Random) -> str | None:
    """Types one letter twice."""
    positions = _letter_positions(text)
    if not positions:
        return None
    index = rng.choice(positions)
    return text[:index] + text[index] + text[index:]


def insert_neighbor(text: str, rng: random.Random) -> str | None:
    """Adds a neighbor of one letter right before or after that letter, as a fat finger does."""
    positions = _letter_positions(text)
    if not positions:
        return None
    index = rng.choice(positions)
    extra = rng.choice(NEIGHBORS[text[index]])
    at = index + rng.choice((0, 1))
    return text[:at] + extra + text[at:]


def transpose_letters(text: str, rng: random.Random) -> str | None:
    """Swaps two letters that sit side by side in the text and differ."""
    choices = [
        index for index in range(len(text) - 1)
        if text[index] in KEY_POSITION and text[index + 1] in KEY_POSITION and text[index] != text[index + 1]
    ]
    if not choices:
        return None
    index = rng.choice(choices)
    return text[:index] + text[index + 1] + text[index] + text[index + 2:]


LETTER_OPERATORS = {
    "substitution_adjacent": substitute_neighbor,
    "deletion": delete_letter,
    "double_letter": double_letter,
    "extra_adjacent": insert_neighbor,
    "transposition": transpose_letters,
}


def two_errors(text: str, rng: random.Random, minimum_gap: int = 3) -> str | None:
    """Applies two letter slips, of the same type or of two types, one in each part of the text."""
    if len(text) < 2 * minimum_gap + 1:
        return None
    middle = rng.randint(minimum_gap, len(text) - minimum_gap)
    first_name, second_name = rng.choices(sorted(LETTER_OPERATORS), k=2)
    head = LETTER_OPERATORS[first_name](text[:middle], rng)
    tail = LETTER_OPERATORS[second_name](text[middle:], rng)
    if head is None or tail is None:
        return None
    return head + tail


def _space_neighbor(rng: random.Random) -> str:
    letters = sorted(SPACE_NEIGHBOR_WEIGHTS)
    return rng.choices(letters, weights=[SPACE_NEIGHBOR_WEIGHTS[letter] for letter in letters])[0]


def drop_space(two_words: str, rng: random.Random) -> str | None:
    """Joins two words: the space bar press did not register."""
    if two_words.count(" ") != 1:
        return None
    return two_words.replace(" ", "")


def space_to_letter(two_words: str, rng: random.Random) -> str | None:
    """Types a letter from the row above the space bar in place of the space."""
    if two_words.count(" ") != 1:
        return None
    return two_words.replace(" ", _space_neighbor(rng))


def transpose_space(two_words: str, rng: random.Random) -> str | None:
    """Types the space one character early or one character late."""
    if two_words.count(" ") != 1:
        return None
    left, right = two_words.split(" ")
    options = []
    if len(left) >= 2:
        options.append(left[:-1] + " " + left[-1] + right)
    if len(right) >= 2:
        options.append(left + right[0] + " " + right[1:])
    return rng.choice(options) if options else None


def extra_space(word: str, rng: random.Random) -> str | None:
    """Types a space inside one word."""
    if len(word) < 4 or " " in word:
        return None
    index = rng.randint(1, len(word) - 1)
    return word[:index] + " " + word[index:]


def letter_to_space(word: str, rng: random.Random) -> str | None:
    """Hits the space bar in place of a letter from the row above the space bar."""
    choices = [index for index in range(1, len(word) - 1) if word[index] in SPACE_NEIGHBORS]
    if not choices or " " in word:
        return None
    index = rng.choice(choices)
    return word[:index] + " " + word[index + 1:]


SPACE_OPERATORS_TWO_WORDS = {
    "space_missing": drop_space,
    "space_to_letter": space_to_letter,
    "space_transposed": transpose_space,
}
SPACE_OPERATORS_ONE_WORD = {
    "space_extra": extra_space,
    "letter_to_space": letter_to_space,
}

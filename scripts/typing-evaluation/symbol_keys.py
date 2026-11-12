"""The symbol and digit keys that sit next to a letter key, from Shared/keyboard-layout.json.

A finger that aims at a letter and lands on the key beside it can type a digit or a symbol:
"[lease" for "please", "2hat" for "what". This module reads the real key positions of the
letters layer of both layout styles and lists, for every symbol key, the letters next to it.

Key positions are in key widths. A row that is narrower than the layout is centered, as in the
keyboard, and rows count as one key width apart, as in keyboard_noise.py. Two keys are neighbors
up to keyboard_noise.NEIGHBOR_DISTANCE. Only the main character of a key counts: the upper
character of a two-character key and the slide character of a letter key need a long press or
a slide, and a slip does not make one.

The typing engine (Engine/duo_engine.c) and the keyboard (Shared/KeyboardTextLogic.swift) each
hold a copy of the result. The check compares both copies with the layout file:
    python3 scripts/typing-evaluation/symbol_keys.py --check

A workflow that compares the engine with an older engine gives the older engine the table of
the layout file first, so the comparison reads only the change that the workflow is about:
    python3 scripts/typing-evaluation/symbol_keys.py --write-engine-table build/base-engine/duo_engine.c
"""
import json
import math
import re
import sys
from pathlib import Path

import keyboard_noise as noise

ROOT = Path(__file__).resolve().parents[2]
LAYOUT = ROOT / "Shared" / "keyboard-layout.json"
ENGINE_SOURCE = ROOT / "Engine" / "duo_engine.c"
KEYBOARD_SOURCE = ROOT / "Shared" / "KeyboardTextLogic.swift"
STYLES = ("wide", "compact")
LETTERS = "abcdefghijklmnopqrstuvwxyz"


def key_positions(style: dict) -> dict[str, tuple[float, float]]:
    """The center of every character key of the letters layer, by the key's main character."""
    positions = {}
    for row_index, row in enumerate(style["letters"]):
        widths = []
        characters = []
        for key in row["keys"]:
            if isinstance(key, str):
                characters.append(key)
                widths.append(1.0)
            elif isinstance(key, list):
                characters.append(key[0])
                widths.append(1.0)
            else:
                # {"c": "a", "a": "@"} is the letter "a" with the slide character "@", and
                # {"c": "1", "s": "!"} is "1" with the upper character "!". Both count as "c".
                # A function key has no "c" and only takes its width.
                unknown = set(key) - {"c", "s", "a", "f", "w"}
                if unknown or ("c" in key) == ("f" in key):
                    raise SystemExit(f"unknown key form in {LAYOUT.name}: {key}")
                characters.append(key.get("c"))
                widths.append(float(key.get("w", 1)))
        left = (style["units"] - sum(widths)) / 2
        for character, width in zip(characters, widths):
            if character is not None:
                positions[character] = (left + width / 2, float(row_index))
            left += width
    return positions


def neighbors_in_style(style: dict) -> dict[str, list[str]]:
    """For every symbol or digit key of one layout style: the letters next to it."""
    positions = key_positions(style)
    result = {}
    for symbol, (x, y) in positions.items():
        if symbol in LETTERS:
            continue
        near = sorted(
            letter for letter in LETTERS
            if letter in positions and math.hypot(x - positions[letter][0], y - positions[letter][1]) <= noise.NEIGHBOR_DISTANCE
        )
        if near:
            result[symbol] = near
    return result


def symbol_neighbors(layout_path: Path = LAYOUT) -> dict[str, list[str]]:
    """For every symbol or digit key: the letters next to it in the wide or the compact layout."""
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    result: dict[str, set[str]] = {}
    for name in STYLES:
        for symbol, letters in neighbors_in_style(layout[name]).items():
            result.setdefault(symbol, set()).update(letters)
    return {symbol: sorted(letters) for symbol, letters in sorted(result.items())}


def symbols_of_letter(neighbors: dict[str, list[str]]) -> dict[str, list[str]]:
    """The reverse table: for every letter, the symbol and digit keys next to it."""
    result: dict[str, list[str]] = {}
    for symbol, letters in neighbors.items():
        for letter in letters:
            result.setdefault(letter, []).append(symbol)
    return {letter: sorted(symbols) for letter, symbols in sorted(result.items())}


# A slip inside a word can only be a digit or "[". The other symbol keys beside a letter end a
# word or join two words ("," "." ";" "-"), so the keyboard reads them as a slip only in front
# of a word.
def may_stand_inside_a_word(symbol: str) -> bool:
    return symbol.isdigit() or symbol == "["


# One line of the table symbol_neighbors in duo_engine.c, as in: case ',': return "klmn";
ENGINE_TABLE_LINE = re.compile(r"case '(\\?.)': return \"([a-z]+)\";")


def engine_table(source: str) -> dict[str, list[str]]:
    """The table symbol_neighbors of one copy of duo_engine.c."""
    return {symbol.replace("\\\\", "\\"): sorted(letters) for symbol, letters in ENGINE_TABLE_LINE.findall(source)}


def write_engine_table(path: Path) -> None:
    """Puts the letters of the layout file into the table symbol_neighbors of a copy of
    duo_engine.c. The copy must hold a line for each symbol key of the layout file and no other."""
    expected = symbol_neighbors()
    source = path.read_text(encoding="utf-8")
    found = engine_table(source)
    if sorted(found) != sorted(expected):
        raise SystemExit(f"{path}: symbol_neighbors holds the keys {sorted(found)}, the layout gives {sorted(expected)}")

    def line_of_the_layout(line: re.Match) -> str:
        letters = "".join(expected[line.group(1).replace("\\\\", "\\")])
        return f"case '{line.group(1)}': return \"{letters}\";"

    written = ENGINE_TABLE_LINE.sub(line_of_the_layout, source)
    if engine_table(written) != expected:
        raise SystemExit(f"{path}: the table does not hold the layout's letters after the write")
    path.write_text(written, encoding="utf-8", newline="\n")
    changed = sorted(symbol for symbol in expected if found[symbol] != expected[symbol])
    print(f"{path}: wrote the symbol keys of {LAYOUT.name}, changed keys: {' '.join(changed) or 'none'}")


def check() -> list[str]:
    """Compares the copies in the engine and in the keyboard with the layout file."""
    expected = symbol_neighbors()
    problems = []

    engine = ENGINE_SOURCE.read_text(encoding="utf-8")
    found = engine_table(engine)
    if found != expected:
        problems.append(f"{ENGINE_SOURCE.name}: symbol_neighbors holds {found}, the layout gives {expected}")

    keyboard = KEYBOARD_SOURCE.read_text(encoding="utf-8")
    for name, wanted in (
        ("symbolsBesideLetters", sorted(expected)),
        ("symbolsInsideWords", sorted(symbol for symbol in expected if may_stand_inside_a_word(symbol))),
    ):
        match = re.search(rf"static let {name}: Set<Character> = Set\(\"([^\"]*)\"\)", keyboard)
        if match is None:
            problems.append(f"{KEYBOARD_SOURCE.name}: {name} is missing")
        elif sorted(match.group(1)) != wanted:
            problems.append(f"{KEYBOARD_SOURCE.name}: {name} holds {sorted(match.group(1))}, the layout gives {wanted}")
    return problems


def main():
    if sys.argv[1:] == ["--check"]:
        problems = check()
        for problem in problems:
            print("PROBLEM", problem)
        if problems:
            raise SystemExit(f"{len(problems)} problem(s): a copy of the symbol keys differs from {LAYOUT.name}")
        print(f"the engine and the keyboard hold the symbol keys of {LAYOUT.name}")
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--write-engine-table":
        write_engine_table(Path(sys.argv[2]))
        return
    if sys.argv[1:]:
        raise SystemExit(f"unknown arguments: {sys.argv[1:]}")
    layout = json.loads(LAYOUT.read_text(encoding="utf-8"))
    for name in STYLES:
        print(name, neighbors_in_style(layout[name]))
    print("both", symbol_neighbors())
    print("by letter", symbols_of_letter(symbol_neighbors()))


if __name__ == "__main__":
    main()

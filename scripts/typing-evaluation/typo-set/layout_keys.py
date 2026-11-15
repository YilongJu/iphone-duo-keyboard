"""The keys of the letters layer of the keyboard's two layouts, from Shared/keyboard-layout.json.

The wide layout has rows of 13.5 key units (the open iPhone Duo). The compact layout has rows of
10 key units (the closed phone). A letter key is 1 unit wide. A row that is narrower than the
layout is centered, and rows are 1 unit apart, as in scripts/typing-evaluation/symbol_keys.py.

Each key has a span on its row: from its left edge to its right edge. A key that types a
character has `character`. A function key (shift, return, the space bar and the others) has
`function` and types no character.

Two slips read these keys:
- Neighbor key: a letter key whose center lies at most NEIGHBOR_DISTANCE from the center of the
  intended key. The value is the one of keyboard_noise.py and symbol_keys.py.
- Drift: the hand moves by one key and types every key from the moved place. A drift has a
  direction and an offset (dx, dy) in key units. Left is (-1, 0) and right is (+1, 0). Up is
  (dx, -1) and down is (dx, +1), where dx is a small sideways part that the case records. The
  drifted key is the key whose span holds the moved point on the moved row.
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LAYOUT = ROOT / "Shared" / "keyboard-layout.json"
STYLES = ("wide", "compact")
LETTERS = "abcdefghijklmnopqrstuvwxyz"
NEIGHBOR_DISTANCE = 1.15
DIRECTIONS = ("left", "right", "up", "down")
# The sideways part of an up or down drift. A finger that moves up or down also moves a little to
# one side. The compact layout puts the middle of a home-row key right on the edge between two
# keys of the top row, so a drift straight up has no single key there.
SIDEWAYS = (-0.3, 0.3)


@dataclass(frozen=True)
class Key:
    row: int
    left: float
    width: float
    character: str | None
    function: str | None

    @property
    def center(self) -> tuple[float, float]:
        return (self.left + self.width / 2, float(self.row))


def read_style(name: str, layout_path: Path = LAYOUT) -> list[list[Key]]:
    """The rows of the letters layer of one layout style."""
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    style = layout[name]
    rows = []
    for row_index, row in enumerate(style["letters"]):
        keys = []
        for key in row["keys"]:
            if isinstance(key, str):
                keys.append((key, None, 1.0))
            elif isinstance(key, list):
                keys.append((key[0], None, 1.0))
            else:
                unknown = set(key) - {"c", "s", "a", "f", "w"}
                if unknown or ("c" in key) == ("f" in key):
                    raise SystemExit(f"unknown key form in {layout_path.name}: {key}")
                keys.append((key.get("c"), key.get("f"), float(key.get("w", 1))))
        left = (style["units"] - sum(width for _, _, width in keys)) / 2
        placed = []
        for character, function, width in keys:
            placed.append(Key(row_index, left, width, character, function))
            left += width
        rows.append(placed)
    return rows


class Layout:
    def __init__(self, name: str, layout_path: Path = LAYOUT):
        if name not in STYLES:
            raise SystemExit(f"unknown layout style {name!r}")
        self.name = name
        self.rows = read_style(name, layout_path)
        self.by_character: dict[str, Key] = {}
        for row in self.rows:
            for key in row:
                if key.character is not None:
                    if key.character in self.by_character:
                        raise SystemExit(f"{name}: the character {key.character!r} has two keys")
                    self.by_character[key.character] = key
        missing = [letter for letter in LETTERS if letter not in self.by_character]
        if missing:
            raise SystemExit(f"{name}: no key for the letters {missing}")
        self.neighbors = {
            letter: sorted(
                other for other in LETTERS
                if other != letter and math.dist(self.by_character[letter].center, self.by_character[other].center)
                <= NEIGHBOR_DISTANCE)
            for letter in LETTERS
        }

    def key_at(self, x: float, row: int) -> Key | None:
        """The key whose span holds the point x on the row, or None outside the rows."""
        if not 0 <= row < len(self.rows):
            return None
        for key in self.rows[row]:
            if key.left <= x < key.left + key.width:
                return key
        return None

    def offset(self, direction: str, sideways: float) -> tuple[float, int]:
        if direction == "left":
            return (-1.0, 0)
        if direction == "right":
            return (1.0, 0)
        if direction == "up":
            return (sideways, -1)
        if direction == "down":
            return (sideways, 1)
        raise SystemExit(f"unknown drift direction {direction!r}")

    def drifted(self, character: str, direction: str, sideways: float) -> str | None:
        """The character that the drifted hand types for `character`, or None when the moved
        point lands on a function key, the space bar or outside the keys. Left and right move to
        the next key of the row by its span, so a wide key such as tab counts as one key."""
        key = self.by_character.get(character)
        if key is None:
            return None
        dx, dy = self.offset(direction, sideways)
        x, _ = key.center
        if dy == 0:
            row = self.rows[key.row]
            index = row.index(key)
            other_index = index + (1 if dx > 0 else -1)
            if not 0 <= other_index < len(row):
                return None
            other = row[other_index]
        else:
            other = self.key_at(x + dx, key.row + dy)
        if other is None or other.character is None:
            return None
        return other.character

    def drift_text(self, text: str, direction: str, sideways: float, start: int = 0) -> str | None:
        """`text` with every letter from `start` on drifted. Spaces stay: the space bar is wide,
        and a thumb that drifts still hits it. None when one letter has no drifted key."""
        out = list(text)
        for index in range(start, len(text)):
            if text[index] == " ":
                continue
            moved = self.drifted(text[index], direction, sideways)
            if moved is None:
                return None
            out[index] = moved
        return "".join(out)


def both() -> dict[str, Layout]:
    return {name: Layout(name) for name in STYLES}


if __name__ == "__main__":
    for name, layout in both().items():
        print(name)
        for direction in DIRECTIONS:
            for sideways in (SIDEWAYS if direction in ("up", "down") else (0.0,)):
                moved = {letter: layout.drifted(letter, direction, sideways) for letter in LETTERS}
                print(f"  {direction:5s} {sideways:+.1f}", " ".join(f"{a}{b or '_'}" for a, b in moved.items()))
        print("  this phrase, right:", layout.drift_text("this phrase", "right", 0.0))

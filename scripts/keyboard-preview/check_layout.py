"""Checks Shared/keyboard-layout.json against the layout rules.

Usage, from the repository root:
    python scripts/keyboard-preview/check_layout.py [path to a layout file]

The script exits with an error and lists every broken rule. The rules:
1. Every row is as wide as the layout or narrower. A narrower row is centered.
2. Every layer has a space bar, a backspace key and a return key.
3. Every layer has exactly one key for each other layer it leads to. In particular a symbol
   layer has exactly one key that returns to the letters.
4. A character is the main character of at most one key in a layer. The upper character of a
   two-character key does not count, because the compact number row repeats those on purpose.
5. Each layout style reaches all 32 ASCII punctuation characters and all 10 digits.
6. Every wide row names the key where the split layout puts its empty middle.
"""
import json
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAYOUT = ROOT / "Shared" / "keyboard-layout.json"
LAYERS = ("letters", "symbols", "more")
LAYER_KEYS = {"letters", "symbols", "more"}
# The layer keys each layer must hold, with the count of each.
EXPECTED_LAYER_KEYS = {
    "letters": {"symbols": 1},
    "symbols": {"letters": 1, "more": 1},
    "more": {"letters": 1, "symbols": 1},
}


def key_parts(key):
    """Returns (function name or None, main character or None, all characters the key types, width)."""
    if isinstance(key, str):
        return None, key, [key], 1
    if isinstance(key, list):
        return None, key[0], list(key), 1
    if "c" in key:
        typed = [key["c"]] + ([key["s"]] if "s" in key else [])
        return None, key["c"], typed, key.get("w", 1)
    return key["f"], None, [], key.get("w", 1)


def check(layout):
    problems = []
    for style_name in ("wide", "compact"):
        style = layout[style_name]
        units = style["units"]
        reachable = set()
        for layer_name in LAYERS:
            if layer_name not in style:
                problems.append(f"{style_name}: layer '{layer_name}' is missing")
                continue
            where = f"{style_name}/{layer_name}"
            functions = []
            main_characters = []
            for row_index, row in enumerate(style[layer_name]):
                width = 0
                for key in row["keys"]:
                    function, main, typed, key_width = key_parts(key)
                    width += key_width
                    if function:
                        functions.append(function)
                    if main is not None:
                        main_characters.append(main)
                    reachable.update(typed)
                if style_name == "wide":
                    split = row.get("split")
                    if not isinstance(split, int) or not 0 < split < len(row["keys"]):
                        problems.append(f"{where} row {row_index}: the split value {split!r} is not a key position")
                    # The split layout puts its empty middle into every row, so every row must
                    # fill the layout's width, or its two halves do not line up with the others.
                    if abs(width - units) > 1e-6:
                        problems.append(f"{where} row {row_index}: width {width:g} is not the {units:g} units of the layout")
                if width > units + 1e-9:
                    problems.append(f"{where} row {row_index}: width {width:g} is over {units:g} units")
            for required in ("space", "backspace", "return"):
                if required not in functions:
                    problems.append(f"{where}: the '{required}' key is missing")
            for target in sorted(LAYER_KEYS):
                found = functions.count(target)
                wanted = EXPECTED_LAYER_KEYS[layer_name].get(target, 0)
                if found != wanted:
                    problems.append(f"{where}: {found} '{target}' layer keys, expected {wanted}")
            repeated = sorted({c for c in main_characters if main_characters.count(c) > 1})
            if repeated:
                problems.append(f"{where}: characters appear more than once: {' '.join(repeated)}")
        missing = sorted(set(string.punctuation + string.digits) - reachable)
        if missing:
            problems.append(f"{style_name}: characters out of reach: {' '.join(missing)}")
    return problems


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LAYOUT
    found = check(json.loads(path.read_text(encoding="utf-8")))
    for problem in found:
        print("PROBLEM", problem)
    if found:
        raise SystemExit(f"{len(found)} layout problem(s) in {path}")
    print(f"layout rules hold for {path}")

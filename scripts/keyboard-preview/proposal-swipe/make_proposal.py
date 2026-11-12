"""Writes proposal-layout.json: Shared/keyboard-layout.json with the compact layout changed.

Three changes to the compact layout (the folded phone):
1. The return key is 1.5 key units wide in place of 2.5, on every layer.
2. The letters layer gets a comma key left of the period key. A slide up or down on the comma
   types "!", and on the period types "?", as on the iPad keyboard of iOS.
3. The 16 letters of the second and third letter rows each get a second character, typed by a
   slide up or down. The characters and their places are those of the iPad keyboard of iOS.

A letter key with a second character has the form {"c": "a", "a": "@"}.

Run it against the layout of commit f48cd80 (the layout before this change).
"""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
current = json.loads((ROOT / "Shared" / "keyboard-layout.json").read_text(encoding="utf-8"))
proposal = copy.deepcopy(current)
compact = proposal["compact"]

# The second characters of the iPad keyboard of iOS, for the rows A to L and Z to M.
SECOND = {
    "a": "@", "s": "#", "d": "$", "f": "&", "g": "*", "h": "(", "j": ")", "k": "'", "l": "\"",
    "z": "%", "x": "-", "c": "+", "v": "=", "b": "/", "n": ";", "m": ":",
}
RETURN_WIDTH = 1.5


def with_second(key):
    if isinstance(key, str) and key in SECOND:
        return {"c": key, "a": SECOND[key]}
    return key


letters = compact["letters"]
for row in letters[3:5]:
    row["keys"] = [with_second(key) for key in row["keys"]]
letters[5]["keys"] = [
    {"f": "symbols", "w": 1.25}, {"f": "globe", "w": 1.25}, {"f": "language", "w": 1},
    {"f": "space", "w": 3}, [",", "!"], [".", "?"], {"f": "return", "w": RETURN_WIDTH},
]
for layer in ("symbols", "more"):
    keys = compact[layer][5]["keys"]
    freed = 0
    for key in keys:
        if isinstance(key, dict) and key.get("f") == "return":
            freed = key["w"] - RETURN_WIDTH
            key["w"] = RETURN_WIDTH
    for key in keys:
        if isinstance(key, dict) and key.get("f") == "space":
            key["w"] += freed

out = Path(__file__).with_name("proposal-layout.json")
out.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding="utf-8")
print("wrote", out.relative_to(ROOT))

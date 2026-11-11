"""Writes proposal-layout.json: Shared/keyboard-layout.json with the wide layout on 13.5 key units.

The letter keys grow from 1/14.5 to 1/13.5 of the keyboard width, and the letters move toward
the middle. Every digit and symbol key keeps the letters next to it that
scripts/typing-evaluation/symbol_keys.py finds today, so the typing test cases stay valid.

The script reads the 14.5-unit layout of the commit before b7ce57d, which applied its output to
Shared/keyboard-layout.json. Run it only against that version of the file.
"""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
current = json.loads((ROOT / "Shared" / "keyboard-layout.json").read_text(encoding="utf-8"))
proposal = copy.deepcopy(current)
wide = proposal["wide"]
wide["units"] = 13.5


def f(name, width):
    return {"f": name, "w": width}


def c(character, width, shifted=None):
    key = {"c": character, "w": width}
    if shifted is not None:
        key["s"] = shifted
    return key


shortcuts = [f("selectAll", 2.3), f("cut", 2.3), f("copy", 2.3), f("paste", 2.3), f("home", 2.15), f("end", 2.15)]
bottom_letters = [f("globe", 1.1), f("symbols", 1.1), f("language", 1.1), f("space", 6.5), f("dismiss", 1.0),
                  f("left", 0.9), f("down", 0.9), f("right", 0.9)]
bottom_symbols = [f("globe", 1.1), f("letters", 1.1), f("space", 7.6), f("dismiss", 1.0),
                  f("left", 0.9), f("down", 0.9), f("right", 0.9)]


def number_row(characters, shifted=None):
    """`` ` `` 1.0, ten digits 0.9, the last two 0.95, backspace 1.6."""
    widths = [1.0] + [0.9] * 10 + [0.95, 0.95]
    keys = [c(ch, w, None if shifted is None else shifted[i]) for i, (ch, w) in enumerate(zip(characters, widths))]
    return keys + [f("backspace", 1.6)]


letters = wide["letters"]
letters[0]["keys"] = shortcuts
pairs = current["wide"]["letters"][1]["keys"][:13]
letters[1]["keys"] = number_row([p[0] for p in pairs], [p[1] for p in pairs])
letters[2]["keys"] = [f("tab", 1.35)] + list("qwertyuiop") + [c("[", 0.72, "{"), c("]", 0.72, "}"), c("\\", 0.71, "|")]
letters[3]["keys"] = [f("capsLock", 1.75)] + list("asdfghjkl") + [c(";", 0.7, ":"), c("'", 0.7, "\""), f("return", 1.35)]
letters[4]["keys"] = [f("shift", 2.3)] + list("zxcvbnm") + [c(",", 0.8, "<"), c(".", 0.8, ">"), c("/", 0.8, "?"),
                                                            f("up", 0.9), f("shift", 0.9)]
letters[5]["keys"] = bottom_letters

for layer, first, fourth_first in (("symbols", "more", "more"), ("more", "symbols", "symbols")):
    rows = wide[layer]
    rows[0]["keys"] = shortcuts
    old = current["wide"][layer]
    rows[1]["keys"] = number_row(old[1]["keys"][:13])
    rows[2]["keys"] = [f("tab", 1.41)] + [c(k, 0.93) for k in old[2]["keys"][1:]]
    rows[3]["keys"] = [c(k["c"], 1.0) for k in old[3]["keys"][:12]] + [f("return", 1.5)]
    rows[4]["keys"] = [f(fourth_first, 1.25)] + [c(k, 0.95) for k in old[4]["keys"][1:12]] + [f("up", 0.9), f("forwardDelete", 0.9)]
    rows[5]["keys"] = bottom_symbols

out = Path(__file__).with_name("proposal-layout.json")
out.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding="utf-8")
print("wrote", out.relative_to(ROOT))

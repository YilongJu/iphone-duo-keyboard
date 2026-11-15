"""Builds the generated Pinyin cases of the typo set: cases/pinyin-typos.dev.jsonl and
cases/pinyin-typos.test.jsonl. docs/typo-set-design.md describes every rule.

A case holds the Chinese text before the cursor (`context`), the letters a person typed
(`typed`), the Chinese text the person meant (`intended`) and its syllables. A keyboard gets
`typed` and must give `intended` as its first candidates. Each slip case names its clean case
in `twin`: the same clause typed right. The scorer then reports the repair rate among the
cases whose clean twin the engine converts right.

The slips use the real keys of the keyboard's two layouts (layout_keys.py), as the English
cases do. The Pinyin keyboard has the same letter keys.

Sources:
- Sentences: Tatoeba Mandarin export, CC BY 2.0 FR, https://tatoeba.org, read and cut into
  clauses by scripts/typing-evaluation/build_pinyin_cases.py.
- Pinyin and the standard syllables: the pypinyin package (MIT).
- Simplified Chinese filter: OpenCC (Apache 2.0).

Splits: a sentence with an even Tatoeba id feeds the dev half and one with an odd id the test
half. A clause of the existing Pinyin cases stays out.

Usage, from the repository root:
    uv run --with pypinyin --with opencc-python-reimplemented python scripts/typing-evaluation/typo-set/build_pinyin_typos.py
"""
import bz2
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import build_pinyin_cases as base  # noqa: E402
import layout_keys  # noqa: E402
from opencc import OpenCC  # noqa: E402

ROOT = HERE.parents[2]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
REPORTS = HERE / "reports"
SEED = "typo-set-pinyin-20261114"
SHORTEST, LONGEST = 3, 12

FUZZY_PAIRS = {
    "z_zh": ("initial", "z", "zh"), "c_ch": ("initial", "c", "ch"), "s_sh": ("initial", "s", "sh"),
    "n_l": ("initial", "n", "l"), "an_ang": ("final", "an", "ang"), "en_eng": ("final", "en", "eng"),
    "in_ing": ("final", "in", "ing"),
}
QUOTAS = {
    "pinyin_neighbor": 150, "pinyin_omitted": 100, "pinyin_added": 100, "pinyin_swapped": 100,
    "pinyin_drift_word": 100, "pinyin_drift_partial": 100,
    **{f"pinyin_fuzzy_{name}": 50 for name in FUZZY_PAIRS},
    "pinyin_split_apostrophe": 60, "pinyin_split_plain": 60,
}
GROUPS = {
    "finger_slips": ["pinyin_neighbor", "pinyin_omitted", "pinyin_added", "pinyin_swapped"],
    "drift": ["pinyin_drift_word", "pinyin_drift_partial"],
    "fuzzy": [f"pinyin_fuzzy_{name}" for name in FUZZY_PAIRS],
    "split": ["pinyin_split_apostrophe", "pinyin_split_plain"],
    "clean": ["pinyin_clean"],
}
GROUP_OF = {category: group for group, members in GROUPS.items() for category in members}


def load_clauses(valid: set[str]) -> dict[str, list[dict]]:
    """Clauses with the text before them in their sentence, by half. A clause of the existing
    Pinyin case files stays out."""
    used = set()
    for half in ("dev", "test"):
        for line in (CASES / f"pinyin.{half}.jsonl").read_text(encoding="utf-8").splitlines():
            if line:
                used.add(json.loads(line)["intended"])
    if not base.CACHE.exists():
        raise SystemExit(f"{base.CACHE} is missing: run scripts/typing-evaluation/build_pinyin_cases.py once to fetch it")
    to_simplified = OpenCC("t2s")
    halves = {"dev": [], "test": []}
    seen = set()
    counts = {"clauses": 0, "removed_existing_cases": 0}
    with bz2.open(base.CACHE, "rt", encoding="utf-8") as lines:
        for line in lines:
            sentence_id, _, text = line.rstrip("\n").split("\t", 2)
            for match in base.CLAUSE.finditer(text):
                clause = match.group(0)
                if not SHORTEST <= len(clause) <= LONGEST or clause in seen:
                    continue
                seen.add(clause)
                if to_simplified.convert(clause) != clause:
                    continue
                syllables = base.to_syllables(clause, valid)
                if syllables is None:
                    continue
                counts["clauses"] += 1
                if clause in used:
                    counts["removed_existing_cases"] += 1
                    continue
                half = "dev" if int(sentence_id) % 2 == 0 else "test"
                halves[half].append({"text": clause, "syllables": syllables, "context": text[:match.start()],
                                     "source": f"tatoeba:{sentence_id}"})
    counts.update({half: len(clauses) for half, clauses in halves.items()})
    return halves, counts


def greedy_split(letters: str, valid: set[str]) -> list[str] | None:
    """The cut into syllables that takes the longest syllable first at each place and still
    cuts every letter, as PinyinEngine.longestWholeSyllables does."""
    longest = max(len(s) for s in valid)
    finishes = [False] * (len(letters) + 1)
    finishes[len(letters)] = True
    for position in range(len(letters) - 1, -1, -1):
        finishes[position] = any(finishes[position + n] and letters[position:position + n] in valid
                                 for n in range(1, min(longest, len(letters) - position) + 1))
    if not finishes[0]:
        return None
    out, position = [], 0
    while position < len(letters):
        length = min(longest, len(letters) - position)
        while not (finishes[position + length] and letters[position:position + length] in valid):
            length -= 1
        out.append(letters[position:position + length])
        position += length
    return out


def letter_places(syllables: list[str]) -> list[tuple[int, int]]:
    """(syllable index, letter index inside it) for every typed letter."""
    return [(s, i) for s, syllable in enumerate(syllables) for i in range(len(syllable))]


def neighbor_slip(syllables, layout, rng):
    s, i = rng.choice(letter_places(syllables))
    syllable = syllables[s]
    changed = syllable[:i] + rng.choice(layout.neighbors[syllable[i]]) + syllable[i + 1:]
    return "".join(syllables[:s]) + changed + "".join(syllables[s + 1:]), {"syllable": s}


def omitted_slip(syllables, layout, rng):
    s, i = rng.choice(letter_places(syllables))
    syllable = syllables[s]
    return "".join(syllables[:s]) + syllable[:i] + syllable[i + 1:] + "".join(syllables[s + 1:]), {"syllable": s}


def added_slip(syllables, layout, rng):
    s, i = rng.choice(letter_places(syllables))
    syllable = syllables[s]
    at = i + rng.choice((0, 1))
    extra = rng.choice(layout.neighbors[syllable[i]])
    return "".join(syllables[:s]) + syllable[:at] + extra + syllable[at:] + "".join(syllables[s + 1:]), {"syllable": s}


def swapped_slip(syllables, layout, rng):
    letters = "".join(syllables)
    places = [i for i in range(len(letters) - 1) if letters[i] != letters[i + 1]]
    if not places:
        return None
    i = rng.choice(places)
    return letters[:i] + letters[i + 1] + letters[i] + letters[i + 2:], {}


def drift_slip(partial: bool):
    """Two neighboring syllables, the length of a common word, typed with the hand one key off.
    A partial drift starts after the first letter of the first of them."""
    def slip(syllables, layout, rng):
        if len(syllables) < 2:
            return None
        s = rng.randrange(len(syllables) - 1)
        direction = rng.choice(layout_keys.DIRECTIONS)
        sideways = rng.choice(layout_keys.SIDEWAYS) if direction in ("up", "down") else 0.0
        head = "".join(syllables[:s])
        word = syllables[s] + syllables[s + 1]
        start = rng.randint(1, len(syllables[s])) if partial else 0
        if partial and len(word) - start < 2:
            return None
        moved = layout.drift_text(word, direction, sideways, start)
        if moved is None or not moved.isalpha() or not moved.isascii():
            return None
        return head + moved + "".join(syllables[s + 2:]), {"direction": direction, "sideways": sideways,
                                                         "drift_start": start, "syllable": s}
    return slip


def fuzzy_slip(name: str, valid: set[str]):
    kind, short, long = FUZZY_PAIRS[name]

    def swaps(syllable: str) -> list[str]:
        out = []
        if kind == "initial" and short == "n":
            # n and l: one letter each way.
            if syllable.startswith("n"):
                out.append("l" + syllable[1:])
            elif syllable.startswith("l"):
                out.append("n" + syllable[1:])
        elif kind == "initial":
            if syllable.startswith(long):
                out.append(short + syllable[len(long):])
            elif syllable.startswith(short):
                out.append(long + syllable[len(short):])
        else:
            if syllable.endswith(long):
                out.append(syllable[:-len(long)] + short)
            elif syllable.endswith(short):
                out.append(syllable[:-len(short)] + long)
        return [v for v in out if v in valid and v != syllable]

    def slip(syllables, layout, rng):
        options = [(s, v) for s, syllable in enumerate(syllables) for v in swaps(syllable)]
        if not options:
            return None
        s, swapped = rng.choice(options)
        return "".join(syllables[:s] + [swapped] + syllables[s + 1:]), {"syllable": s, "fuzzy_from": syllables[s],
                                                                        "fuzzy_to": swapped}
    return slip


def split_slip(with_apostrophe: bool, valid: set[str]):
    """A clause whose letters the longest-first cut reads as other syllables, as "xian" for
    "xi an". With the apostrophe the person marks the break, as in "xi'an"."""
    def slip(syllables, layout, rng):
        letters = "".join(syllables)
        greedy = greedy_split(letters, valid)
        if greedy is None or greedy == syllables:
            return None
        # The first break where the two cuts part.
        position, a, b = 0, 0, 0
        breaks_intended = set()
        for syllable in syllables:
            position += len(syllable)
            breaks_intended.add(position)
        position = 0
        greedy_breaks = set()
        for syllable in greedy:
            position += len(syllable)
            greedy_breaks.add(position)
        missing = sorted(breaks_intended - greedy_breaks)
        if not missing:
            return None
        cut = missing[0]
        typed = letters[:cut] + "'" + letters[cut:] if with_apostrophe else letters
        return typed, {"greedy_split": " ".join(greedy)}
    return slip


def build_half(half: str, clauses: list[dict], valid: set[str], layouts) -> tuple[list[dict], dict]:
    cases: list[dict] = []
    clean_of: dict[str, str] = {}
    shortfalls = {}

    def clean_case(clause) -> str:
        key = clause["text"]
        if key not in clean_of:
            case_id = f"zhtypo-{half}-pinyin_clean-{len(clean_of):04d}"
            clean_of[key] = case_id
            cases.append({"id": case_id, "split": half, "category": "pinyin_clean", "group": "clean", "expected": "keep",
                          "context": clause["context"], "typed": "".join(clause["syllables"]), "intended": clause["text"],
                          "intended_pinyin": " ".join(clause["syllables"]), "source": clause["source"]})
        return clean_of[key]

    makers = {
        "pinyin_neighbor": neighbor_slip, "pinyin_omitted": omitted_slip, "pinyin_added": added_slip,
        "pinyin_swapped": swapped_slip, "pinyin_drift_word": drift_slip(False), "pinyin_drift_partial": drift_slip(True),
        **{f"pinyin_fuzzy_{name}": fuzzy_slip(name, valid) for name in FUZZY_PAIRS},
        "pinyin_split_apostrophe": split_slip(True, valid), "pinyin_split_plain": split_slip(False, valid),
    }
    for category, maker in makers.items():
        rng = random.Random(f"{SEED}-{half}-{category}")
        order = clauses[:]
        rng.shuffle(order)
        number = 0
        for clause in order:
            letters = "".join(clause["syllables"])
            if len(letters) < base.SLIP_MINIMUM_LETTERS:
                continue
            layout = layouts[rng.choice(layout_keys.STYLES)]
            made = maker(clause["syllables"], layout, rng)
            if made is None:
                continue
            typed, fields = made
            split_case = category.startswith("pinyin_split")
            if not split_case and typed == letters:
                continue
            twin = clean_case(clause)
            case = {"id": f"zhtypo-{half}-{category}-{number:04d}", "split": half, "category": category,
                    "group": GROUP_OF[category], "expected": "correct", "context": clause["context"], "typed": typed,
                    "intended": clause["text"], "intended_pinyin": " ".join(clause["syllables"]),
                    "typed_parses_exactly": base.parses_exactly(typed.replace("'", ""), valid),
                    "source": clause["source"], "layout": layout.name, "twin": twin}
            case.update(fields)
            cases.append(case)
            number += 1
            if number == QUOTAS[category]:
                break
        else:
            shortfalls[category] = {"wanted": QUOTAS[category], "made": number}
    return cases, shortfalls


def main():
    valid = base.standard_syllables()
    clauses, counts = load_clauses(valid)
    layouts = layout_keys.both()
    report = {"seed": SEED, "pool": counts, "halves": {}}
    for half in ("dev", "test"):
        cases, shortfalls = build_half(half, clauses[half], valid, layouts)
        path = CASES / f"pinyin-typos.{half}.jsonl"
        path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")
        tally: dict[str, int] = {}
        for case in cases:
            tally[case["category"]] = tally.get(case["category"], 0) + 1
        report["halves"][half] = {"cases": len(cases), "categories": tally, "shortfalls": shortfalls}
        print(f"wrote {path.relative_to(ROOT)}: {len(cases)} cases")
        for category, count in tally.items():
            sample = next(case for case in cases if case["category"] == category)
            print(f"  {category:28s} {count:4d}   e.g. {sample['typed']} -> {sample['intended']} ({sample['intended_pinyin']})")
        if shortfalls:
            print("  shortfalls:", shortfalls)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "pinyin-typos-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                      encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

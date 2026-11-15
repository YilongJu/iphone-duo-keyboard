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
- Pinyin and the standard syllables: the pypinyin package (MIT), with the word cut of jieba
  (MIT), by pinyin_reading.py. A clause with a character of uncertain reading stays out.
- Simplified Chinese filter: OpenCC (Apache 2.0).

Splits: a sentence with an even Tatoeba id feeds the dev half and one with an odd id the test
half. A clause that holds, or stands inside, a clause of the existing Pinyin cases stays out. A
clause that holds, or stands inside, a clause of the other half stays out of both halves.

Usage, from the repository root:
    uv run --with pypinyin==0.55.0 --with jieba==0.42.1 --with opencc-python-reimplemented==0.1.7 \
        python scripts/typing-evaluation/typo-set/build_pinyin_typos.py
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
import pinyin_reading  # noqa: E402
from opencc import OpenCC  # noqa: E402

ROOT = HERE.parents[2]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
REPORTS = HERE / "reports"
SEED = "typo-set-pinyin-20261114"
SHORTEST, LONGEST = 3, 12
# The shortest clause that the containment rule reads. A clause of 3 characters stands inside
# many longer clauses, and the rule then reads each of them.
CONTAINMENT_MINIMUM = 3

# Fuzzy pairs, as the fuzzy settings of common Pinyin input methods name them. A final pair
# swaps the end of a syllable. The finals ian/iang and uan/uang come before an/ang, so an/ang
# holds the other syllables with an or ang only.
FUZZY_PAIRS = {
    "z_zh": ("initial", "z", "zh"), "c_ch": ("initial", "c", "ch"), "s_sh": ("initial", "s", "sh"),
    "n_l": ("letter", "n", "l"), "f_h": ("letter", "f", "h"), "r_l": ("letter", "r", "l"),
    "an_ang": ("final", "an", "ang"), "ian_iang": ("final", "ian", "iang"), "uan_uang": ("final", "uan", "uang"),
    "en_eng": ("final", "en", "eng"), "in_ing": ("final", "in", "ing"), "u_v": ("u_v", "u", "v"),
}
LONGER_FINALS = {"an": ("ian", "uan"), "ang": ("iang", "uang")}
DRIFT_PER_DIRECTION = 25
QUOTAS = {
    "pinyin_neighbor": 150, "pinyin_omitted": 100, "pinyin_added": 100, "pinyin_swapped": 100,
    "pinyin_drift_word": DRIFT_PER_DIRECTION * len(layout_keys.DIRECTIONS),
    "pinyin_drift_partial": DRIFT_PER_DIRECTION * len(layout_keys.DIRECTIONS),
    **{f"pinyin_fuzzy_{name}": 50 for name in FUZZY_PAIRS},
    "pinyin_fuzzy_and_neighbor": 50,
    "pinyin_split_apostrophe": 60,
}
GROUPS = {
    "finger_slips": ["pinyin_neighbor", "pinyin_omitted", "pinyin_added", "pinyin_swapped"],
    "drift": ["pinyin_drift_word", "pinyin_drift_partial"],
    "fuzzy": [f"pinyin_fuzzy_{name}" for name in FUZZY_PAIRS],
    "mixed": ["pinyin_fuzzy_and_neighbor"],
    "split": ["pinyin_split_apostrophe"],
    "clean": ["pinyin_clean"],
}
GROUP_OF = {category: group for group, members in GROUPS.items() for category in members}


def substrings(text: str) -> set[str]:
    return {text[i:j] for i in range(len(text)) for j in range(i + CONTAINMENT_MINIMUM, len(text) + 1)}


def load_clauses(valid: set[str], reader: pinyin_reading.Reader) -> tuple[dict[str, list[dict]], dict]:
    """Clauses with the text before them in their sentence, by half."""
    used = set()
    for half in ("dev", "test"):
        for line in (CASES / f"pinyin.{half}.jsonl").read_text(encoding="utf-8").splitlines():
            if line:
                used.add(json.loads(line)["intended"])
    used_parts = set().union(*(substrings(text) for text in used))
    if not base.CACHE.exists():
        raise SystemExit(f"{base.CACHE} is missing: run scripts/typing-evaluation/build_pinyin_cases.py once to fetch it")
    to_simplified = OpenCC("t2s")
    halves = {"dev": [], "test": []}
    seen = set()
    counts = {"clauses": 0, "uncertain_reading": 0, "removed_existing_cases": 0, "removed_other_half": 0}
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
                syllables = reader.syllables(clause)
                if syllables is None:
                    counts["uncertain_reading"] += 1
                    continue
                if any(s not in valid or s in base.TWO_SPELLINGS for s in syllables):
                    continue
                counts["clauses"] += 1
                if clause in used_parts or any(part in used for part in substrings(clause)):
                    counts["removed_existing_cases"] += 1
                    continue
                half = "dev" if int(sentence_id) % 2 == 0 else "test"
                halves[half].append({"text": clause, "syllables": syllables, "context": text[:match.start()],
                                     "source": f"tatoeba:{sentence_id}"})
    # A clause that holds a clause of the other half, or stands inside one, leaves both halves.
    texts = {half: {c["text"] for c in clauses} for half, clauses in halves.items()}
    parts = {half: set().union(*(substrings(t) for t in found)) for half, found in texts.items()}
    shared = set()
    for half, other in (("dev", "test"), ("test", "dev")):
        for text in texts[half]:
            if text in parts[other] or any(part in texts[other] for part in substrings(text)):
                shared.add(text)
    for half in halves:
        before = len(halves[half])
        halves[half] = [c for c in halves[half] if c["text"] not in shared]
        counts["removed_other_half"] += before - len(halves[half])
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


def neighbor_in(syllables, layout, rng, places=None):
    s, i = rng.choice(places if places is not None else letter_places(syllables))
    syllable = syllables[s]
    return s, syllable[:i] + rng.choice(layout.neighbors[syllable[i]]) + syllable[i + 1:]


def neighbor_slip(syllables, layout, rng):
    s, changed = neighbor_in(syllables, layout, rng)
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


def drift_slip(partial: bool, direction: str):
    """Two neighboring syllables, the length of a common word, typed with the hand one key off
    in `direction`. A partial drift starts after the first letter of the first of them. A drift
    that types a key other than a letter makes no case."""
    def slip(syllables, layout, rng):
        if len(syllables) < 2:
            return None
        s = rng.randrange(len(syllables) - 1)
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


def fuzzy_swaps(name: str, valid: set[str]):
    kind, short, long = FUZZY_PAIRS[name]

    def swaps(syllable: str) -> list[str]:
        out = []
        if kind == "letter":
            # One letter each way at the start of the syllable.
            if syllable.startswith(short):
                out.append(long + syllable[1:])
            elif syllable.startswith(long):
                out.append(short + syllable[1:])
        elif kind == "initial":
            if syllable.startswith(long):
                out.append(short + syllable[len(long):])
            elif syllable.startswith(short):
                out.append(long + syllable[len(short):])
        elif kind == "u_v":
            # The sound ü after l and n, typed with "v", and the plain u.
            if syllable in ("lu", "nu"):
                out.append(syllable[0] + "v")
            elif syllable in ("lv", "nv"):
                out.append(syllable[0] + "u")
        else:
            for a, b in ((long, short), (short, long)):
                if syllable.endswith(a) and not any(syllable.endswith(x) for x in LONGER_FINALS.get(a, ())):
                    out.append(syllable[:-len(a)] + b)
                    break
        return [v for v in out if v in valid and v != syllable]
    return swaps


def fuzzy_slip(name: str, valid: set[str]):
    swaps = fuzzy_swaps(name, valid)

    def slip(syllables, layout, rng):
        options = [(s, v) for s, syllable in enumerate(syllables) for v in swaps(syllable)]
        if not options:
            return None
        s, swapped = rng.choice(options)
        return "".join(syllables[:s] + [swapped] + syllables[s + 1:]), {"syllable": s, "fuzzy_from": syllables[s],
                                                                        "fuzzy_to": swapped}
    return slip


def fuzzy_and_neighbor_slip(valid: set[str]):
    """A fuzzy swap in one syllable and a neighbor key in another syllable of the same clause."""
    every = {name: fuzzy_swaps(name, valid) for name in FUZZY_PAIRS}

    def slip(syllables, layout, rng):
        options = [(s, name, v) for s, syllable in enumerate(syllables) for name, swaps in every.items()
                   for v in swaps(syllable)]
        if not options or len(syllables) < 2:
            return None
        s, name, swapped = rng.choice(options)
        places = [(t, i) for t, i in letter_places(syllables) if t != s]
        t, changed = neighbor_in(syllables, layout, rng, places)
        out = syllables[:]
        out[s] = swapped
        out[t] = changed
        return "".join(out), {"syllable": s, "fuzzy_pair": name, "fuzzy_from": syllables[s], "fuzzy_to": swapped,
                              "neighbor_syllable": t}
    return slip


def first_break_apart(syllables: list[str], greedy: list[str]) -> int | None:
    """The first letter place where the intended cut has a break and the longest-first cut has
    none, or None."""
    position, intended_breaks = 0, set()
    for syllable in syllables:
        position += len(syllable)
        intended_breaks.add(position)
    position, greedy_breaks = 0, set()
    for syllable in greedy:
        position += len(syllable)
        greedy_breaks.add(position)
    missing = sorted(intended_breaks - greedy_breaks)
    return missing[0] if missing else None


def split_slip(valid: set[str]):
    """A clause whose letters the longest-first cut reads as other syllables, as "xian" for
    "xi an", typed with the apostrophe that marks the break, as in "xi'an"."""
    def slip(syllables, layout, rng):
        letters = "".join(syllables)
        greedy = greedy_split(letters, valid)
        if greedy is None or greedy == syllables:
            return None
        cut = first_break_apart(syllables, greedy)
        if cut is None:
            return None
        return letters[:cut] + "'" + letters[cut:], {"greedy_split": " ".join(greedy)}
    return slip


def build_half(half: str, clauses: list[dict], valid: set[str], layouts) -> tuple[list[dict], dict, int]:
    cases: list[dict] = []
    clean_of: dict[str, str] = {}
    shortfalls = {}

    def clean_case(clause) -> str:
        key = clause["text"]
        if key not in clean_of:
            case_id = f"zhtypo-{half}-pinyin_clean-{len(clean_of):04d}"
            clean_of[key] = case_id
            letters = "".join(clause["syllables"])
            greedy = greedy_split(letters, valid)
            case = {"id": case_id, "split": half, "category": "pinyin_clean", "group": "clean", "expected": "keep",
                    "context": clause["context"], "typed": letters, "intended": clause["text"],
                    "intended_pinyin": " ".join(clause["syllables"]), "source": clause["source"],
                    # Whether the longest-first cut of the letters gives other syllables than the
                    # intended ones, so the person needs a syllable break that the cut does not make.
                    "longest_first_cut_differs": greedy != clause["syllables"]}
            cases.append(case)
        return clean_of[key]

    runs = [
        ("pinyin_neighbor", None, neighbor_slip), ("pinyin_omitted", None, omitted_slip),
        ("pinyin_added", None, added_slip), ("pinyin_swapped", None, swapped_slip),
        *[("pinyin_drift_word", d, drift_slip(False, d)) for d in layout_keys.DIRECTIONS],
        *[("pinyin_drift_partial", d, drift_slip(True, d)) for d in layout_keys.DIRECTIONS],
        *[(f"pinyin_fuzzy_{name}", None, fuzzy_slip(name, valid)) for name in FUZZY_PAIRS],
        ("pinyin_fuzzy_and_neighbor", None, fuzzy_and_neighbor_slip(valid)),
        ("pinyin_split_apostrophe", None, split_slip(valid)),
    ]
    numbers: dict[str, int] = {}
    # Two slips can give the same letters, as a neighbor key and a fuzzy pair. A half holds each
    # (context, typed, intended) once.
    seen: set[tuple[str, str, str]] = set()
    repeated = 0
    for category, direction, maker in runs:
        quota = DRIFT_PER_DIRECTION if direction is not None else QUOTAS[category]
        label = f"{category} {direction}" if direction is not None else category
        rng = random.Random(f"{SEED}-{half}-{label}")
        order = clauses[:]
        rng.shuffle(order)
        made = 0
        for clause in order:
            letters = "".join(clause["syllables"])
            if len(letters) < base.SLIP_MINIMUM_LETTERS:
                continue
            layout = layouts[rng.choice(layout_keys.STYLES)]
            result = maker(clause["syllables"], layout, rng)
            if result is None:
                continue
            typed, fields = result
            if typed.replace("'", "") == letters and category != "pinyin_split_apostrophe":
                continue
            if (clause["context"], typed, clause["text"]) in seen:
                repeated += 1
                continue
            seen.add((clause["context"], typed, clause["text"]))
            twin = clean_case(clause)
            number = numbers.get(category, 0)
            numbers[category] = number + 1
            case = {"id": f"zhtypo-{half}-{category}-{number:04d}", "split": half, "category": category,
                    "group": GROUP_OF[category], "expected": "correct", "context": clause["context"], "typed": typed,
                    "intended": clause["text"], "intended_pinyin": " ".join(clause["syllables"]),
                    "typed_parses_exactly": base.parses_exactly(typed.replace("'", ""), valid),
                    "source": clause["source"], "layout": layout.name, "twin": twin}
            case.update(fields)
            cases.append(case)
            made += 1
            if made == quota:
                break
        else:
            shortfalls[label] = {"wanted": quota, "made": made}
    return cases, shortfalls, repeated


def main():
    valid = base.standard_syllables()
    reader = pinyin_reading.Reader()
    clauses, counts = load_clauses(valid, reader)
    layouts = layout_keys.both()
    report = {"seed": SEED, "pool": counts, "halves": {}}
    for half in ("dev", "test"):
        cases, shortfalls, repeated = build_half(half, clauses[half], valid, layouts)
        path = CASES / f"pinyin-typos.{half}.jsonl"
        path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")
        tally: dict[str, int] = {}
        for case in cases:
            tally[case["category"]] = tally.get(case["category"], 0) + 1
        clean = [c for c in cases if c["category"] == "pinyin_clean"]
        report["halves"][half] = {"cases": len(cases), "categories": tally, "shortfalls": shortfalls,
                                  "skipped_as_a_repeated_case": repeated,
                                  "clean_cases_whose_longest_first_cut_differs":
                                      sum(c["longest_first_cut_differs"] for c in clean),
                                  "slip_cases_whose_typed_letters_parse_exactly":
                                      sum(1 for c in cases if c.get("typed_parses_exactly"))}
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

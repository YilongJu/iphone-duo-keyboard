"""Builds the generated English cases of the typo set: cases/english-typos.dev.jsonl and
cases/english-typos.test.jsonl. docs/typo-set-design.md describes every rule.

A case holds the words before the cursor (`context`), the keys a person typed (`typed`), and the
text the person meant (`intended`). `expected` says what a keyboard must do: "correct" when the
typed keys hold a slip, and "keep" when they are the intended text. `typed` can end with one or
two more words typed right (`follow`), because the keyboard reads the word before again when it
corrects the next word.

The slips use the real keys of the keyboard's two layouts (layout_keys.py). Each case names its
layout. A drift case also names its direction, its sideways part and the first drifted letter.

Sources:
- Sentences: Tatoeba English export, CC BY 2.0 FR, https://tatoeba.org.
- Word frequencies: the wordfreq package (Zipf scale), data under CC BY-SA 4.0.

Splits: a sentence with an even Tatoeba id feeds the dev half and one with an odd id the test
half. The test half is for decisions only.

Leakage: a sentence leaves the pool when a language-model training, stopping or tuning case
holds its Tatoeba id or its words (leakage.py), and when an existing English case file of
scripts/typing-evaluation/cases names it as its source. The report counts both.

Usage, from the repository root, with the training files of scripts/lm-domain and
scripts/lm-finetune2 that their builders wrote to build/:
    uv run --with wordfreq python scripts/typing-evaluation/typo-set/build_english_typos.py \
        --lm-domain-data PATH/build/lm-domain/data --lm-finetune2-data PATH/build/lm-finetune2/data
"""
import argparse
import bz2
import hashlib
import json
import random
import re
import sys
import urllib.request
from pathlib import Path

from wordfreq import top_n_list, zipf_frequency

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import layout_keys  # noqa: E402
import leakage  # noqa: E402

ROOT = HERE.parents[2]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
REPORTS = HERE / "reports"
CACHE = ROOT / "build" / "typing-evaluation" / "eng_sentences.tsv.bz2"
SOURCE_URL = "https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences.tsv.bz2"
SEED = "typo-set-20261114"
# The existing English case files. Their sentences stay out of this set.
EXISTING = ["english", "english-symbols", "english-apostrophe-words", "english-domain", "english-domain-stream"]

WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
PUNCTUATION = ",.?!"
# A target word that any keyboard's word list holds.
TARGET_MINIMUM_ZIPF = 3.5
# A slip whose typed text is a real word this common is a real-word slip, which needs the
# sentence. The slip categories leave those out, as build_english_cases.py does.
TYPED_MAXIMUM_ZIPF = 3.0
INTENDED_OVER_TYPED_ZIPF = 2.0
COMMON_WORD_ZIPF = 4.0
SHORT_WORD_MINIMUM_ZIPF = 5.0
VERY_COMMON_ZIPF = 5.5
# A keep case: a real word that one slip of the layout turns into a word this much more common.
NEAR_COMMON_GAP = 1.5
NEAR_COMMON_MINIMUM_ZIPF = 3.0
LISTED_MAXIMUM_ZIPF = 3.2
# One typed text appears at most this often in one category.
REPEATS = 3
# The apostrophe categories have few typed words, each typed in many sentences, so one typed
# word may appear this often there.
APOSTROPHE_REPEATS = 20
# Keys that end a word in the keyboard. A drift onto them would end the word early, so a drift
# case never types them.
WORD_ENDING_KEYS = set(",.;")

# Hand-listed slips of common short words: the user's reports ("thst", "teh", "adn", "jsut")
# and slips of the same kind. wordfreq counts some common misspellings as words ("teh" is at
# 3.04), so a listed typed text needs only to stay below LISTED_MAXIMUM_ZIPF, which the builder
# checks. "amd" and "fro" stay out, because both are real words.
LISTED = [
    ("thst", "that"), ("taht", "that"), ("thta", "that"), ("tht", "that"), ("rhat", "that"),
    ("teh", "the"), ("hte", "the"), ("thw", "the"), ("rhe", "the"), ("tge", "the"), ("yhe", "the"),
    ("thr", "the"), ("adn", "and"), ("nad", "and"), ("abd", "and"),
    ("jsut", "just"), ("jist", "just"), ("yuo", "you"), ("ypu", "you"), ("yoy", "you"), ("tou", "you"),
    ("gor", "for"), ("woth", "with"), ("wiht", "with"), ("eith", "with"),
    ("thsi", "this"), ("tihs", "this"), ("thid", "this"), ("tjis", "this"), ("rhis", "this"),
    ("waht", "what"), ("whta", "what"), ("whst", "what"), ("wjat", "what"),
    ("thnk", "think"), ("knwo", "know"), ("konw", "know"), ("hwo", "how"), ("wnat", "want"),
    ("liek", "like"), ("ahve", "have"), ("hvae", "have"), ("cna", "can"), ("nto", "not"),
    ("becuase", "because"), ("waz", "was"), ("wsa", "was"), ("jave", "have"), ("abour", "about"),
]
# Contractions whose form without the apostrophe is not a common word of its own.
UNAMBIGUOUS_CONTRACTIONS = [
    "don't", "can't", "i'm", "i've", "you're", "they're", "doesn't", "isn't", "didn't", "wasn't",
    "weren't", "aren't", "haven't", "hasn't", "hadn't", "couldn't", "wouldn't", "shouldn't",
    "that's", "what's", "there's", "you've", "we've", "they've", "you'll", "they'll", "she's", "he's",
]
# Pairs where both forms are real words: the keyboard needs the words around them.
AMBIGUOUS_PAIRS = [("well", "we'll"), ("its", "it's"), ("were", "we're"), ("ill", "i'll"),
                   ("wont", "won't"), ("hell", "he'll"), ("shell", "she'll")]

# Cases per category and half.
QUOTAS = {
    **{f"drift_full_{d}": 60 for d in layout_keys.DIRECTIONS},
    **{f"drift_partial_{d}": 60 for d in layout_keys.DIRECTIONS},
    "drift_phrase": 60,
    "short_word_neighbor": 150, "short_word_transposition": 100, "short_word_listed": 150,
    "apostrophe_missing": 200,
    "letter_omitted": 120, "letter_added": 120, "letter_doubled": 120, "letters_swapped": 120,
    "space_missing_common": 120, "space_extra": 120,
    "punctuation_after_slip": 120,
    "keep_near_common": 150, "keep_clean_short": 120, "keep_clean_punctuation": 80,
}
# Per pair and direction, so each of the 7 pairs gets the same weight.
AMBIGUOUS_PER_PAIR = 20
GROUPS = {
    "drift": [c for c in QUOTAS if c.startswith("drift")],
    "short_words": ["short_word_neighbor", "short_word_transposition", "short_word_listed"],
    "apostrophe": ["apostrophe_missing"],
    "letter_slips": ["letter_omitted", "letter_added", "letter_doubled", "letters_swapped"],
    "space_slips": ["space_missing_common", "space_extra"],
    "punctuation": ["punctuation_after_slip"],
    "keep": ["keep_near_common", "keep_clean_short", "keep_clean_punctuation"],
    "ambiguous": ["ambiguous_apostrophe_keep", "ambiguous_apostrophe_correct"],
}
GROUP_OF = {category: group for group, members in GROUPS.items() for category in members}


def zipf(word: str) -> float:
    return zipf_frequency(word, "en")


def tokenize(text: str) -> list[tuple[str, str]] | None:
    """The words of a sentence in lower case, each with the mark right after it (",", ".", "?",
    "!" or ""), or None when the sentence holds any other sign."""
    tokens = []
    for raw in text.lower().replace("’", "'").split():
        mark = ""
        if raw[-1:] in PUNCTUATION:
            mark = raw[-1]
            raw = raw[:-1]
        if not WORD.fullmatch(raw):
            return None
        tokens.append((raw, mark))
    return tokens


def existing_sources() -> set[str]:
    sources = set()
    for name in EXISTING:
        for half in ("dev", "test"):
            for line in (CASES / f"{name}.{half}.jsonl").read_text(encoding="utf-8").splitlines():
                if line:
                    source = json.loads(line).get("source", "")
                    if source.startswith("tatoeba:"):
                        sources.add(source)
    return sources


def load_pool(training: leakage.TrainingTexts, report: dict) -> dict[str, list[tuple[str, list[tuple[str, str]]]]]:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(SOURCE_URL, CACHE)
    report["tatoeba_export_sha256"] = hashlib.sha256(CACHE.read_bytes()).hexdigest()
    vocabulary = set(top_n_list("en", 60000))
    used = existing_sources()
    halves = {"dev": [], "test": []}
    counts = {"passing_filter": 0, "removed_training": 0, "removed_existing_cases": 0}
    with bz2.open(CACHE, "rt", encoding="utf-8") as lines:
        for line in lines:
            sentence_id, _, text = line.rstrip("\n").split("\t", 2)
            if not text.isascii():
                continue
            tokens = tokenize(text)
            if tokens is None or not 4 <= len(tokens) <= 14 or any(w not in vocabulary for w, _ in tokens):
                continue
            # A mark inside the sentence other than a comma would start a new sentence.
            if any(mark not in ("", ",") for _, mark in tokens[:-1]):
                continue
            counts["passing_filter"] += 1
            source = f"tatoeba:{sentence_id}"
            if training.leaks(source, " ".join(w for w, _ in tokens)):
                counts["removed_training"] += 1
                continue
            if source in used:
                counts["removed_existing_cases"] += 1
                continue
            halves["dev" if int(sentence_id) % 2 == 0 else "test"].append((source, tokens))
    report["pool"] = counts | {"dev": len(halves["dev"]), "test": len(halves["test"])}
    return halves


# ---- Slip makers. Each returns the typed word, or None. ----

def neighbor_substitution(word: str, layout: layout_keys.Layout, rng: random.Random) -> str:
    index = rng.randrange(len(word))
    return word[:index] + rng.choice(layout.neighbors[word[index]]) + word[index + 1:]


def omission(word: str, layout, rng: random.Random) -> str | None:
    if len(word) < 3:
        return None
    index = rng.randrange(len(word))
    return word[:index] + word[index + 1:]


def added_neighbor(word: str, layout: layout_keys.Layout, rng: random.Random) -> str:
    index = rng.randrange(len(word))
    extra = rng.choice(layout.neighbors[word[index]])
    at = index + rng.choice((0, 1))
    return word[:at] + extra + word[at:]


def doubled(word: str, layout, rng: random.Random) -> str:
    index = rng.randrange(len(word))
    return word[:index] + word[index] + word[index:]


def swapped(word: str, layout, rng: random.Random) -> str | None:
    places = [i for i in range(len(word) - 1) if word[i] != word[i + 1]]
    if not places:
        return None
    index = rng.choice(places)
    return word[:index] + word[index + 1] + word[index] + word[index + 2:]


LETTER_SLIPS = {"letter_omitted": omission, "letter_added": added_neighbor, "letter_doubled": doubled,
                "letters_swapped": swapped}


def fair(typed: str | None, intended: str) -> bool:
    return (typed is not None and typed != intended and zipf(typed) < TYPED_MAXIMUM_ZIPF
            and zipf(intended) - zipf(typed) >= INTENDED_OVER_TYPED_ZIPF)


def one_slip_variants(word: str, layout: layout_keys.Layout) -> set[str]:
    """Every text that one slip of the layout makes from `word`: a neighbor key, a letter left
    out, an extra neighbor key, a doubled letter, or two letters swapped."""
    out = set()
    for i, letter in enumerate(word):
        for other in layout.neighbors[letter]:
            out.add(word[:i] + other + word[i + 1:])
            out.add(word[:i] + other + word[i:])
            out.add(word[:i + 1] + other + word[i + 1:])
        out.add(word[:i] + word[i + 1:])
        out.add(word[:i] + letter + word[i:])
        if i + 1 < len(word) and word[i] != word[i + 1]:
            out.add(word[:i] + word[i + 1] + word[i] + word[i + 2:])
    out.discard(word)
    return out


class Builder:
    def __init__(self, half: str, pool: list, layouts: dict[str, layout_keys.Layout]):
        self.half = half
        self.pool = pool
        self.layouts = layouts
        self.cases: list[dict] = []
        self.shortfalls: dict[str, dict] = {}

    def add(self, category: str, number: int, source: str, context: str, typed: str, intended: str,
            expected: str, **fields) -> None:
        case = {"id": f"entypo-{self.half}-{category}-{number:04d}", "split": self.half, "category": category,
                "group": GROUP_OF[category], "expected": expected, "context": context, "typed": typed,
                "intended": intended, "source": source}
        case.update(fields)
        self.cases.append(case)

    def follow_words(self, tokens, end: int, rng: random.Random) -> list[str]:
        """Zero, one or two words after place `end`, typed right. Half the cases get some. A
        word after a mark stays out, so the follow words stay inside one clause."""
        if rng.random() < 0.5:
            return []
        wanted = rng.choice((1, 2))
        if tokens[end][1] not in ("", ","):
            return []
        words = []
        for word, mark in tokens[end + 1:end + 1 + wanted]:
            words.append(word)
            if mark:
                break
        return words

    def run(self, category: str, quota: int, maker, expected: str, repeat_limit: int = REPEATS) -> None:
        """Draws sentences in a seeded order and lets `maker` make one case of each, until the
        quota is full. `maker(tokens, rng, layout)` returns (index, typed word, intended word,
        mark, fields) for the word at `index`, or None."""
        rng = random.Random(f"{SEED}-{self.half}-{category}")
        order = self.pool[:]
        rng.shuffle(order)
        number = 0
        repeats: dict[str, int] = {}
        for source, tokens in order:
            layout = self.layouts[rng.choice(layout_keys.STYLES)]
            made = maker(tokens, rng, layout)
            if made is None:
                continue
            start, end, typed, intended, fields = made
            if repeats.get(typed, 0) >= repeat_limit:
                continue
            follow = self.follow_words(tokens, end, rng)
            # A mark at the end of the slip word stays; the follow words come after its space.
            typed_text = " ".join([typed] + follow)
            intended_text = " ".join([intended] + follow)
            context = " ".join(word for word, _ in tokens[:start])
            repeats[typed] = repeats.get(typed, 0) + 1
            self.add(category, number, source, context, typed_text, intended_text, expected,
                     layout=layout.name, follow=len(follow), **fields)
            number += 1
            if number == quota:
                return
        self.shortfalls[category] = {"wanted": quota, "made": number}


def pick_word(tokens, rng, test) -> int | None:
    """A random place whose word passes `test`, or None."""
    places = [i for i, (word, mark) in enumerate(tokens) if test(word, mark, i)]
    return rng.choice(places) if places else None


def plain(word: str) -> bool:
    return word.isalpha()


def drift_maker(direction: str, partial: bool):
    def maker(tokens, rng, layout):
        minimum = 4 if partial else 3
        index = pick_word(tokens, rng, lambda w, m, i: plain(w) and len(w) >= minimum and zipf(w) >= TARGET_MINIMUM_ZIPF)
        if index is None:
            return None
        word, mark = tokens[index]
        sideways = rng.choice(layout_keys.SIDEWAYS) if direction in ("up", "down") else 0.0
        # A partial drift starts inside the word and moves two letters or more.
        start = rng.randint(1, len(word) - 2) if partial else 0
        typed = layout.drift_text(word, direction, sideways, start)
        if typed is None or WORD_ENDING_KEYS & set(typed) or typed == word or zipf(typed) >= TYPED_MAXIMUM_ZIPF:
            return None
        return index, index, typed + mark, word + mark, {"direction": direction, "sideways": sideways, "drift_start": start}
    return maker


def drift_phrase_maker(tokens, rng, layout):
    places = [i for i in range(len(tokens) - 1)
              if plain(tokens[i][0]) and plain(tokens[i + 1][0]) and not tokens[i][1]
              and min(zipf(tokens[i][0]), zipf(tokens[i + 1][0])) >= TARGET_MINIMUM_ZIPF
              and len(tokens[i][0]) + len(tokens[i + 1][0]) >= 6]
    if not places:
        return None
    index = rng.choice(places)
    direction = rng.choice(layout_keys.DIRECTIONS)
    sideways = rng.choice(layout_keys.SIDEWAYS) if direction in ("up", "down") else 0.0
    phrase = tokens[index][0] + " " + tokens[index + 1][0]
    typed = layout.drift_text(phrase, direction, sideways)
    if typed is None or WORD_ENDING_KEYS & set(typed) or any(zipf(part) >= TYPED_MAXIMUM_ZIPF for part in typed.split(" ")):
        return None
    mark = tokens[index + 1][1]
    return index, index + 1, typed + mark, phrase + mark, {"direction": direction, "sideways": sideways, "drift_start": 0}


def short_word_maker(slip):
    def maker(tokens, rng, layout):
        index = pick_word(tokens, rng, lambda w, m, i: plain(w) and 3 <= len(w) <= 5 and zipf(w) >= SHORT_WORD_MINIMUM_ZIPF)
        if index is None:
            return None
        word, mark = tokens[index]
        typed = slip(word, layout, rng)
        if not fair(typed, word):
            return None
        return index, index, typed + mark, word + mark, {}
    return maker


def listed_maker():
    by_word: dict[str, list[str]] = {}
    for typed, intended in LISTED:
        if zipf(typed) >= LISTED_MAXIMUM_ZIPF:
            raise SystemExit(f"the listed slip {typed!r} is a common word")
        by_word.setdefault(intended, []).append(typed)

    def maker(tokens, rng, layout):
        index = pick_word(tokens, rng, lambda w, m, i: w in by_word)
        if index is None:
            return None
        word, mark = tokens[index]
        typed = rng.choice(by_word[word])
        return index, index, typed + mark, word + mark, {"pair": f"{typed}/{word}"}
    return maker


def apostrophe_maker(tokens, rng, layout):
    index = pick_word(tokens, rng, lambda w, m, i: w in UNAMBIGUOUS_CONTRACTIONS)
    if index is None:
        return None
    word, mark = tokens[index]
    typed = word.replace("'", "")
    return index, index, typed + mark, word + mark, {"pair": f"{typed}/{word}"}


def letter_maker(slip):
    def maker(tokens, rng, layout):
        index = pick_word(tokens, rng, lambda w, m, i: plain(w) and len(w) >= 3 and zipf(w) >= TARGET_MINIMUM_ZIPF)
        if index is None:
            return None
        word, mark = tokens[index]
        typed = slip(word, layout, rng)
        if not fair(typed, word):
            return None
        return index, index, typed + mark, word + mark, {}
    return maker


def space_missing_maker(tokens, rng, layout):
    places = [i for i in range(len(tokens) - 1)
              if plain(tokens[i][0]) and plain(tokens[i + 1][0]) and not tokens[i][1]
              and min(zipf(tokens[i][0]), zipf(tokens[i + 1][0])) >= VERY_COMMON_ZIPF]
    if not places:
        return None
    index = rng.choice(places)
    typed = tokens[index][0] + tokens[index + 1][0]
    if zipf(typed) >= TYPED_MAXIMUM_ZIPF:
        return None
    mark = tokens[index + 1][1]
    return index, index + 1, typed + mark, tokens[index][0] + " " + tokens[index + 1][0] + mark, {}


def space_extra_maker(tokens, rng, layout):
    index = pick_word(tokens, rng, lambda w, m, i: plain(w) and len(w) >= 4 and zipf(w) >= TARGET_MINIMUM_ZIPF)
    if index is None:
        return None
    word, mark = tokens[index]
    cut = rng.randint(1, len(word) - 1)
    left, right = word[:cut], word[cut:]
    if zipf(left) >= COMMON_WORD_ZIPF and zipf(right) >= COMMON_WORD_ZIPF:
        return None
    return index, index, left + " " + right + mark, word + mark, {}


def punctuation_maker(tokens, rng, layout):
    index = pick_word(tokens, rng, lambda w, m, i: m != "" and plain(w) and len(w) >= 3 and zipf(w) >= TARGET_MINIMUM_ZIPF)
    if index is None:
        return None
    word, mark = tokens[index]
    slip = rng.choice([neighbor_substitution, omission, added_neighbor, swapped])
    typed = slip(word, layout, rng)
    if not fair(typed, word):
        return None
    return index, index, typed + mark, word + mark, {"mark": mark}


def keep_near_common_maker(tokens, rng, layout):
    def test(word, mark, index):
        if not plain(word) or len(word) < 3 or zipf(word) < NEAR_COMMON_MINIMUM_ZIPF:
            return False
        return any(zipf(v) >= zipf(word) + NEAR_COMMON_GAP for v in one_slip_variants(word, layout))
    index = pick_word(tokens, rng, test)
    if index is None:
        return None
    word, mark = tokens[index]
    nearer = max(one_slip_variants(word, layout), key=lambda v: (zipf(v), v))
    return index, index, word + mark, word + mark, {"near": nearer}


def keep_short_maker(tokens, rng, layout):
    index = pick_word(tokens, rng, lambda w, m, i: plain(w) and 2 <= len(w) <= 5 and zipf(w) >= SHORT_WORD_MINIMUM_ZIPF)
    if index is None:
        return None
    word, mark = tokens[index]
    return index, index, word + mark, word + mark, {}


def keep_punctuation_maker(tokens, rng, layout):
    index = pick_word(tokens, rng, lambda w, m, i: m != "" and plain(w) and len(w) >= 2)
    if index is None:
        return None
    word, mark = tokens[index]
    return index, index, word + mark, word + mark, {"mark": mark}


def ambiguous_maker(plain_word: str, contraction: str, direction: str):
    """direction "keep": the sentence holds the plain word, typed right. "correct": the sentence
    holds the contraction, typed without its apostrophe."""
    wanted = plain_word if direction == "keep" else contraction

    def maker(tokens, rng, layout):
        index = pick_word(tokens, rng, lambda w, m, i: w == wanted)
        if index is None:
            return None
        word, mark = tokens[index]
        return index, index, plain_word + mark, word + mark, {"pair": f"{plain_word}/{contraction}", "ambiguous": True}
    return maker


def build_half(half: str, pool: list, layouts) -> tuple[list[dict], dict]:
    builder = Builder(half, pool, layouts)
    for direction in layout_keys.DIRECTIONS:
        builder.run(f"drift_full_{direction}", QUOTAS[f"drift_full_{direction}"], drift_maker(direction, False), "correct")
        builder.run(f"drift_partial_{direction}", QUOTAS[f"drift_partial_{direction}"], drift_maker(direction, True), "correct")
    builder.run("drift_phrase", QUOTAS["drift_phrase"], drift_phrase_maker, "correct")
    builder.run("short_word_neighbor", QUOTAS["short_word_neighbor"], short_word_maker(neighbor_substitution), "correct")
    builder.run("short_word_transposition", QUOTAS["short_word_transposition"], short_word_maker(swapped), "correct")
    builder.run("short_word_listed", QUOTAS["short_word_listed"], listed_maker(), "correct")
    builder.run("apostrophe_missing", QUOTAS["apostrophe_missing"], apostrophe_maker, "correct", APOSTROPHE_REPEATS)
    for category, slip in LETTER_SLIPS.items():
        builder.run(category, QUOTAS[category], letter_maker(slip), "correct")
    builder.run("space_missing_common", QUOTAS["space_missing_common"], space_missing_maker, "correct")
    builder.run("space_extra", QUOTAS["space_extra"], space_extra_maker, "correct")
    builder.run("punctuation_after_slip", QUOTAS["punctuation_after_slip"], punctuation_maker, "correct")
    builder.run("keep_near_common", QUOTAS["keep_near_common"], keep_near_common_maker, "keep")
    builder.run("keep_clean_short", QUOTAS["keep_clean_short"], keep_short_maker, "keep")
    builder.run("keep_clean_punctuation", QUOTAS["keep_clean_punctuation"], keep_punctuation_maker, "keep")
    # The ambiguous pairs share two categories. Numbers run on inside each category.
    for direction, category in (("keep", "ambiguous_apostrophe_keep"), ("correct", "ambiguous_apostrophe_correct")):
        start = len(builder.cases)
        for plain_word, contraction in AMBIGUOUS_PAIRS:
            # "wont" as a word of its own ("he is wont to") is rare, and most Tatoeba sentences
            # with "wont" hold a slip of "won't". So "wont" gets no keep case.
            if direction == "keep" and plain_word == "wont":
                continue
            sub = Builder(half, pool, layouts)
            sub.run(category, AMBIGUOUS_PER_PAIR, ambiguous_maker(plain_word, contraction, direction), direction,
                    APOSTROPHE_REPEATS)
            for case in sub.cases:
                builder.cases.append(case)
            if sub.shortfalls:
                builder.shortfalls[f"{category} {plain_word}/{contraction}"] = sub.shortfalls[category]
        for number, case in enumerate(builder.cases[start:]):
            case["id"] = f"entypo-{half}-{category}-{number:04d}"
    return builder.cases, builder.shortfalls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm-domain-data", type=Path, required=True)
    parser.add_argument("--lm-finetune2-data", type=Path, required=True)
    arguments = parser.parse_args()
    training = leakage.TrainingTexts(arguments.lm_domain_data, arguments.lm_finetune2_data)
    report = {"seed": SEED, "training": training.report()}
    pool = load_pool(training, report)
    layouts = layout_keys.both()
    report["halves"] = {}
    for half in ("dev", "test"):
        cases, shortfalls = build_half(half, pool[half], layouts)
        ids = [case["id"] for case in cases]
        if len(ids) != len(set(ids)):
            raise SystemExit(f"{half}: two cases share an id")
        path = CASES / f"english-typos.{half}.jsonl"
        path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")
        counts: dict[str, int] = {}
        for case in cases:
            counts[case["category"]] = counts.get(case["category"], 0) + 1
        pair_overlap = sum(1 for case in cases if case["expected"] == "correct"
                           and (case["typed"].split(" ")[0].strip(PUNCTUATION), case["intended"].split(" ")[0].strip(PUNCTUATION))
                           in training.pairs)
        report["halves"][half] = {"cases": len(cases), "categories": counts, "shortfalls": shortfalls,
                                  "slip_cases_whose_first_word_pair_a_training_case_holds": pair_overlap}
        print(f"wrote {path.relative_to(ROOT)}: {len(cases)} cases")
        for category, count in counts.items():
            sample = next(case for case in cases if case["category"] == category)
            print(f"  {category:30s} {count:4d}   e.g. [{sample['context']}] {sample['typed']!r} -> {sample['intended']!r}")
        if shortfalls:
            print("  shortfalls:", shortfalls)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "english-typos-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

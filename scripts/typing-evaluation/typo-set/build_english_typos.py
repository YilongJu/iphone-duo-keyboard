"""Builds the generated English cases of the typo set: cases/english-typos.{dev,test}.jsonl and
cases/english-typos-capitals.{dev,test}.jsonl. docs/typo-set-design.md describes every rule.

A case holds the words before the cursor (`context`), the keys a person typed (`typed`), and the
text the person meant (`intended`). `expected` says what a keyboard must do: "correct" when the
typed keys hold a slip, and "keep" when they are the intended text. `typed` can end with one or
two more words typed right (`follow`), because the keyboard reads the word before again when it
corrects the next word.

The slips use the real keys of the keyboard's two layouts (layout_keys.py). Each case names its
layout. A drift case also names its direction, its sideways part and the first drifted letter.

english-typos-capitals holds cases of the short-word and apostrophe categories in sentence case,
as a field that capitalizes sentences shows them: the context starts with a capital and has "I",
and a slip word that opens the field starts with a capital, as "Dont" and "Thst".

Sources:
- Sentences: Tatoeba English export, CC BY 2.0 FR, https://tatoeba.org.
- Word frequencies: the wordfreq package (Zipf scale), data under CC BY-SA 4.0.

Splits: a sentence with an even Tatoeba id feeds the dev half and one with an odd id the test
half. The test half is for decisions only. When the two halves give cases with the same
sentence start (the context and the intended slip text), the SHA-256 value of that start picks
the one half that keeps it, and the other half draws again.

Leakage: a sentence leaves the pool when a language-model file holds its Tatoeba id, its words,
or its words but one (leakage.py), and when an existing English case file of
scripts/typing-evaluation/cases names it as its source. The report counts each reason.

Usage, from the repository root, with the language-model files of scripts/lm-domain and
scripts/lm-finetune2 that their builders wrote to build/:
    uv run --with wordfreq==3.1.1 python scripts/typing-evaluation/typo-set/build_english_typos.py \
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
sys.path.insert(0, str(ROOT / "scripts" / "typing-evaluation"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
from rerank import correctable_word  # noqa: E402

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
# One typed word appears at most this often in one category.
REPEATS = 3
# The apostrophe categories have few typed words, each typed in many sentences, so one typed
# word may appear this often there.
APOSTROPHE_REPEATS = 20
# Keys that end a word in the keyboard. A drift onto them would end the word early, so a drift
# case never types them.
WORD_ENDING_KEYS = set(",.;")
# A case whose context and intended text equal those of a language-model case leaves the set
# when its context has this many words or more. A shorter start, as "i dont", is in every text.
MODEL_START_MINIMUM_CONTEXT_WORDS = 2

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
# Contractions whose form without the apostrophe has no common meaning of its own. wordfreq
# still gives many of these forms a high score ("dont" is at 4.74), because people type them
# without the apostrophe. "cant" is also a rare English word.
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
    "drift_end_two": 60, "drift_phrase": 60, "drift_run_on": 60, "drift_onto_symbols": 60,
    "short_word_neighbor": 150, "short_word_transposition": 100, "short_word_listed": 150,
    "short_word_listed_next": 150,
    "apostrophe_missing": 200,
    "letter_neighbor": 120, "letter_omitted": 120, "letter_added": 120, "letter_doubled": 120, "letters_swapped": 120,
    "drift_then_slip": 60, "drift_and_omission": 60,
    "space_missing_common": 120, "space_extra": 120,
    "punctuation_after_slip": 120,
    "keep_near_common": 150, "keep_clean_short": 120, "keep_clean_punctuation": 80,
}
# Per pair and direction, so each of the 7 pairs gets the same weight.
AMBIGUOUS_PER_PAIR = 20
GROUPS = {
    "drift": [f"drift_{kind}_{d}" for kind in ("full", "partial") for d in layout_keys.DIRECTIONS]
    + ["drift_end_two", "drift_phrase", "drift_run_on"],
    "drift_symbols": ["drift_onto_symbols"],
    "short_words": ["short_word_neighbor", "short_word_transposition", "short_word_listed", "short_word_listed_next"],
    "apostrophe": ["apostrophe_missing"],
    "letter_slips": ["letter_neighbor", "letter_omitted", "letter_added", "letter_doubled", "letters_swapped"],
    "mixed": ["drift_then_slip", "drift_and_omission"],
    "space_slips": ["space_missing_common", "space_extra"],
    "punctuation": ["punctuation_after_slip"],
    "keep": ["keep_near_common", "keep_clean_short", "keep_clean_punctuation"],
    "ambiguous": ["ambiguous_apostrophe_keep", "ambiguous_apostrophe_correct"],
}
GROUP_OF = {category: group for group, members in GROUPS.items() for category in members}
# The categories that the sentence-case file holds.
CAPITALS_CATEGORIES = ["short_word_listed", "short_word_listed_next", "apostrophe_missing",
                       "ambiguous_apostrophe_correct", "ambiguous_apostrophe_keep"]


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
    counts = {"passing_filter": 0, "removed_existing_cases": 0}
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
            reason = training.leak_reason(source, " ".join(w for w, _ in tokens))
            if reason is not None:
                key = "removed_" + reason.replace(" ", "_")
                counts[key] = counts.get(key, 0) + 1
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


LETTER_SLIPS = {"letter_neighbor": neighbor_substitution, "letter_omitted": omission, "letter_added": added_neighbor,
                "letter_doubled": doubled, "letters_swapped": swapped}
ONE_LETTER_SLIPS = [neighbor_substitution, omission, added_neighbor, swapped]


def fair(typed: str | None, intended: str) -> bool:
    return (typed is not None and typed != intended and zipf(typed) < TYPED_MAXIMUM_ZIPF
            and zipf(intended) - zipf(typed) >= INTENDED_OVER_TYPED_ZIPF)


def fair_words(typed: str, intended: str) -> bool:
    """`fair` for each changed word of two texts with the same count of words."""
    pairs = list(zip(typed.split(" "), intended.split(" ")))
    return (len(typed.split(" ")) == len(intended.split(" ")) and any(a != b for a, b in pairs)
            and all(a == b or fair(a, b) for a, b in pairs))


def letters_only(typed: str) -> bool:
    return typed.replace(" ", "").isalpha() and typed.isascii()


def one_slip_variants(word: str, layout: layout_keys.Layout) -> set[str]:
    """Every text that one slip of the layout makes from `word`: a neighbor key, a letter left
    out, an extra neighbor key, a doubled letter, or two letters swapped."""
    out = set()
    for i, letter in enumerate(word):
        for other in layout.neighbors.get(letter, ()):
            out.add(word[:i] + other + word[i + 1:])
            out.add(word[:i] + other + word[i:])
            out.add(word[:i + 1] + other + word[i + 1:])
        out.add(word[:i] + word[i + 1:])
        out.add(word[:i] + letter + word[i:])
        if i + 1 < len(word) and word[i] != word[i + 1]:
            out.add(word[:i] + word[i + 1] + word[i] + word[i + 2:])
    out.discard(word)
    return out


def rival_of(typed: str, intended: str, layout: layout_keys.Layout) -> str | None:
    """A word one slip from a changed typed word that is at least as common as the intended
    word, as "who" for "hwo" typed for "how". Such a slip needs the words around it."""
    typed_words, intended_words = typed.split(" "), intended.split(" ")
    if len(typed_words) != len(intended_words):
        return None
    best = None
    for a, b in zip(typed_words, intended_words):
        a, b = a.rstrip(PUNCTUATION), b.rstrip(PUNCTUATION)
        if a == b or not a.isalpha():
            continue
        for variant in one_slip_variants(a, layout):
            if variant != b and zipf(variant) >= zipf(b) and (best is None or zipf(variant) > zipf(best)):
                best = variant
    return best


def start_key(context: str, intended: str) -> str:
    """The sentence start of a case: its context and the intended slip text, without the follow
    words. Two halves never share one."""
    return leakage.words_of(context + " " + intended)


def owner_of(key: str) -> str:
    return "dev" if hashlib.sha256(key.encode()).digest()[0] % 2 == 0 else "test"


class Builder:
    def __init__(self, half: str, pool: list, layouts: dict[str, layout_keys.Layout], excluded: set,
                 training: leakage.TrainingTexts, seen: set, skipped: dict):
        """`excluded` holds the sentence starts that the other half keeps. `seen` holds the
        (context, typed, intended) triples of this half, so no case repeats in a half."""
        self.half = half
        self.pool = pool
        self.layouts = layouts
        self.excluded = excluded
        self.training = training
        self.seen = seen
        self.skipped = skipped
        self.cases: list[dict] = []
        self.starts: set[str] = set()
        self.shortfalls: dict[str, dict] = {}

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def add(self, category: str, number: int, source: str, context: str, typed: str, intended: str,
            expected: str, **fields) -> None:
        case = {"id": f"entypo-{self.half}-{category}-{number:04d}", "split": self.half, "category": category,
                "group": GROUP_OF[category], "expected": expected, "context": context, "typed": typed,
                "intended": intended, "source": source}
        case.update(fields)
        self.cases.append(case)

    def follow_words(self, tokens, end: int, rng: random.Random, forced: bool) -> list[str]:
        """Zero, one or two words after place `end`, typed right. Half the cases get some, and
        every case of a category with `forced` follow words. A word after a mark stays out, so
        the follow words stay inside one clause."""
        if not forced and rng.random() < 0.5:
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

    def run(self, category: str, quota: int, maker, expected: str, repeat_limit: int = REPEATS,
            forced_follow: bool = False, needs_context: bool = False, needs_decider: bool = False,
            start_number: int = 0, label: str | None = None) -> int:
        """Draws sentences in a seeded order and lets `maker` make one case of each, until the
        quota is full. `maker(tokens, rng, layout)` returns (start, end, typed text, intended text,
        fields) for the words from `start` to `end`, or None. Returns the count of cases made.

        `forced_follow`: every case types one or two words after the slip. `needs_context`: the
        slip has one word or more before it. `needs_decider`: the case has a context or follow
        words, because its typed word is itself a real word."""
        rng = random.Random(f"{SEED}-{self.half}-{label or category}")
        order = self.pool[:]
        rng.shuffle(order)
        made = 0
        repeats: dict[str, int] = {}
        for source, tokens in order:
            layout = self.layouts[rng.choice(layout_keys.STYLES)]
            result = maker(tokens, rng, layout)
            if result is None:
                continue
            start, end, typed, intended, fields = result
            context = " ".join(word for word, _ in tokens[:start])
            if needs_context and not context:
                continue
            # The typed word, without the mark after it: "thst" and "thst," are one typed word.
            typed_word = typed.rstrip(PUNCTUATION)
            if repeats.get(typed_word, 0) >= repeat_limit:
                continue
            follow = self.follow_words(tokens, end, rng, forced_follow)
            if forced_follow and not follow:
                continue
            if needs_decider and not context and not follow:
                continue
            # A mark at the end of the slip word stays; the follow words come after its space.
            typed_text = " ".join([typed] + follow)
            intended_text = " ".join([intended] + follow)
            key = start_key(context, intended)
            if key in self.excluded:
                self.skip("start kept by the other half")
                continue
            triple = (context, typed_text, intended_text)
            if triple in self.seen:
                self.skip("same case in this half")
                continue
            if len(context.split()) >= MODEL_START_MINIMUM_CONTEXT_WORDS and (
                    self.training.prefix_is_model_text(context, intended)
                    or self.training.prefix_is_model_text(context, intended_text)):
                self.skip("start is language-model text")
                continue
            if expected == "correct":
                rival = rival_of(typed, intended, layout)
                if rival is not None:
                    if not context and not follow:
                        # Nothing decides between the intended word and the rival.
                        self.skip("rival word and no words around it")
                        continue
                    fields = fields | {"rival": rival}
            self.seen.add(triple)
            self.starts.add(key)
            repeats[typed_word] = repeats.get(typed_word, 0) + 1
            self.add(category, start_number + made, source, context, typed_text, intended_text, expected,
                     layout=layout.name, follow=len(follow), **fields)
            made += 1
            if made == quota:
                return made
        self.shortfalls[label or category] = {"wanted": quota, "made": made}
        return made


def pick_word(tokens, rng, test) -> int | None:
    """A random place whose word passes `test`, or None."""
    places = [i for i, (word, mark) in enumerate(tokens) if test(word, mark, i)]
    return rng.choice(places) if places else None


def plain(word: str) -> bool:
    return word.isalpha()


def keyboard_reads(typed_text: str) -> bool:
    """Whether the keyboard reads each typed word as a word it may correct
    (`correctableWord` of Shared/KeyboardTextLogic.swift, through rerank.correctable_word)."""
    return all(correctable_word(word) == word for word in typed_text.rstrip(PUNCTUATION).split(" "))


def drift_maker(direction: str | None, kind: str, symbols: bool = False):
    """kind "full": every letter of the word. "partial": from a letter after the first to the
    end, two letters or more. "end_two": the last two letters. A drift case types letters only,
    except that `symbols` asks for a drift that types a digit or symbol key, as "=pw7e"."""
    def maker(tokens, rng, layout):
        minimum = 3 if kind == "full" else 4
        index = pick_word(tokens, rng, lambda w, m, i: plain(w) and len(w) >= minimum and zipf(w) >= TARGET_MINIMUM_ZIPF)
        if index is None:
            return None
        word, mark = tokens[index]
        chosen = direction if direction is not None else rng.choice(layout_keys.DIRECTIONS)
        sideways = rng.choice(layout_keys.SIDEWAYS) if chosen in ("up", "down") else 0.0
        start = {"full": 0, "end_two": len(word) - 2}.get(kind)
        if start is None:
            start = rng.randint(1, len(word) - 2)
        typed = layout.drift_text(word, chosen, sideways, start)
        if typed is None or WORD_ENDING_KEYS & set(typed) or letters_only(typed) == symbols:
            return None
        if symbols:
            if typed == word or zipf(typed) >= TYPED_MAXIMUM_ZIPF:
                return None
        elif not fair(typed, word):
            return None
        fields = {"direction": chosen, "sideways": sideways, "drift_start": start}
        if symbols:
            fields["keyboard_reads_word"] = keyboard_reads(typed)
        return index, index, typed + mark, word + mark, fields
    return maker


def two_word_places(tokens, minimum_zipf: float, minimum_letters: int) -> list[int]:
    return [i for i in range(len(tokens) - 1)
            if plain(tokens[i][0]) and plain(tokens[i + 1][0]) and not tokens[i][1]
            and min(zipf(tokens[i][0]), zipf(tokens[i + 1][0])) >= minimum_zipf
            and len(tokens[i][0]) + len(tokens[i + 1][0]) >= minimum_letters]


def drift_phrase_maker(run_on: bool):
    """Two words, both drifted in one direction, the space kept. With `run_on` the drift starts
    inside the first word and runs on to the end of the second, as "tjod [jtsdr" for "this
    phrase"."""
    def maker(tokens, rng, layout):
        places = two_word_places(tokens, TARGET_MINIMUM_ZIPF, 6)
        if not places:
            return None
        index = rng.choice(places)
        direction = rng.choice(layout_keys.DIRECTIONS)
        sideways = rng.choice(layout_keys.SIDEWAYS) if direction in ("up", "down") else 0.0
        first = tokens[index][0]
        if run_on and len(first) < 2:
            return None
        start = rng.randint(1, len(first) - 1) if run_on else 0
        phrase = first + " " + tokens[index + 1][0]
        typed = layout.drift_text(phrase, direction, sideways, start)
        if typed is None or not letters_only(typed) or not fair_words(typed, phrase):
            return None
        mark = tokens[index + 1][1]
        return index, index + 1, typed + mark, phrase + mark, {"direction": direction, "sideways": sideways,
                                                             "drift_start": start}
    return maker


def drift_then_slip_maker(tokens, rng, layout):
    """One word drifted, in full or from a letter inside it, and a one-letter slip of another
    kind in the next word."""
    places = two_word_places(tokens, TARGET_MINIMUM_ZIPF, 7)
    places = [i for i in places if len(tokens[i][0]) >= 3 and len(tokens[i + 1][0]) >= 3]
    if not places:
        return None
    index = rng.choice(places)
    first, second = tokens[index][0], tokens[index + 1][0]
    direction = rng.choice(layout_keys.DIRECTIONS)
    sideways = rng.choice(layout_keys.SIDEWAYS) if direction in ("up", "down") else 0.0
    start = rng.choice((0, rng.randint(1, len(first) - 2))) if len(first) >= 4 else 0
    drifted = layout.drift_text(first, direction, sideways, start)
    slip = rng.choice(ONE_LETTER_SLIPS)
    slipped = slip(second, layout, rng)
    if drifted is None or slipped is None:
        return None
    typed = drifted + " " + slipped
    phrase = first + " " + second
    if not letters_only(typed) or not fair(drifted, first) or not fair(slipped, second):
        return None
    mark = tokens[index + 1][1]
    return index, index + 1, typed + mark, phrase + mark, {"direction": direction, "sideways": sideways,
                                                         "drift_start": start, "second_slip": slip.__name__}


def drift_and_omission_maker(tokens, rng, layout):
    """A word with a drift from a letter inside it, and one letter of the word left out."""
    index = pick_word(tokens, rng, lambda w, m, i: plain(w) and len(w) >= 5 and zipf(w) >= TARGET_MINIMUM_ZIPF)
    if index is None:
        return None
    word, mark = tokens[index]
    direction = rng.choice(layout_keys.DIRECTIONS)
    sideways = rng.choice(layout_keys.SIDEWAYS) if direction in ("up", "down") else 0.0
    start = rng.randint(1, len(word) - 2)
    drifted = layout.drift_text(word, direction, sideways, start)
    if drifted is None:
        return None
    left_out = rng.randrange(len(word))
    typed = drifted[:left_out] + drifted[left_out + 1:]
    if not letters_only(typed) or not fair(typed, word):
        return None
    return index, index, typed + mark, word + mark, {"direction": direction, "sideways": sideways,
                                                     "drift_start": start, "left_out": left_out}


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
    places = two_word_places(tokens, VERY_COMMON_ZIPF, 0)
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
    slip = rng.choice(ONE_LETTER_SLIPS)
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


def build_half(half: str, pool: list, layouts, excluded: set, training) -> tuple[list[dict], dict, dict, set]:
    seen: set = set()
    skipped: dict[str, int] = {}
    builder = Builder(half, pool, layouts, excluded, training, seen, skipped)
    for direction in layout_keys.DIRECTIONS:
        builder.run(f"drift_full_{direction}", QUOTAS[f"drift_full_{direction}"], drift_maker(direction, "full"), "correct")
        builder.run(f"drift_partial_{direction}", QUOTAS[f"drift_partial_{direction}"], drift_maker(direction, "partial"),
                    "correct")
    builder.run("drift_end_two", QUOTAS["drift_end_two"], drift_maker(None, "end_two"), "correct")
    builder.run("drift_phrase", QUOTAS["drift_phrase"], drift_phrase_maker(False), "correct")
    builder.run("drift_run_on", QUOTAS["drift_run_on"], drift_phrase_maker(True), "correct")
    # Drifts that type a digit or symbol key: half full and half from a letter inside the word.
    made = builder.run("drift_onto_symbols", QUOTAS["drift_onto_symbols"] // 2, drift_maker(None, "full", symbols=True),
                       "correct", label="drift_onto_symbols full")
    builder.run("drift_onto_symbols", QUOTAS["drift_onto_symbols"] - QUOTAS["drift_onto_symbols"] // 2,
                drift_maker(None, "partial", symbols=True), "correct", start_number=made, label="drift_onto_symbols partial")
    builder.run("short_word_neighbor", QUOTAS["short_word_neighbor"], short_word_maker(neighbor_substitution), "correct")
    builder.run("short_word_transposition", QUOTAS["short_word_transposition"], short_word_maker(swapped), "correct")
    builder.run("short_word_listed", QUOTAS["short_word_listed"], listed_maker(), "correct")
    # The listed slips with words before them and one or two words typed after them, as "i think
    # thst is right": the keyboard reads the slip again when the next word ends.
    builder.run("short_word_listed_next", QUOTAS["short_word_listed_next"], listed_maker(), "correct",
                forced_follow=True, needs_context=True)
    builder.run("apostrophe_missing", QUOTAS["apostrophe_missing"], apostrophe_maker, "correct", APOSTROPHE_REPEATS)
    for category, slip in LETTER_SLIPS.items():
        builder.run(category, QUOTAS[category], letter_maker(slip), "correct")
    builder.run("drift_then_slip", QUOTAS["drift_then_slip"], drift_then_slip_maker, "correct")
    builder.run("drift_and_omission", QUOTAS["drift_and_omission"], drift_and_omission_maker, "correct")
    builder.run("space_missing_common", QUOTAS["space_missing_common"], space_missing_maker, "correct")
    builder.run("space_extra", QUOTAS["space_extra"], space_extra_maker, "correct")
    builder.run("punctuation_after_slip", QUOTAS["punctuation_after_slip"], punctuation_maker, "correct")
    builder.run("keep_near_common", QUOTAS["keep_near_common"], keep_near_common_maker, "keep")
    builder.run("keep_clean_short", QUOTAS["keep_clean_short"], keep_short_maker, "keep")
    builder.run("keep_clean_punctuation", QUOTAS["keep_clean_punctuation"], keep_punctuation_maker, "keep")
    # The ambiguous pairs share two categories. Numbers run on inside each category. Both forms
    # are words, so every case has a context or follow words that decide between them.
    for direction, category in (("keep", "ambiguous_apostrophe_keep"), ("correct", "ambiguous_apostrophe_correct")):
        made = 0
        for plain_word, contraction in AMBIGUOUS_PAIRS:
            # "wont" as a word of its own ("he is wont to") is rare, and most Tatoeba sentences
            # with "wont" hold a slip of "won't". So "wont" gets no keep case.
            if direction == "keep" and plain_word == "wont":
                continue
            made += builder.run(category, AMBIGUOUS_PER_PAIR, ambiguous_maker(plain_word, contraction, direction), direction,
                                APOSTROPHE_REPEATS, needs_decider=True, start_number=made,
                                label=f"{category} {plain_word}/{contraction}")
    return builder.cases, builder.shortfalls, skipped, builder.starts


def sentence_case(text: str, opens_field: bool) -> str:
    words = text.split(" ")
    out = []
    for index, word in enumerate(words):
        if word == "i" or word.startswith("i'"):
            word = "I" + word[1:]
        if index == 0 and opens_field and word:
            word = word[0].upper() + word[1:]
        out.append(word)
    return " ".join(out)


def capitals_cases(half: str, cases: list[dict]) -> list[dict]:
    """The cases of CAPITALS_CATEGORIES as a field that capitalizes sentences shows them. The
    context is the text in the field, so it starts with a capital and has "I". The typed text
    gets the capital of a word that opens the field, which the keyboard's automatic shift types.
    A typed "i" after the first word stays in lower case: the person types it so, and the
    keyboard corrects it."""
    out = []
    numbers: dict[str, int] = {}
    for case in cases:
        if case["category"] not in CAPITALS_CATEGORIES:
            continue
        opens = not case["context"]
        context = sentence_case(case["context"], True) if case["context"] else ""
        typed = case["typed"][0].upper() + case["typed"][1:] if opens else case["typed"]
        intended = sentence_case(case["intended"], opens)
        number = numbers.get(case["category"], 0)
        numbers[case["category"]] = number + 1
        fields = {k: v for k, v in case.items() if k not in ("id", "context", "typed", "intended")}
        out.append({"id": f"entypocap-{half}-{case['category']}-{number:04d}", **fields, "context": context,
                    "typed": typed, "intended": intended, "lower_case_twin": case["id"]})
    return out


def write_cases(path: Path, cases: list[dict]) -> None:
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"{path.name}: two cases share an id")
    path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm-domain-data", type=Path, required=True)
    parser.add_argument("--lm-finetune2-data", type=Path, required=True)
    arguments = parser.parse_args()
    training = leakage.TrainingTexts(arguments.lm_domain_data, arguments.lm_finetune2_data)
    report = {"seed": SEED, "training": training.report()}
    pool = load_pool(training, report)
    layouts = layout_keys.both()
    # Both halves draw, then each sentence start that both halves drew goes to the half that its
    # SHA-256 value names, and the other half draws again. The rounds stop when no start is in
    # both halves.
    excluded = {"dev": set(), "test": set()}
    for rounds in range(1, 11):
        built = {half: build_half(half, pool[half], layouts, excluded[half], training) for half in ("dev", "test")}
        shared = built["dev"][3] & built["test"][3]
        print(f"round {rounds}: {len(shared)} sentence starts in both halves", flush=True)
        if not shared:
            break
        for key in shared:
            excluded["test" if owner_of(key) == "dev" else "dev"].add(key)
    else:
        raise SystemExit("the halves still share sentence starts after 10 rounds")
    report["rounds"] = rounds
    report["halves"] = {}
    for half in ("dev", "test"):
        cases, shortfalls, skipped, _ = built[half]
        path = CASES / f"english-typos.{half}.jsonl"
        write_cases(path, cases)
        capitals = capitals_cases(half, cases)
        write_cases(CASES / f"english-typos-capitals.{half}.jsonl", capitals)
        counts: dict[str, int] = {}
        for case in cases:
            counts[case["category"]] = counts.get(case["category"], 0) + 1
        pair_overlap = sum(1 for case in cases if case["expected"] == "correct"
                           and (case["typed"].split(" ")[0].strip(PUNCTUATION), case["intended"].split(" ")[0].strip(PUNCTUATION))
                           in training.pairs)
        report["halves"][half] = {"cases": len(cases), "capitals_cases": len(capitals), "categories": counts,
                                  "shortfalls": shortfalls, "skipped": skipped,
                                  "starts_given_to_the_other_half": len(excluded[half]),
                                  "slip_cases_with_a_rival_word": sum(1 for c in cases if "rival" in c),
                                  "slip_cases_whose_first_word_pair_a_training_case_holds": pair_overlap}
        print(f"wrote {path.relative_to(ROOT)}: {len(cases)} cases, and {len(capitals)} in sentence case")
        for category, count in counts.items():
            sample = next(case for case in cases if case["category"] == category)
            print(f"  {category:30s} {count:4d}   e.g. [{sample['context']}] {sample['typed']!r} -> {sample['intended']!r}")
        if shortfalls:
            print("  shortfalls:", shortfalls)
        print("  skipped:", skipped)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "english-typos-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

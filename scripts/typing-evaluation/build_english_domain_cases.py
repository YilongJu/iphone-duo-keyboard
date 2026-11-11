"""Builds the English cases of the "AI and software" vocabulary pack:
cases/english-domain.{dev,test}.jsonl and cases/english-domain-stream.{dev,test}.jsonl.

The files stand apart from english.*.jsonl, so the scores on those files do not change.

Sources:
- Technical sentences: the held-out sentences of scripts/domain-pack/collect_corpus.py, in
  build/domain-pack/corpus/sentences.{dev,test}.jsonl. They come from documents that the pack
  builder never read, and the dev and test halves come from different documents.
- Everyday sentences: Tatoeba English, as build_english_cases.py reads it. A sentence with an
  even id feeds the dev half and one with an odd id the test half.
- The pack: Shared/supplement-ai-software.tsv and scripts/domain-pack/pack/*.tsv.

A case holds the fields of build_english_cases.py and these:
- `group`: the kind of case, one of GROUPS below. The scorer reports each group alone.
- `term`: the word of the pack that the case is about, when it has one.
- `scoring`: "case" for a case that is right only with the intended capitals. Every other case
  is right when the letters agree, as in the other English files.
- `twin`: for a slip, the case with the same text typed without the slip.

The context of a technical case is the sentence before the word, as the source wrote it, with
its capitals and punctuation. The typed word is in lower case, unless the case is about capitals.

Groups and categories:

domain_clean        a word of the pack typed right in a technical sentence. It must stay.
    domain_clean_new, domain_clean_raised    a word new to the base lexicon, and one it holds
    domain_clean_hyphenated                  a compound typed with its hyphen, as "fine-tuning"
domain_slips        a word of the pack typed with one slip of keyboard_noise.py
    domain_slip_new, domain_slip_raised
domain_phrases      a frequent pair of the domain text, and the space bar inside a word of the pack
    phrase_clean                             the pair typed right
    phrase_space_missing, phrase_space_to_letter, phrase_space_transposed
    term_space_extra, term_letter_to_space
    hyphen_second_part_slip                  a slip after the hyphen of a compound
required            the words of scripts/domain-pack/pack/required-terms.tsv
    required_clean, required_clean_next_word, required_slip_named, required_slip, required_control
neighbour_controls  everyday sentences with a common word one edit away from a word of the pack
    neighbour_clean                          the common word typed right. It must stay.
    neighbour_slip                           a slip of the common word. It must go to the common word.
    neighbour_slip_between                   a slip one edit away from both words
    neighbour_slip_onto_term                 a slip of the common word that spells a word new in the
                                             pack. With the pack the keyboard takes the typed
                                             text for that word, so this category is the price of the pack.
capitals            the preferred capitals of a word of the pack (scoring "case")
    capital_lower_stays                      "gpu" inside a sentence stays "gpu"
    capital_deliberate                       "Gpu" inside a sentence becomes "GPU"
    capital_sentence_start                   "Gpu" as the first word of the field becomes "GPU"
    capital_inner                            "pyTorch" becomes "PyTorch"
    capital_preferred_stays                  "PyTorch" stays
    capital_all_capitals_stay                "PYTORCH" stays
    capital_two_capitals_nearest             "PYTORCh" becomes "PYTORCH", and "PYtorch" "PyTorch"
    capital_slip_lower, capital_slip_deliberate, capital_slip_sentence_start
                                             a slip in lower case becomes the word in lower case, and
                                             a slip with a capital becomes the preferred form
    capital_plain_word_keeps_capital         "Tokenizer" stays: the pack prefers lower case for it
    capital_control_everyday_start, capital_control_everyday_deliberate, capital_control_everyday_lower
                                             a word of the pack that is also an everyday word, as "rag"
    capital_control_ordinary_word            a word outside the pack keeps its typed capital
    capital_control_collision_lower          "it", "us" and "ai" in lower case stay in lower case

The stream files hold whole sentences in lower case without punctuation, typed word by word.
Their measure is the count of words that the keyboard changes: `stream` is "technical" for the
held-out technical sentences and "everyday" for Tatoeba sentences.

Usage, from the repository root:
    uv run --with wordfreq python scripts/typing-evaluation/build_english_domain_cases.py
"""
import hashlib
import json
import random
import re
import sys
from pathlib import Path

from wordfreq import top_n_list, zipf_frequency

import build_english_cases as base
import keyboard_noise as noise

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "domain-pack"))
from build_pack import read_base_lexicon  # noqa: E402

CORPUS = ROOT / "build" / "domain-pack" / "corpus"
PACK = ROOT / "scripts" / "domain-pack" / "pack"
TABLE = ROOT / "Shared" / "supplement-ai-software.tsv"
OUTPUT_DIR = HERE / "cases"
SEED = 20261111
EDGE = ".,!?;:\"()[]"
LETTERS = re.compile(r"[a-z]+(?:'[a-z]+)?")
FORM = re.compile(r"[A-Za-z]+(?:['\-][A-Za-z]+)*")
PER_TERM = 3

GROUPS = {
    "domain_clean": ["domain_clean_new", "domain_clean_raised", "domain_clean_hyphenated"],
    "domain_slips": ["domain_slip_new", "domain_slip_raised"],
    "domain_phrases": ["phrase_clean", "phrase_space_missing", "phrase_space_to_letter", "phrase_space_transposed",
                       "term_space_extra", "term_letter_to_space", "hyphen_second_part_slip"],
    "required": ["required_clean", "required_clean_next_word", "required_slip_named", "required_slip", "required_control"],
    "neighbour_controls": ["neighbour_clean", "neighbour_slip", "neighbour_slip_between", "neighbour_slip_onto_term"],
    "capitals": ["capital_lower_stays", "capital_deliberate", "capital_sentence_start", "capital_inner",
                 "capital_preferred_stays", "capital_all_capitals_stay", "capital_two_capitals_nearest",
                 "capital_slip_lower", "capital_slip_deliberate", "capital_slip_sentence_start",
                 "capital_plain_word_keeps_capital", "capital_control_everyday_start",
                 "capital_control_everyday_deliberate", "capital_control_everyday_lower",
                 "capital_control_ordinary_word", "capital_control_collision_lower"],
}
GROUP_OF = {category: group for group, categories in GROUPS.items() for category in categories}

# The contexts of the requested words. No public text holds these words yet, so the contexts
# are written by hand: the start of a request to a coding agent. Each half has its own.
REQUIRED_CONTEXTS = {
    "dev": ["", "please", "can you", "I want you to", "let's", "think hard and"],
    "test": ["now", "ok", "this time", "go ahead and", "before you answer", "you should"],
}
REQUIRED_NEXT_WORDS = {"dev": ["about", "and", "this"], "test": ["on", "before", "the"]}
# The slips of the requested words that the user named.
REQUIRED_NAMED_SLIPS = {"ultrathink": ["ultrathnik", "ultrathinl"], "ultracode": ["ultracoed"]}
# Everyday words that sit close to the requested words. They must stay as typed.
REQUIRED_CONTROLS = ["ultra", "ultrathin", "ultrasound"]
CONTROL_CONTEXTS = {
    "dev": ["", "the", "it was an", "we saw the", "she had an", "that is"],
    "test": ["an", "this", "he bought the", "they need an", "it looks", "a very"],
}
# Everyday words whose capital form is also a technical name. In lower case they stay in lower case.
COLLISION_WORDS = ["it", "us", "ai", "go", "rust", "swift", "python", "apple", "java", "spark", "meta", "git", "rag"]


def all_slips(word: str) -> dict[str, str]:
    """Every text that one slip of keyboard_noise.py makes of the word, with the slip's name."""
    result: dict[str, str] = {}
    for index, letter in enumerate(word):
        if letter not in noise.KEY_POSITION:
            continue
        for neighbour in noise.NEIGHBORS[letter]:
            result.setdefault(word[:index] + neighbour + word[index + 1:], "substitution_adjacent")
            result.setdefault(word[:index] + neighbour + word[index:], "extra_adjacent")
            result.setdefault(word[:index + 1] + neighbour + word[index + 1:], "extra_adjacent")
        if len(word) >= 2:
            result.setdefault(word[:index] + word[index + 1:], "deletion")
        result.setdefault(word[:index] + letter + word[index:], "double_letter")
        if index + 1 < len(word) and word[index + 1] != letter and word[index + 1] in noise.KEY_POSITION:
            result.setdefault(word[:index] + word[index + 1] + letter + word[index + 2:], "transposition")
    result.pop(word, None)
    return result


def split_of(text: str) -> str:
    return "dev" if hashlib.sha256(text.encode()).digest()[0] % 2 == 0 else "test"


class Builder:
    def __init__(self, half: str, known: set[str]):
        self.half = half
        self.known = known
        self.cases: list[dict] = []
        self.numbers: dict[str, int] = {}

    def add(self, category, context, typed, intended, source, term=None, scoring=None, twin=None) -> str:
        number = self.numbers.get(category, 0)
        self.numbers[category] = number + 1
        case = {"id": f"endom-{self.half}-{category}-{number:04d}", "split": self.half, "category": category,
                "group": GROUP_OF[category], "context": context, "typed": typed, "intended": intended, "source": source}
        if term is not None:
            case["term"] = term
        if scoring is not None:
            case["scoring"] = scoring
        if twin is not None:
            case["twin"] = twin
        for field in (context, typed, intended):
            if "|" in field or "\t" in field or "\n" in field or not field.isascii():
                raise SystemExit(f"a case text holds a sign that the harness cannot type: {case}")
        self.cases.append(case)
        return case["id"]

    def count(self, category: str) -> int:
        return self.numbers.get(category, 0)


def read_table() -> tuple[dict[str, tuple[str, bool]], dict[str, str], list[str]]:
    """The words of the supplement with their preferred form and everyday mark, the kind (new or
    raised) of each corpus word, and the requested words."""
    table = {}
    for line in TABLE.read_text(encoding="utf-8").splitlines()[1:]:
        word, _, preferred, everyday = line.split("\t")
        table[word] = (preferred, everyday == "1")
    kinds = {}
    lines = (PACK / "ai-software.terms.tsv").read_text(encoding="utf-8").splitlines()
    columns = lines[0].split("\t")
    for line in lines[1:]:
        row = dict(zip(columns, line.split("\t")))
        kinds[row["word"]] = row["kind"]
    requested = [line.split("\t")[0] for line in (PACK / "required-terms.tsv").read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.startswith("#")]
    return table, kinds, requested


def technical_sentences(half: str) -> list[dict]:
    rows = []
    with (CORPUS / f"sentences.{half}.jsonl").open(encoding="utf-8") as file:
        for line in file:
            row = json.loads(line)
            text = row["text"]
            if text.isascii() and "|" not in text and "\t" not in text:
                row["tokens"] = text.split()
                rows.append(row)
    random.Random(f"{SEED}-{half}-technical").shuffle(rows)
    return rows


def bare(token: str) -> str | None:
    """The word of a token that stands alone or has punctuation only after it, or None."""
    word = token.rstrip(EDGE)
    return word if word and FORM.fullmatch(word) else None


def source_of(row: dict) -> str:
    return f"{row['source']}:{row['document']}"


def build_technical(builder: Builder, sentences: list[dict], table, kinds, phrases: list[str]) -> None:
    half = builder.half
    rng = random.Random(f"{SEED}-{half}-domain")
    known = builder.known
    used = {}

    def take(term: str, limit: int = PER_TERM) -> bool:
        if used.get(term, 0) >= limit:
            return False
        used[term] = used.get(term, 0) + 1
        return True

    # ---- A word of the pack, typed right and typed with a slip ----
    wanted = {"new": 400, "raised": 400}
    for row in sentences:
        tokens = row["tokens"]
        spots = [index for index, token in enumerate(tokens)
                 if (word := bare(token)) is not None and word.lower() in kinds and LETTERS.fullmatch(word.lower())]
        if not spots:
            continue
        index = rng.choice(spots)
        term = bare(tokens[index]).lower()
        kind = kinds[term]
        if builder.count(f"domain_clean_{kind}") >= wanted[kind] or not take(term):
            continue
        context = " ".join(tokens[:index])
        clean = builder.add(f"domain_clean_{kind}", context, term, term, source_of(row), term=term)
        if len(term) >= 4:
            slips = [typed for typed in all_slips(term) if typed not in known]
            if slips:
                operator = rng.choice(sorted(noise.LETTER_OPERATORS))
                named = [typed for typed, name in all_slips(term).items() if name == operator and typed not in known]
                typed = rng.choice(sorted(named or slips))
                builder.add(f"domain_slip_{kind}", context, typed, term, source_of(row), term=term, twin=clean)
        if all(builder.count(f"domain_clean_{k}") >= wanted[k] for k in wanted):
            break

    # ---- Compounds with a hyphen ----
    used.clear()
    for row in sentences:
        tokens = row["tokens"]
        spots = [index for index, token in enumerate(tokens)
                 if (word := bare(token)) is not None and word.count("-") == 1 and word.islower() and "'" not in word
                 and min(len(part) for part in word.split("-")) >= 3]
        if not spots:
            continue
        index = rng.choice(spots)
        word = bare(tokens[index])
        if not take(word):
            continue
        context = " ".join(tokens[:index])
        if builder.count("domain_clean_hyphenated") < 150:
            clean = builder.add("domain_clean_hyphenated", context, word, word, source_of(row), term=word)
            left, right = word.split("-")
            slips = sorted(typed for typed in all_slips(right) if typed not in known)
            if len(right) >= 4 and slips and builder.count("hyphen_second_part_slip") < 150:
                builder.add("hyphen_second_part_slip", context, f"{left}-{rng.choice(slips)}", word, source_of(row),
                            term=word, twin=clean)
        else:
            break

    # ---- Frequent pairs, and the space bar ----
    used.clear()
    phrase_set = set(phrases)
    two_word = {"phrase_space_missing": noise.drop_space, "phrase_space_to_letter": noise.space_to_letter,
                "phrase_space_transposed": noise.transpose_space}
    one_word = {"term_space_extra": noise.extra_space, "term_letter_to_space": noise.letter_to_space}
    order = ["phrase_clean", *two_word]
    turn = 0
    for row in sentences:
        tokens = row["tokens"]
        spots = []
        for index in range(len(tokens) - 1):
            left, right = tokens[index], bare(tokens[index + 1])
            if right is not None and LETTERS.fullmatch(left) and LETTERS.fullmatch(right.lower()) and right.islower() \
                    and f"{left} {right}" in phrase_set:
                spots.append(index)
        if not spots:
            continue
        index = rng.choice(spots)
        phrase = f"{tokens[index]} {bare(tokens[index + 1])}"
        category = order[turn % len(order)]
        limit = 300 if category == "phrase_clean" else 150
        if builder.count(category) >= limit:
            turn += 1
            if all(builder.count(name) >= (300 if name == "phrase_clean" else 150) for name in order):
                break
            continue
        if not take(phrase, 2):
            continue
        context = " ".join(tokens[:index])
        if category == "phrase_clean":
            builder.add(category, context, phrase, phrase, source_of(row), term=phrase)
        else:
            typed = two_word[category](phrase, rng)
            # Typed parts that are all known words read as two intended words, so the case has no slip to see.
            if typed is None or typed == phrase or all(part in known for part in typed.split(" ")):
                continue
            builder.add(category, context, typed, phrase, source_of(row), term=phrase)
        turn += 1

    used.clear()
    for category, operator in one_word.items():
        for row in sentences:
            tokens = row["tokens"]
            spots = [index for index, token in enumerate(tokens)
                     if (word := bare(token)) is not None and word.lower() in kinds and LETTERS.fullmatch(word.lower())
                     and len(word) >= 5]
            if not spots:
                continue
            index = rng.choice(spots)
            term = bare(tokens[index]).lower()
            typed = operator(term, rng)
            if typed is None or all(part in known for part in typed.split(" ")) or not take(f"{category}:{term}", 2):
                continue
            builder.add(category, " ".join(tokens[:index]), typed, term, source_of(row), term=term)
            if builder.count(category) >= 150:
                break

    # ---- Capitals ----
    cased = {word: preferred for word, (preferred, everyday) in table.items() if preferred and not everyday and word.isalpha()}
    plain = {word for word, (preferred, _) in table.items() if not preferred and word in kinds and word.isalpha()}
    used.clear()
    middle = ["capital_lower_stays", "capital_deliberate", "capital_inner", "capital_preferred_stays",
              "capital_all_capitals_stay", "capital_two_capitals_nearest", "capital_slip_lower", "capital_slip_deliberate"]
    limits = {"capital_lower_stays": 150, "capital_deliberate": 150, "capital_inner": 100, "capital_preferred_stays": 100,
              "capital_all_capitals_stay": 100, "capital_two_capitals_nearest": 60, "capital_slip_lower": 150,
              "capital_slip_deliberate": 150}
    turn = 0
    for row in sentences:
        tokens = row["tokens"]
        spots = [index for index, token in enumerate(tokens)
                 if index >= 1 and (word := bare(token)) is not None and word.lower() in cased
                 and not tokens[index - 1].endswith((".", "!", "?"))]
        if not spots:
            continue
        index = rng.choice(spots)
        term = bare(tokens[index]).lower()
        preferred = cased[term]
        category = middle[turn % len(middle)]
        turn += 1
        if builder.count(category) >= limits[category]:
            if all(builder.count(name) >= limits[name] for name in middle):
                break
            continue
        context = " ".join(tokens[:index])
        source = source_of(row)
        slips = sorted(typed for typed in all_slips(term) if typed not in known)
        made = None
        if category == "capital_lower_stays":
            made = (term, term)
        elif category == "capital_deliberate":
            made = (term.capitalize(), preferred)
        elif category == "capital_inner" and len(term) >= 3:
            # One capital after the first letter, at a place where the result is no form of the word.
            places = [place for place in range(1, len(term))
                      if (typed := term[:place] + term[place].upper() + term[place + 1:]) != preferred]
            if places:
                place = rng.choice(places)
                made = (term[:place] + term[place].upper() + term[place + 1:], preferred)
        elif category == "capital_preferred_stays":
            made = (preferred, preferred)
        elif category == "capital_all_capitals_stay" and preferred != term.upper():
            made = (term.upper(), term.upper())
        elif category == "capital_two_capitals_nearest" and len(term) >= 5 and preferred != term.upper():
            if builder.count(category) % 2 == 0:
                place = rng.randrange(1, len(term))
                typed = term.upper()[:place] + term[place] + term.upper()[place + 1:]
                to_preferred = sum(a.isupper() != b.isupper() for a, b in zip(typed, preferred))
                if to_preferred >= 2:
                    made = (typed, term.upper())
            else:
                places = [place for place in range(1, len(term)) if not preferred[place].isupper()]
                place = rng.choice(places)
                typed = preferred[:place] + preferred[place].upper() + preferred[place + 1:]
                capitals = sum(c.isupper() for c in typed)
                if capitals >= 2 and len(term) - capitals >= 2:
                    made = (typed, preferred)
        elif category == "capital_slip_lower" and len(term) >= 4 and slips:
            made = (rng.choice(slips), term)
        elif category == "capital_slip_deliberate" and len(term) >= 4 and slips:
            made = (rng.choice(slips).capitalize(), preferred)
        if made is None or not take(f"{category}:{term}", 2):
            turn -= 1
            continue
        builder.add(category, context, made[0], made[1], source, term=term, scoring="case")

    start_rng = random.Random(f"{SEED}-{half}-capital-start")
    start_terms = sorted(word for word in cased if split_of(word) == half)
    start_rng.shuffle(start_terms)
    for term in start_terms[:150]:
        builder.add("capital_sentence_start", "", term.capitalize(), cased[term], "the pack", term=term, scoring="case")
    for term in start_terms[150:]:
        slips = sorted(typed for typed in all_slips(term) if typed not in known)
        if len(term) >= 4 and slips and builder.count("capital_slip_sentence_start") < 100:
            builder.add("capital_slip_sentence_start", "", start_rng.choice(slips).capitalize(), cased[term], "the pack",
                        term=term, scoring="case")

    used.clear()
    for row in sentences:
        tokens = row["tokens"]
        spots = [index for index, token in enumerate(tokens)
                 if index >= 1 and (word := bare(token)) is not None and word.lower() in plain
                 and not tokens[index - 1].endswith((".", "!", "?"))]
        if not spots:
            continue
        index = rng.choice(spots)
        term = bare(tokens[index]).lower()
        if not take(term, 1):
            continue
        builder.add("capital_plain_word_keeps_capital", " ".join(tokens[:index]), term.capitalize(), term.capitalize(),
                    source_of(row), term=term, scoring="case")
        if builder.count("capital_plain_word_keeps_capital") >= 100:
            break


def build_required(builder: Builder, requested: list[str]) -> None:
    half = builder.half
    rng = random.Random(f"{SEED}-{half}-required")
    contexts = REQUIRED_CONTEXTS[half]
    for term in requested:
        clean = {}
        for context in contexts:
            clean[context] = builder.add("required_clean", context, term, term, "requested by the user", term=term)
            for next_word in REQUIRED_NEXT_WORDS[half]:
                builder.add("required_clean_next_word", context, f"{term} {next_word}", f"{term} {next_word}",
                            "requested by the user", term=term)
        for typed in REQUIRED_NAMED_SLIPS.get(term, []):
            for context in contexts:
                builder.add("required_slip_named", context, typed, term, "requested by the user", term=term, twin=clean[context])
        named = set(REQUIRED_NAMED_SLIPS.get(term, []))
        slips = sorted(typed for typed in all_slips(term)
                       if typed not in builder.known and typed not in named and split_of(f"{term}:{typed}") == half)
        rng.shuffle(slips)
        for typed in slips[:40]:
            context = rng.choice(contexts)
            builder.add("required_slip", context, typed, term, "requested by the user", term=term, twin=clean[context])
    for word in REQUIRED_CONTROLS:
        for context in CONTROL_CONTEXTS[half]:
            builder.add("required_control", context, word, word, "written for this file", term=word)


def build_everyday(builder: Builder, sentences, table, kinds, requested: list[str], base_words: dict[str, float]) -> None:
    half = builder.half
    rng = random.Random(f"{SEED}-{half}-neighbours")
    known = builder.known
    pack = set(kinds) | set(requested)
    new_terms = {word for word in pack if word not in base_words}

    # A common word and the words of the pack one edit away from it.
    neighbours: dict[str, list[str]] = {}
    for term in sorted(pack):
        for other in all_slips(term) | dict.fromkeys(base_one_edit(term)):
            if other in base_words and other not in pack and other.isalpha() and len(other) >= 3 \
                    and zipf_frequency(other, "en") >= 4.0:
                neighbours.setdefault(other, []).append(term)

    order = sentences[:]
    rng.shuffle(order)
    used: dict[str, int] = {}

    def take(key: str, limit: int) -> bool:
        if used.get(key, 0) >= limit:
            return False
        used[key] = used.get(key, 0) + 1
        return True

    limits = {"neighbour_clean": 400, "neighbour_slip": 400, "neighbour_slip_between": 300, "neighbour_slip_onto_term": 200}
    for sentence_id, words in order:
        spots = [index for index, word in enumerate(words) if word in neighbours]
        if not spots:
            continue
        index = rng.choice(spots)
        word = words[index]
        context = " ".join(words[:index])
        source = f"tatoeba:{sentence_id}"
        slips = all_slips(word)
        terms = neighbours[word]
        clean = None
        if builder.count("neighbour_clean") < limits["neighbour_clean"] and take(f"clean:{word}", 3):
            clean = builder.add("neighbour_clean", context, word, word, source, term=terms[0])
        fair = sorted(typed for typed in slips if typed not in known and base.letter_slip_is_fair(word, typed))
        if fair and builder.count("neighbour_slip") < limits["neighbour_slip"] and take(f"slip:{word}", 3):
            builder.add("neighbour_slip", context, rng.choice(fair), word, source, term=terms[0], twin=clean)
        between = sorted({typed for term in terms for typed in slips if typed in base_one_edit(term) and typed not in known})
        if between and builder.count("neighbour_slip_between") < limits["neighbour_slip_between"] and take(f"between:{word}", 3):
            typed = rng.choice(between)
            term = next(term for term in terms if typed in base_one_edit(term))
            builder.add("neighbour_slip_between", context, typed, word, source, term=term, twin=clean)
        onto = sorted(term for term in terms if term in slips and term in new_terms)
        if onto and builder.count("neighbour_slip_onto_term") < limits["neighbour_slip_onto_term"] and take(f"onto:{word}", 3):
            term = rng.choice(onto)
            builder.add("neighbour_slip_onto_term", context, term, word, source, term=term, twin=clean)
        if all(builder.count(name) >= limit for name, limit in limits.items()):
            break

    # ---- Capitals: everyday words ----
    rng = random.Random(f"{SEED}-{half}-capital-controls")
    everyday_terms = sorted(word for word, (preferred, everyday) in table.items() if preferred and everyday)
    for term in everyday_terms:
        builder.add("capital_control_everyday_start", "", term.capitalize(), term.capitalize(), "the pack", term=term, scoring="case")
    used.clear()
    for sentence_id, words in order:
        for index, word in enumerate(words):
            if index == 0:
                continue
            context = " ".join(words[:index])
            source = f"tatoeba:{sentence_id}"
            if word in everyday_terms and take(f"everyday:{word}", 8):
                builder.add("capital_control_everyday_deliberate", context, word.capitalize(), word.capitalize(), source,
                            term=word, scoring="case")
                builder.add("capital_control_everyday_lower", context, word, word, source, term=word, scoring="case")
            elif word in COLLISION_WORDS and take(f"collision:{word}", 8):
                builder.add("capital_control_collision_lower", context, word, word, source, term=word, scoring="case")
            elif word not in pack and word.isalpha() and len(word) >= 3 and word in base_words \
                    and builder.count("capital_control_ordinary_word") < 150 and take(f"ordinary:{word}", 1) and rng.random() < 0.02:
                builder.add("capital_control_ordinary_word", context, word.capitalize(), word.capitalize(), source, scoring="case")


_ONE_EDIT: dict[str, set[str]] = {}


def base_one_edit(word: str) -> set[str]:
    """Every string one edit away, as build_english_lexicon.py counts it."""
    if word not in _ONE_EDIT:
        sys.path.insert(0, str(ROOT / "scripts" / "typing-engine"))
        from build_english_lexicon import one_edit_away
        _ONE_EDIT[word] = one_edit_away(word)
    return _ONE_EDIT[word]


def build_stream(half: str, technical: list[dict], everyday) -> list[dict]:
    rows = []
    per_source: dict[str, int] = {}
    for row in technical:
        words = []
        for token in row["tokens"]:
            word = token.strip(EDGE)
            if not FORM.fullmatch(word):
                words = []
                break
            words.append(word.lower())
        if not 6 <= len(words) <= 25 or per_source.get(row["source"], 0) >= 80:
            continue
        per_source[row["source"]] = per_source.get(row["source"], 0) + 1
        text = " ".join(words)
        rows.append({"id": f"endomstream-{half}-technical-{len(rows):04d}", "split": half, "stream": "technical",
                     "context": "", "typed": text, "intended": text, "source": source_of(row)})
        if len(rows) == 1000:
            break
    technical_count = len(rows)
    order = everyday[:]
    random.Random(f"{SEED}-{half}-stream").shuffle(order)
    for sentence_id, words in order[:1000]:
        text = " ".join(words)
        rows.append({"id": f"endomstream-{half}-everyday-{len(rows) - technical_count:04d}", "split": half,
                     "stream": "everyday", "context": "", "typed": text, "intended": text, "source": f"tatoeba:{sentence_id}"})
    return rows


def main():
    table, kinds, requested = read_table()
    base_words = read_base_lexicon(ROOT / "Shared" / "lexicon-english.bin")
    known = set(base_words) | set(table)
    # A pair with a contraction, as "you'll learn", is everyday text and not a phrase of the field.
    phrases = [line.split("\t")[0] for line in (PACK / "ai-software.phrases.tsv").read_text(encoding="utf-8").splitlines()[1:]
               if "'" not in line.split("\t")[0]]
    everyday = base.load_sentences(set(top_n_list("en", 60000)))
    dev_texts = {tuple(words) for _, words in everyday["dev"]}
    everyday["test"] = [sentence for sentence in everyday["test"] if tuple(sentence[1]) not in dev_texts]
    OUTPUT_DIR.mkdir(exist_ok=True)
    for half in ("dev", "test"):
        technical = technical_sentences(half)
        builder = Builder(half, known)
        build_technical(builder, technical, table, kinds, phrases)
        build_required(builder, requested)
        build_everyday(builder, everyday[half], table, kinds, requested, base_words)
        order = {category: place for place, category in enumerate(GROUP_OF)}
        cases = sorted(builder.cases, key=lambda case: (order[case["category"]], case["id"]))
        path = OUTPUT_DIR / f"english-domain.{half}.jsonl"
        path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")
        stream = build_stream(half, technical, everyday[half])
        stream_path = OUTPUT_DIR / f"english-domain-stream.{half}.jsonl"
        stream_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in stream), encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}: {len(cases)} cases")
        for group, categories in GROUPS.items():
            print(f"  {group}")
            for category in categories:
                sample = next((case for case in cases if case["category"] == category), None)
                shown = f"e.g. [{sample['context'][-40:]}] {sample['typed']!r} -> {sample['intended']!r}" if sample else ""
                print(f"    {category:38s} {builder.count(category):4d}   {shown}")
        for kind in ("technical", "everyday"):
            rows = [row for row in stream if row["stream"] == kind]
            print(f"  stream {kind}: {len(rows)} sentences, {sum(len(row['typed'].split()) for row in rows)} words")


if __name__ == "__main__":
    main()

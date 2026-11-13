"""Builds the training and tuning cases of the distilgpt2 fine-tune, from Tatoeba sentences that
the dev and test halves do not use.

The cases come from the generators of the dev and test halves (scripts/typing-evaluation/
build_english_cases.py and build_english_symbol_cases.py), with their slip makers and frequency
limits, on a new pool of sentences. docs/lm-finetune-design.md gives the rules.

Leakage rules. A sentence leaves the pool when
1. its id is the source of a dev or test case,
2. its words equal the words of a dev or test source sentence,
3. its words equal a dev or test context, or
4. its words hold a dev or test context followed by that case's intended text, for every case
   with a context.
A case leaves the splits when its intended text holds a word of a list-based clean category of
dev or test (rare words, names and terms, symbol tokens), or when a typed word is a published
misspelling of the dev or test half. Of the test cases the script reads `source`, `context`,
`intended` and `category` only.

Splits. SHA-256 of "lm-finetune:" and the sentence id gives a bucket from 0 to 9. Bucket 0 feeds
the tuning split, which chooses the re-ranker setting of every arm. Bucket 1 feeds the stopping
split, which chooses the checkpoint of each fine-tune. Buckets 2 to 9 feed the training split.
A word of a word list splits by the same hash of the word. The tuning and stopping splits have
the category counts of the dev half. A sentence whose words equal a sentence of the tuning split
leaves the other two, and one that equals a sentence of the stopping split leaves training.

Usage, from the repository root (needs wordfreq, the Tatoeba export that
build_english_cases.py caches, and build/typing-evaluation/external/english.*.jsonl from
build_external_english_cases.py):
    python3 scripts/lm-finetune/build_cases.py --out build/lm-finetune/data
"""
import argparse
import bz2
import hashlib
import json
import random
import re
import sys
import urllib.request
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "typing-evaluation"))
from wordfreq import top_n_list  # noqa: E402

import build_english_cases as base  # noqa: E402
import build_english_symbol_cases as sym  # noqa: E402
import keyboard_noise as noise  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
HELD_FILES = ["english.dev.jsonl", "english.test.jsonl", "english-symbols.dev.jsonl", "english-symbols.test.jsonl"]
EXTERNAL = ROOT / "build" / "typing-evaluation" / "external"
NAMES = ROOT / "scripts" / "typing-evaluation" / "inputs" / "names_and_terms.txt"
SYMBOL_TOKENS = ROOT / "scripts" / "typing-evaluation" / "inputs" / "symbol_tokens.txt"

# Cases per category in the training split. The clean categories get more, so that clean lists
# make up about one third of the training cases.
TRAIN_SLIP_CASES = 4000
TRAIN_CLEAN_CASES = 6000
# The tuning split has the counts of the dev half: 300 per category, and the dev counts of the
# two clean categories that come from a short list.
TUNE_CASES = 300
TUNE_NAMES = 73
TUNE_SYMBOL_TOKENS = 129
# The list-based clean categories of dev and test, whose words never enter a training case.
LIST_CATEGORIES = {"clean_rare", "clean_names_and_terms", "clean_symbol_token"}
# A token for the names-and-terms stand-in stays only when no word this much more frequent (Zipf)
# sits one edit away, the rule of scripts/typing-engine/build_english_lexicon.py.
SLIP_ZIPF_GAP = 2.0
TOKEN_ALPHABET = "abcdefghijklmnopqrstuvwxyz"
PROXY_RANKS = (60000, 400000)
SYMBOL_PROXY_MINIMUM_ZIPF = 1.0
DIGIT_TOKEN = re.compile(r"[a-z0-9]+")
SEED = "lm-finetune-20261110"


SPLITS = ("tune", "stop", "train")
# How many times symbol_cases reads the sentences for one category. The first reading is the
# reading of rounds 1 and 2. A later reading takes new word positions, for a set whose sentences
# leave a category short after one reading (scripts/lm-domain/build_fresh_holdout.py).
SENTENCE_READINGS = 1


def bucket(key: str) -> int:
    return int(hashlib.sha256(f"lm-finetune:{key}".encode()).hexdigest(), 16) % 10


def split_of(key: str) -> str:
    return {0: "tune", 1: "stop"}.get(bucket(key), "train")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def one_edit_away(word: str) -> set[str]:
    cuts = [(word[:index], word[index:]) for index in range(len(word) + 1)]
    result = {left + right[1:] for left, right in cuts if right}
    result |= {left + right[1] + right[0] + right[2:] for left, right in cuts if len(right) > 1}
    result |= {left + letter + right[1:] for left, right in cuts if right for letter in TOKEN_ALPHABET}
    result |= {left + letter + right for left, right in cuts for letter in TOKEN_ALPHABET}
    result.discard(word)
    return result


def load_pool(held: list[dict], report: dict) -> list[tuple[int, list[str]]]:
    """Every sentence that passes the generator's filter, minus the four leakage rules."""
    vocabulary = set(top_n_list("en", 60000))
    held_ids = {int(case["source"].split(":", 1)[1]) for case in held if case["source"].startswith("tatoeba:")}
    contexts = {case["context"] for case in held if case["context"]}
    phrases = {case["context"] + " " + case["intended"].strip().lower() for case in held if case["context"]}
    longest = max(len(phrase.split(" ")) for phrase in phrases)
    sentences = {}
    lines = 0
    with bz2.open(base.CACHE, "rt", encoding="utf-8") as file:
        for line in file:
            lines += 1
            sentence_id, _, text = line.rstrip("\n").split("\t", 2)
            if not text.isascii():
                continue
            words = base.tokenize(text)
            if words is None or not 4 <= len(words) <= 12 or any(word not in vocabulary for word in words):
                continue
            sentences[int(sentence_id)] = words
    missing = sorted(i for i in held_ids if i not in sentences)
    if missing:
        raise SystemExit(f"{len(missing)} dev or test source ids are not in the export, e.g. {missing[:5]}")
    source_texts = {" ".join(sentences[i]) for i in held_ids}
    for case in held:
        if case["source"].startswith("tatoeba:"):
            words = sentences[int(case["source"].split(":", 1)[1])]
            if not (" ".join(words) + " ").startswith(case["context"] + " " if case["context"] else ""):
                raise SystemExit(f"the context {case['context']!r} is not the start of its source sentence {case['source']}")
    drops = {"id": 0, "same_as_source": 0, "same_as_context": 0, "holds_context_and_intended": 0}
    pool = []
    for sentence_id, words in sentences.items():
        text = " ".join(words)
        if sentence_id in held_ids:
            drops["id"] += 1
        elif text in source_texts:
            drops["same_as_source"] += 1
        elif text in contexts:
            drops["same_as_context"] += 1
        elif any(" ".join(words[i:j]) in phrases for i in range(len(words))
                 for j in range(i + 2, min(len(words), i + longest) + 1)):
            drops["holds_context_and_intended"] += 1
        else:
            pool.append((sentence_id, words))
    report.update({"export_lines": lines, "pass_filter": len(sentences), "drops": drops, "pool": len(pool)})
    return pool


def held_words(held: list[dict], names: list[str], symbol_tokens: list[str]) -> set[str]:
    words = {case["intended"].strip().lower() for case in held if case["category"] in LIST_CATEGORIES}
    return words | set(names) | set(symbol_tokens)


def word_lists(excluded: set[str], names: list[str], symbol_tokens: list[str]) -> dict:
    """The word lists of the three list-based clean categories, per split."""
    ranked = [w for w in top_n_list("en", 60000)[20000:] if w.isalpha() and w.isascii() and len(w) >= 4 and w not in excluded]
    rare = {split: [w for w in ranked if split_of(w) == split] for split in SPLITS}

    wide = top_n_list("en", PROXY_RANKS[1])
    candidates = [w for w in wide[PROXY_RANKS[0]:] if w.isalpha() and w.isascii() and len(w) >= 4 and w not in excluded]
    # The slip test is slow, so the tokens go in a fixed hash order and the test stops once every
    # split is full.
    candidates.sort(key=lambda w: hashlib.sha256(f"lm-finetune-order:{w}".encode()).hexdigest())
    names_by_split = {split: [] for split in SPLITS}
    wanted = {"train": TRAIN_CLEAN_CASES, "stop": TUNE_NAMES, "tune": TUNE_NAMES}
    for token in candidates:
        split = split_of(token)
        if len(names_by_split[split]) >= wanted[split]:
            if all(len(names_by_split[s]) >= wanted[s] for s in wanted):
                break
            continue
        frequency = base.zipf(token)
        if any(base.zipf(other) - frequency >= SLIP_ZIPF_GAP for other in one_edit_away(token)):
            continue
        names_by_split[split].append(token)
    for split, count in wanted.items():
        if len(names_by_split[split]) < count:
            raise SystemExit(f"only {len(names_by_split[split])} name stand-ins for {split}, wanted {count}")

    digit_tokens = [w for w in wide if DIGIT_TOKEN.fullmatch(w) and sum(c.isdigit() for c in w) == 1
                    and any(c.isalpha() for c in w) and base.zipf(w) >= SYMBOL_PROXY_MINIMUM_ZIPF and w not in excluded]
    tokens = {split: [w for w in digit_tokens if split_of(w) == split] for split in SPLITS}
    for split in ("stop", "tune"):
        tokens[split] = tokens[split][:TUNE_SYMBOL_TOKENS]
        if len(tokens[split]) < TUNE_SYMBOL_TOKENS:
            raise SystemExit(f"only {len(tokens[split])} symbol token stand-ins for {split}")
    # Each training token appears with several contexts, so the list repeats to the case count.
    repeated = (tokens["train"] * (TRAIN_CLEAN_CASES // len(tokens["train"]) + 1))[:TRAIN_CLEAN_CASES]
    return {"rare": rare, "names": names_by_split,
            "symbol_tokens": {"train": repeated, "stop": tokens["stop"], "tune": tokens["tune"]},
            "distinct_symbol_tokens": {split: len(set(values)) for split, values in tokens.items()}}


def english_cases(split: str, sentences, lists: dict) -> list[dict]:
    """The categories of english.*.jsonl, with the generator of build_english_cases.py."""
    base.CASES_PER_CATEGORY = TRAIN_CLEAN_CASES if split == "train" else TUNE_CASES
    cases = base.build_half(split, sentences, {split: lists["rare"][split]}, {split: lists["names"][split]})
    if split == "train":
        # The generator stops each category at its count, so the first cases of a longer run equal
        # a shorter run with the same seed.
        kept, seen = [], {}
        for case in cases:
            category = case["category"]
            seen[category] = seen.get(category, 0) + 1
            if category.startswith("clean") or seen[category] <= TRAIN_SLIP_CASES:
                kept.append(case)
        cases = kept
    return cases


def symbol_cases(split: str, sentences, symbol_tokens: list[str]) -> list[dict]:
    """The categories of english-symbols.*.jsonl. The loop is build_half of
    build_english_symbol_cases.py with counters in place of its scans, which are too slow for
    thousands of cases, and with per-category counts."""
    slip_count = TRAIN_SLIP_CASES if split == "train" else TUNE_CASES
    clean_count = TRAIN_CLEAN_CASES if split == "train" else TUNE_CASES
    # The repeat limit grows with the count, so one typed text takes the same share of a category.
    repeats_limit = sym.REPEATS_PER_TYPED_TEXT * max(1, slip_count // TUNE_CASES)
    cases, numbers, repeats = [], {}, {}

    def add(category, context, typed, intended, source):
        number = numbers.get(category, 0)
        numbers[category] = number + 1
        cases.append({"id": f"ensym-{split}-{category}-{number:04d}", "split": split, "category": category,
                      "context": context, "typed": typed, "intended": intended, "source": source})

    def from_sentences(category, maker, count, seed_name):
        rng = random.Random(f"{base.SEED}-{split}-{seed_name}")
        order = sentences[:]
        rng.shuffle(order)
        made, taken = 0, set()
        for _ in range(SENTENCE_READINGS):
            for sentence_id, words in order:
                index = rng.randrange(len(words))
                result = maker(words, index, rng)
                if result is None or (sentence_id, index) in taken:
                    continue
                typed, intended = result
                if repeats.get((category, typed), 0) >= repeats_limit:
                    continue
                repeats[(category, typed)] = repeats.get((category, typed), 0) + 1
                taken.add((sentence_id, index))
                add(category, " ".join(words[:index]), typed, intended, f"tatoeba:{sentence_id}")
                made += 1
                if made == count:
                    return
        raise SystemExit(f"{split}/{seed_name}: only {made} cases, wanted {count}")

    def per_symbol(category, maker, symbols):
        for symbol in symbols:
            from_sentences(category, lambda words, index, rng, symbol=symbol: maker(words, index, rng, symbol),
                           slip_count // len(symbols), seed_name=f"{category}-{symbol}")

    per_symbol("symbol_first_letter", sym.make_first_letter_case, sorted(sym.NEIGHBORS))
    per_symbol("symbol_inner_letter", sym.make_inner_letter_case, sym.INNER_SYMBOLS)
    per_symbol("symbol_first_letter_two_words", sym.make_two_word_case, sorted(sym.NEIGHBORS))
    per_symbol("symbol_plus_letter_slip", sym.make_symbol_plus_letter_case, sorted(sym.NEIGHBORS))

    rng = random.Random(f"{base.SEED}-{split}-clean_symbol_token")
    for token in symbol_tokens:
        sentence_id, sentence = rng.choice(sentences)
        cut = rng.randint(0, min(4, len(sentence)))
        add("clean_symbol_token", " ".join(sentence[:cut]), token, token, f"tatoeba:{sentence_id}")

    per_bucket = clean_count // (2 * len(sym.SYMBOLS_BEFORE_A_WORD))
    for symbol in sym.SYMBOLS_BEFORE_A_WORD:
        for with_real_neighbor in (True, False):
            from_sentences(
                "clean_bracket_or_dot_word",
                lambda words, index, rng, symbol=symbol, flag=with_real_neighbor:
                    sym.make_clean_symbol_word_case(words, index, rng, symbol, flag),
                per_bucket, seed_name=f"clean_bracket_or_dot_word-{symbol}-{with_real_neighbor}")
    return cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    held = [{key: case[key] for key in ("category", "source", "context", "intended")}
            for name in HELD_FILES for case in read_jsonl(CASES / name)]
    misspelled = set()
    for half in ("dev", "test"):
        path = EXTERNAL / f"english.{half}.jsonl"
        if not path.exists():
            raise SystemExit(f"{path} is missing: run scripts/typing-evaluation/build_external_english_cases.py")
        misspelled |= {case["typed"] for case in read_jsonl(path)}
    names = [line.strip() for line in NAMES.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    symbol_tokens = [line.strip() for line in SYMBOL_TOKENS.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("# ")]

    if not base.CACHE.exists():
        base.CACHE.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(base.SOURCE_URL, base.CACHE)
    report = {"export_sha256": hashlib.sha256(base.CACHE.read_bytes()).hexdigest(),
              "wordfreq": metadata.version("wordfreq"), "held_cases": len(held)}
    pool = load_pool(held, report)
    print(json.dumps(report), flush=True)
    excluded = held_words(held, names, symbol_tokens)
    lists = word_lists(excluded, names, symbol_tokens)
    report["word_lists"] = {name: {split: len(values) for split, values in lists[name].items()}
                            for name in ("rare", "names", "symbol_tokens")}
    report["distinct_symbol_tokens"] = lists["distinct_symbol_tokens"]

    arguments.out.mkdir(parents=True, exist_ok=True)
    report["splits"] = {}
    # A sentence text that an earlier split holds leaves the later splits.
    taken, cross_split_drops = set(), {}
    by_split = {}
    for split in SPLITS:
        kept_sentences, dropped = [], 0
        for sentence_id, words in pool:
            if split_of(str(sentence_id)) != split:
                continue
            if " ".join(words) in taken:
                dropped += 1
            else:
                kept_sentences.append((sentence_id, words))
        taken |= {" ".join(words) for _, words in kept_sentences}
        by_split[split] = kept_sentences
        cross_split_drops[split] = dropped
    report["same_text_as_an_earlier_split"] = cross_split_drops
    for split in SPLITS:
        sentences = by_split[split]
        cases = english_cases(split, sentences, lists) + symbol_cases(split, sentences, lists["symbol_tokens"][split])
        by_text = {sentence_id: " ".join(words) for sentence_id, words in sentences}
        kept, dropped = [], {"intended_holds_a_held_word": 0, "typed_is_a_published_misspelling": 0}
        for case in cases:
            if any(word in excluded for word in case["intended"].split(" ")):
                dropped["intended_holds_a_held_word"] += 1
            elif any(word in misspelled for word in case["typed"].split(" ")):
                dropped["typed_is_a_published_misspelling"] += 1
            else:
                case["sentence"] = by_text[int(case["source"].split(":", 1)[1])]
                kept.append(case)
        counts = {}
        for case in kept:
            counts[case["category"]] = counts.get(case["category"], 0) + 1
        path = arguments.out / f"cases.{split}.jsonl"
        path.write_text("".join(json.dumps(case) + "\n" for case in kept), encoding="utf-8", newline="\n")
        report["splits"][split] = {"sentences": len(sentences), "cases": len(kept), "dropped": dropped, "categories": counts}
        print(split, json.dumps(report["splits"][split]), flush=True)
    (arguments.out / "cases-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

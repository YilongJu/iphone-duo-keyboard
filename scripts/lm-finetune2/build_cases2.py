"""Builds the Tatoeba cases of round 2: a fresh held-out set, clean running text, and new training
cases. docs/lm-finetune2-design.md gives the rules.

Sentences. The pool of round 1 (scripts/lm-finetune/build_cases.py: every sentence that passes the
generator's filter and the four leakage rules against dev and test) loses every sentence that is
the source of a round 1 case, and every sentence whose words equal such a source. SHA-256 of
"lm-finetune2:" and the sentence id then gives a bucket from 0 to 19:

    buckets 0-2    holdout   the fresh held-out set, read once
    bucket 3       select    clean running text for the pick among arms
    bucket 4       tune      clean running text for the setting of each arm
    bucket 5       stop      new stopping cases
    buckets 6-19   train     new training cases

A sentence whose words equal a sentence of an earlier split in that order leaves the later split.

Case kinds.
- generated (holdout only): the 24 categories of dev with the generators and counts of dev, as the
  tuning split of round 1 was built. The word lists of the three list-based clean categories hold
  only words that are in no round 1 case and in no dev or test list.
- clean_stream_closed: one whole sentence of the pool, typed word by word without a slip.
- clean_stream_open: one whole sentence that fails the generator's filter only because it holds
  one or two words outside the 60,000 most frequent. Each such word is known to wordfreq (Zipf 1.5
  or more) and has no word 100 times as frequent one edit away, so it is not a misspelling. The
  sentence passes the dev and test leakage rules 2 to 4.
- real_misspelling_wikipedia (train and stop only): a pair of Mitton's Wikipedia list as the typed
  word, in a sentence that holds the right word.

A training or stopping case leaves its split when its typed text is a typed text of an evaluation
set of real misspellings, or when it holds a word of a list-based clean category of the held-out
set, or an open word of a tune, select or holdout stream.

Usage, from the repository root, after build_real_typo_cases.py (needs wordfreq):
    python3 scripts/lm-finetune2/build_cases2.py --round1 ROUND1_WORKTREE --out build/lm-finetune2/data
"""
import argparse
import bz2
import hashlib
import json
import random
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune"))
sys.path.insert(0, str(ROOT / "scripts" / "typing-evaluation"))
from wordfreq import top_n_list  # noqa: E402

import build_cases as r1  # noqa: E402

base, sym = r1.base, r1.sym
SEED = "lm-finetune2-20261110"
SPLITS = ("holdout", "select", "tune", "stop", "train")
STREAM_SENTENCES = {
    "holdout": {"closed": 3000, "open": 1000},
    "select": {"closed": 1000, "open": 300},
    "tune": {"closed": 1000, "open": 300},
    "stop": {"closed": 400, "open": 100},
    "train": {"closed": 7000, "open": 1500},
}
OPEN_WORDS_PER_SENTENCE = (1, 2)
OPEN_MINIMUM_ZIPF = 1.5
WIKIPEDIA_SENTENCES_PER_PAIR = 3
EXPORT_SHA256 = "1a2d75ac07aa5d035bff4e2bf053139dfd3b1f1645f6fd3d76fc852cc9ef6020"


def split_of(sentence_id: int) -> str:
    bucket = int(hashlib.sha256(f"lm-finetune2:{sentence_id}".encode()).hexdigest(), 16) % 20
    return {0: "holdout", 1: "holdout", 2: "holdout", 3: "select", 4: "tune", 5: "stop"}.get(bucket, "train")


def word_split(word: str) -> str:
    """The split of a Wikipedia pair, by its right word: one tenth stops, the rest trains."""
    return "stop" if int(hashlib.sha256(f"lm-finetune2-word:{word}".encode()).hexdigest(), 16) % 10 == 0 else "train"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def holdout_word_lists(excluded: set[str], round1_words: set[str]) -> dict:
    """The word lists of the three list-based clean categories of the held-out set: the lists of
    round 1 (build_cases.word_lists), without every word of a round 1 case."""
    taken = excluded | round1_words
    rare = [w for w in top_n_list("en", 60000)[20000:] if w.isalpha() and w.isascii() and len(w) >= 4 and w not in taken]
    wide = top_n_list("en", r1.PROXY_RANKS[1])
    candidates = [w for w in wide[r1.PROXY_RANKS[0]:] if w.isalpha() and w.isascii() and len(w) >= 4 and w not in taken]
    candidates.sort(key=lambda w: hashlib.sha256(f"lm-finetune2-order:{w}".encode()).hexdigest())
    names = []
    for token in candidates:
        if len(names) == r1.TUNE_NAMES:
            break
        frequency = base.zipf(token)
        if any(base.zipf(other) - frequency >= r1.SLIP_ZIPF_GAP for other in r1.one_edit_away(token)):
            continue
        names.append(token)
    if len(names) < r1.TUNE_NAMES:
        raise SystemExit(f"only {len(names)} name stand-ins for the held-out set")
    digit_tokens = [w for w in wide if r1.DIGIT_TOKEN.fullmatch(w) and sum(c.isdigit() for c in w) == 1
                    and any(c.isalpha() for c in w) and base.zipf(w) >= r1.SYMBOL_PROXY_MINIMUM_ZIPF and w not in taken]
    if len(digit_tokens) < r1.TUNE_SYMBOL_TOKENS:
        raise SystemExit(f"only {len(digit_tokens)} symbol token stand-ins for the held-out set")
    return {"rare": {"holdout": rare}, "names": {"holdout": names}, "symbol_tokens": {"holdout": digit_tokens[:r1.TUNE_SYMBOL_TOKENS]},
            "unused_digit_tokens": len(digit_tokens)}


def open_sentences(held: list[dict], taken_texts: set[str], report: dict) -> dict[str, list[tuple[int, list[str], list[str]]]]:
    """Sentences with one or two real words outside the vocabulary, per split, with those words."""
    vocabulary = set(top_n_list("en", 60000))
    contexts = {case["context"] for case in held if case["context"]}
    phrases = {case["context"] + " " + case["intended"].strip().lower() for case in held if case["context"]}
    longest = max(len(phrase.split(" ")) for phrase in phrases)
    judged: dict[str, bool] = {}

    def real_word(word: str) -> bool:
        if word not in judged:
            frequency = base.zipf(word)
            judged[word] = (word.isalpha() and len(word) >= 4 and frequency >= OPEN_MINIMUM_ZIPF
                            and not any(base.zipf(other) - frequency >= r1.SLIP_ZIPF_GAP for other in r1.one_edit_away(word)))
        return judged[word]

    found = {split: [] for split in SPLITS}
    seen = set()
    with bz2.open(base.CACHE, "rt", encoding="utf-8") as file:
        for line in file:
            sentence_id, _, text = line.rstrip("\n").split("\t", 2)
            if not text.isascii():
                continue
            words = base.tokenize(text)
            if words is None or not 4 <= len(words) <= 12:
                continue
            outside = [word for word in words if word not in vocabulary]
            if not OPEN_WORDS_PER_SENTENCE[0] <= len(set(outside)) <= OPEN_WORDS_PER_SENTENCE[1]:
                continue
            joined = " ".join(words)
            if joined in seen or joined in taken_texts or joined in contexts:
                continue
            if any(" ".join(words[i:j]) in phrases for i in range(len(words)) for j in range(i + 2, min(len(words), i + longest) + 1)):
                continue
            if not all(real_word(word) for word in outside):
                continue
            seen.add(joined)
            found[split_of(int(sentence_id))].append((int(sentence_id), words, sorted(set(outside))))
    report["open_sentences"] = {split: len(rows) for split, rows in found.items()}
    return found


def stream_case(split: str, kind: str, number: int, sentence_id: int, words: list[str]) -> dict:
    text = " ".join(words)
    return {"id": f"stream-{split}-{kind}-{number:05d}", "split": split, "category": f"clean_stream_{kind}",
            "context": "", "typed": text, "intended": text, "source": f"tatoeba:{sentence_id}", "sentence": text}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round1", type=Path, required=True, help="the worktree of round 1, read only")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    round1_data = arguments.round1 / "build" / "lm-finetune" / "data"
    base.CACHE = arguments.round1 / "build" / "typing-evaluation" / "eng_sentences.tsv.bz2"
    external = arguments.round1 / "build" / "typing-evaluation" / "external"
    if hashlib.sha256(base.CACHE.read_bytes()).hexdigest() != EXPORT_SHA256:
        raise SystemExit("the Tatoeba export is not the pinned export of round 1")

    held = [{key: case[key] for key in ("category", "source", "context", "intended")}
            for name in r1.HELD_FILES for case in read_jsonl(r1.CASES / name)]
    names = [line.strip() for line in r1.NAMES.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    symbol_tokens = [line.strip() for line in r1.SYMBOL_TOKENS.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("# ")]
    excluded = r1.held_words(held, names, symbol_tokens)
    published = {case["typed"] for half in ("dev", "test") for case in read_jsonl(external / f"english.{half}.jsonl")}
    evaluation_typed = set(published)
    for name in ("cases.github.select.jsonl", "cases.github.holdout.jsonl", "cases.mitton-remainder.holdout.jsonl"):
        evaluation_typed |= {case["typed"] for case in read_jsonl(arguments.out / name)}
    wikipedia = read_jsonl(arguments.out / "pairs.wikipedia.train.jsonl")

    round1_cases = [case for split in ("train", "stop", "tune") for case in read_jsonl(round1_data / f"cases.{split}.jsonl")]
    round1_ids = {int(case["source"].split(":", 1)[1]) for case in round1_cases}
    round1_texts = {case["sentence"] for case in round1_cases}
    round1_words = {word for case in round1_cases for word in case["intended"].split(" ")}

    report = {"export_sha256": EXPORT_SHA256, "wordfreq": metadata.version("wordfreq"),
              "round1_cases": len(round1_cases), "round1_source_sentences": len(round1_ids)}
    pool = r1.load_pool(held, report)
    fresh = [(i, words) for i, words in pool if i not in round1_ids and " ".join(words) not in round1_texts]
    report["fresh_pool"] = len(fresh)
    by_split, taken = {}, set()
    dropped_as_copy = {}
    for split in SPLITS:
        kept, dropped = [], 0
        for sentence_id, words in fresh:
            if split_of(sentence_id) != split:
                continue
            text = " ".join(words)
            if text in taken:
                dropped += 1
            else:
                kept.append((sentence_id, words))
                taken.add(text)
        by_split[split] = kept
        dropped_as_copy[split] = dropped
    report["sentences"] = {split: len(rows) for split, rows in by_split.items()}
    report["same_text_as_an_earlier_split"] = dropped_as_copy
    print(json.dumps(report), flush=True)

    # ---- The generated cases of the held-out set, as the tuning split of round 1 was built ----
    lists = holdout_word_lists(excluded, round1_words)
    report["holdout_word_lists"] = {"rare": len(lists["rare"]["holdout"]), "names": len(lists["names"]["holdout"]),
                                    "symbol_tokens": len(lists["symbol_tokens"]["holdout"]),
                                    "unused_digit_tokens": lists["unused_digit_tokens"]}
    sentences = by_split["holdout"]
    generated = r1.english_cases("holdout", sentences, lists) + r1.symbol_cases("holdout", sentences, lists["symbol_tokens"]["holdout"])
    by_text = {sentence_id: " ".join(words) for sentence_id, words in sentences}
    kept, dropped = [], {"intended_holds_a_dev_or_test_list_word": 0, "typed_is_a_published_misspelling": 0}
    for case in generated:
        if any(word in excluded for word in case["intended"].split(" ")):
            dropped["intended_holds_a_dev_or_test_list_word"] += 1
        elif any(word in published for word in case["typed"].split(" ")):
            dropped["typed_is_a_published_misspelling"] += 1
        else:
            case["sentence"] = by_text[int(case["source"].split(":", 1)[1])]
            kept.append(case)
    generated = kept
    counts = {}
    for case in generated:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    report["holdout_generated"] = {"cases": len(generated), "dropped": dropped, "categories": counts}
    holdout_list_words = {case["intended"] for case in generated if case["category"] in r1.LIST_CATEGORIES}

    # ---- Clean running text ----
    open_by_split = open_sentences(held, taken | round1_texts, report)
    generated_ids = {int(case["source"].split(":", 1)[1]) for case in generated}
    streams, open_words = {}, {}
    for split in SPLITS:
        rng = random.Random(f"{SEED}-{split}-stream-closed")
        closed = [row for row in by_split[split] if row[0] not in generated_ids]
        rng.shuffle(closed)
        rng = random.Random(f"{SEED}-{split}-stream-open")
        wide = open_by_split[split][:]
        rng.shuffle(wide)
        streams[split] = {"closed": closed, "open": wide}
    guarded = set(holdout_list_words) | excluded
    for split in ("holdout", "select", "tune"):
        rows = streams[split]["open"][:STREAM_SENTENCES[split]["open"]]
        if len(rows) < STREAM_SENTENCES[split]["open"]:
            raise SystemExit(f"only {len(rows)} open sentences for {split}")
        streams[split]["open"] = rows
        guarded |= {word for _, _, outside in rows for word in outside}
    stream_cases, stream_report = {}, {}
    for split in SPLITS:
        cases = []
        for kind in ("closed", "open"):
            wanted, made, skipped = STREAM_SENTENCES[split][kind], 0, 0
            for row in streams[split][kind]:
                if made == wanted:
                    break
                # A training or stopping sentence does not hold a guarded word of an evaluation set.
                if split in ("stop", "train") and any(word in guarded for word in row[1]):
                    skipped += 1
                    continue
                cases.append(stream_case(split, kind, made, row[0], row[1]))
                made += 1
            if made < wanted:
                raise SystemExit(f"only {made} {kind} stream sentences for {split}, wanted {wanted}")
            stream_report[f"{split}_{kind}"] = {"sentences": made, "words": sum(len(c["typed"].split(" ")) for c in cases if c["category"].endswith(kind)),
                                                "skipped_for_a_guarded_word": skipped}
        stream_cases[split] = cases
    report["streams"] = stream_report

    # ---- Wikipedia misspellings in training and stopping sentences ----
    stream_ids = {int(case["source"].split(":", 1)[1]) for cases in stream_cases.values() for case in cases}
    wanted_words = {pair["intended"] for pair in wikipedia}
    places = {"stop": {}, "train": {}}
    for split in ("stop", "train"):
        for sentence_id, words in by_split[split]:
            if sentence_id in stream_ids or any(word in guarded for word in words):
                continue
            for index, word in enumerate(words):
                if word in wanted_words:
                    places[split].setdefault(word, []).append((sentence_id, words, index))
                    break
    wikipedia_cases = {"stop": [], "train": []}
    wikipedia_report = {"typed_is_an_evaluation_misspelling": 0, "right_word_in_no_sentence": 0}
    for pair in wikipedia:
        split = word_split(pair["intended"])
        if pair["typed"] in evaluation_typed:
            wikipedia_report["typed_is_an_evaluation_misspelling"] += 1
            continue
        rows = places[split].get(pair["intended"], [])
        if not rows:
            wikipedia_report["right_word_in_no_sentence"] += 1
            continue
        rng = random.Random(f"{SEED}-wikipedia-{pair['typed']}-{pair['intended']}")
        for sentence_id, words, index in rng.sample(rows, min(WIKIPEDIA_SENTENCES_PER_PAIR, len(rows))):
            number = len(wikipedia_cases[split])
            wikipedia_cases[split].append({
                "id": f"en-{split}-real_misspelling_wikipedia-{number:04d}", "split": split, "category": "real_misspelling_wikipedia",
                "context": " ".join(words[:index]), "typed": pair["typed"], "intended": pair["intended"],
                "source": f"tatoeba:{sentence_id}", "sentence": " ".join(words)})
    wikipedia_report.update({split: len(rows) for split, rows in wikipedia_cases.items()})
    report["wikipedia_cases"] = wikipedia_report

    def write(name: str, rows: list[dict]) -> None:
        (arguments.out / name).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")

    write("cases.generated.holdout.jsonl", generated)
    for split in ("holdout", "select", "tune"):
        write(f"cases.stream.{split}.jsonl", stream_cases[split])
    for split in ("stop", "train"):
        write(f"cases2.{split}.jsonl", stream_cases[split] + wikipedia_cases[split])
    (arguments.out / "cases2-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

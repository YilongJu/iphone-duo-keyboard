"""Builds the fresh held-out set of the domain round: cases that no model and no selection has scored.

Six files, each built with the code of the round that made its older twin:

cases.generated.fresh.jsonl     the 24 categories of the generated dev half, from Tatoeba sentences
                                of the held-out buckets 0 to 2 of round 2 (build_cases2.split_of)
cases.stream.fresh.jsonl        3,000 closed and 1,000 open sentences of the same buckets, typed
                                word by word without a slip
cases.github.fresh.jsonl        1,500 github_misspelling cases of the held-out half of the GitHub
                                Typo Corpus, and the github_real_word cases that round 2 left
cases.birkbeck.fresh.jsonl      600 pairs of Roger Mitton's Birkbeck list
cases.domain.fresh.jsonl        the technical and everyday groups of english-domain.*.jsonl, from
                                test-bucket documents of the pack's corpus
cases.domain-stream.fresh.jsonl 1,000 technical and 300 written sentences of the same documents

Rules that make a case fresh:
- A Tatoeba sentence is the source of no case of round 1 or round 2, and of no dev or test case
  of the pack. For the held-out files of round 2 this script reads only the field `source` of
  each case, and the field `intended` of the three list-based clean categories, to leave those
  sentences and words out.
- A GitHub or Birkbeck pair is not a pick of round 2. The script repeats the seeded picks of
  build_real_typo_cases.py with that script's own code, and leaves them out with their pairs.
- A technical sentence comes from a document that is the source of no dev or test case of the
  pack. Its letters differ from every dev sentence, from every sentence of a document that
  feeds a dev or test case, and from every sentence of a dev or test stream.
- A domain slip case never has the typed and intended pair of a training case or of a dev or test
  case of the pack. A domain case never equals a dev or test case of the pack.
- A word of a list-based clean category and an open word of a stream stand in no training sentence.

Each generated, GitHub and Birkbeck slip case says in `pair_in_training` whether a training case
holds its typed and intended pair. Each domain case with a term says in `term_kind` whether the
term had slip cases in training ("trained"), was withheld ("withheld") or is a requested word.

A later set of the same kind takes --label, --seed and --earlier. Every folder of --earlier holds
an earlier set of this script, and the new set shares no source with it: no Tatoeba sentence, no
list word, no GitHub row, pair or commit, no Birkbeck pair, no technical document, and no domain
pair or case. For such folders the script reads the fields `source`, `sentence`, `typed`,
`intended`, `context` and `category`, and it prints counts only.
With --real-word-corpus the set gets a seventh file, cases.real-word.LABEL.jsonl: real-word
errors of the RWSE Wikipedia Revision Dataset (Torsten Zesch, CC BY 4.0, sentences of Wikipedia
under CC BY-SA), because the held-out half of the GitHub Typo Corpus has no unused real-word row.
A later set takes the symbol tokens that the word list still has, also when they are fewer than
the 129 of the earlier sets. It leaves out every GitHub commit of an earlier case: of the select
half, of round 2 and of an earlier set.

Usage, from the repository root (needs wordfreq):
    uv run --with wordfreq python scripts/lm-domain/build_fresh_holdout.py --round1 ../lm-finetune \
        --round2 ../lm-finetune2 --data build/lm-domain/data --out build/lm-domain/data/fresh-holdout
    uv run --with wordfreq python scripts/lm-domain/build_fresh_holdout.py --round1 ../lm-finetune \
        --round2 ../lm-finetune2 --data build/lm-domain/data --label confirm --seed lm-domain-confirm-20261112 \
        --earlier build/lm-domain/data/fresh-holdout --real-word-corpus build/lm-domain/corpora-confirm/rwse-wikipedia \
        --out build/lm-domain/data/confirm-holdout
"""
import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for folder in ("lm-finetune", "lm-finetune2", "typing-evaluation", "domain-pack", "lm-domain"):
    sys.path.insert(0, str(ROOT / "scripts" / folder))
from wordfreq import top_n_list  # noqa: E402

import build_cases as r1  # noqa: E402
import build_cases2 as r2  # noqa: E402
import build_domain_train_cases as train_cases  # noqa: E402
import build_english_domain_cases as dom  # noqa: E402
import build_real_typo_cases as typo  # noqa: E402
from build_pack import read_base_lexicon, tatoeba_feeds_the_cases  # noqa: E402

base = r1.base
SEED = "lm-domain-fresh-20261112"
# A later set reads the sentences up to this many times for a symbol category (build_cases.SENTENCE_READINGS).
LATER_SENTENCE_READINGS = 20
STREAM_SENTENCES = {"closed": 3000, "open": 1000}
GITHUB_CASES = {"github_misspelling": 1500, "github_real_word": 1000}
BIRKBECK_CASES = 600
START_SLIPS = 100
REQUESTED_SLIPS = 12
# Contexts of the requested words, written for this file. The dev and test halves have their own.
COMMAND_CONTEXTS = {"fresh": ["so", "first", "then please", "I need you to", "we should", "stop and"],
                    "confirm": ["next", "today please", "again", "could you just", "you must", "wait and"]}
NAME_CONTEXTS = {"fresh": ["our", "that", "install", "use the", "look at the", "it depends on"],
                 "confirm": ["their", "with", "update", "try the", "read the", "we rely on"]}
REAL_WORD_FILES = {"en_natural_test.txt": "6eb5f924616340f91939bfe3026d86289dcde6d74ff773d4e4665f9bee68ce73",
                   "en_natural_train.txt": "4d9a489a81be93acb1c848b1e041e2ca9017c44b42b8a90754651c135a87cb3f"}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def source_id(case: dict) -> int:
    return int(case["source"].split(":", 1)[1])


def wikipedia_real_word_rows(folder: Path, report: dict) -> list[dict]:
    """The real-word errors of the RWSE Wikipedia Revision Dataset as rows of a case file. A block
    of the files has the article id, the revision id, the wrong word, the right word, the place
    of the wrong word in characters, and the sentence with the wrong word."""
    vocabulary = set(top_n_list("en", 60000))
    counts = {"instances": 0, "word_not_at_its_place": 0, "not_a_plain_pair": 0, "rare_right_word_or_far_pair": 0, "repeated": 0}
    rows, seen, per_pair = [], set(), {}
    for name, digest in REAL_WORD_FILES.items():
        raw = (folder / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise SystemExit(f"{folder / name} is not the pinned file")
        lines = raw.decode("utf-8").replace("\r\n", "\n").split("\n")
        for start in range(0, len(lines) - 5, 7):
            article, revision, wrong, right, place, sentence = lines[start:start + 6]
            counts["instances"] += 1
            tokens, index, at = sentence.split(" "), None, 0
            for number, token in enumerate(tokens):
                if at <= int(place) < at + len(token):
                    index = number
                at += len(token) + 1
            if index is None or typo.split_edges(tokens[index])[1] != wrong:
                counts["word_not_at_its_place"] += 1
                continue
            if not (typo.plain_shape(wrong) and typo.plain_shape(right)) or wrong.lower() == right.lower() or len(wrong) < 2:
                counts["not_a_plain_pair"] += 1
                continue
            wrong, right = wrong.lower(), right.lower()
            if typo.zipf_frequency(right, "en") < typo.RIGHT_MINIMUM_ZIPF or typo.ext.edits(wrong, right) > 2:
                counts["rare_right_word_or_far_pair"] += 1
                continue
            context = " ".join(typo.context_before(tokens[:index], vocabulary))
            if (context, wrong, right) in seen or per_pair.get((wrong, right), 0) >= typo.CASES_PER_PAIR:
                counts["repeated"] += 1
                continue
            seen.add((context, wrong, right))
            per_pair[(wrong, right)] = per_pair.get((wrong, right), 0) + 1
            rows.append({"category": "wikipedia_real_word", "context": context, "typed": wrong, "intended": right,
                         "source": f"rwse-wikipedia:{article}:{revision}"})
    counts["usable"] = len(rows)
    report.update(counts)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round1", type=Path, required=True, help="the worktree of round 1, read only")
    parser.add_argument("--round2", type=Path, required=True, help="the worktree of round 2, read only")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--label", choices=sorted(COMMAND_CONTEXTS), default="fresh", help="the name of the set in ids and file names")
    parser.add_argument("--seed", default=SEED)
    parser.add_argument("--earlier", type=Path, nargs="*", default=[], help="folders of earlier sets of this script")
    parser.add_argument("--real-word-corpus", type=Path, help="the folder of the RWSE Wikipedia Revision Dataset")
    arguments = parser.parse_args()
    label, seed = arguments.label, arguments.seed
    if arguments.out.exists() and any(arguments.out.iterdir()):
        raise SystemExit(f"{arguments.out} already holds files")
    round1_data = arguments.round1 / "build" / "lm-finetune" / "data"
    round2_data = arguments.round2 / "build" / "lm-finetune2" / "data"
    external = arguments.round1 / "build" / "typing-evaluation" / "external"
    base.CACHE = arguments.round1 / "build" / "typing-evaluation" / "eng_sentences.tsv.bz2"
    if hashlib.sha256(base.CACHE.read_bytes()).hexdigest() != r2.EXPORT_SHA256:
        raise SystemExit("the Tatoeba export is not the pinned export of round 1")
    report: dict = {"seed": seed}

    # ---- The cases of earlier sets of this script. The new set shares no source with them. ----
    earlier_cases = [case for folder in arguments.earlier for path in sorted(folder.glob("cases.*.jsonl")) for case in read_jsonl(path)]
    if arguments.earlier and not earlier_cases:
        raise SystemExit("a folder of --earlier holds no case file")
    earlier_tatoeba = {source_id(case) for case in earlier_cases if case["source"].startswith("tatoeba:")}
    earlier_sentences = {case["sentence"] for case in earlier_cases if "sentence" in case}
    earlier_list_words = {case["intended"] for case in earlier_cases if case.get("category") in r1.LIST_CATEGORIES}
    earlier_real = [case for case in earlier_cases if case["source"].startswith(("github-typo-corpus:", "mitton:"))]
    earlier_domain = [case for case in earlier_cases if case["id"].startswith("endom-") or "stream" in case]
    if arguments.earlier:
        report["earlier_sets"] = {"folders": len(arguments.earlier), "cases": len(earlier_cases), "tatoeba_sources": len(earlier_tatoeba),
                                  "list_words": len(earlier_list_words), "github_and_birkbeck_cases": len(earlier_real),
                                  "domain_cases_and_stream_sentences": len(earlier_domain)}

    # ---- Text that a model trained on ----
    everyday_training = [case for name in ("cases.train.jsonl", "cases.stop.jsonl", "cases2.train.jsonl", "cases2.stop.jsonl")
                         for case in read_jsonl(arguments.data / "everyday" / name)]
    domain_training = [case for split in ("train", "stop") for case in read_jsonl(arguments.data / "domain" / f"cases.{split}.jsonl")]
    training_pairs = {(case["typed"].lower(), case["intended"].lower()) for case in everyday_training + domain_training
                      if case["typed"].lower() != case["intended"].lower()}
    training_words = {word for case in everyday_training for word in case["sentence"].split(" ")}
    for case in domain_training:
        for token in (case["context"] + " " + case["intended"]).lower().split():
            training_words.add(token.strip(dom.EDGE))
    report["training"] = {"everyday_cases": len(everyday_training), "domain_cases": len(domain_training),
                          "pairs": len(training_pairs), "words": len(training_words)}

    # ---- The Tatoeba sentences of the held-out buckets, as build_cases2.py splits them ----
    held = [{key: case[key] for key in ("category", "source", "context", "intended")}
            for name in r1.HELD_FILES for case in read_jsonl(r1.CASES / name)]
    names = [line.strip() for line in r1.NAMES.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    symbol_tokens = [line.strip() for line in r1.SYMBOL_TOKENS.read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.startswith("# ")]
    excluded = r1.held_words(held, names, symbol_tokens)
    published = {case["typed"] for half in ("dev", "test") for case in read_jsonl(external / f"english.{half}.jsonl")}
    round1_cases = [case for split in ("train", "stop", "tune") for case in read_jsonl(round1_data / f"cases.{split}.jsonl")]
    round1_ids = {source_id(case) for case in round1_cases}
    round1_texts = {case["sentence"] for case in round1_cases}
    round1_words = {word for case in round1_cases for word in case["intended"].split(" ")}
    pool = r1.load_pool(held, report)
    fresh_pool = [(i, words) for i, words in pool if i not in round1_ids and " ".join(words) not in round1_texts]
    by_split, taken = {}, set()
    for split in r2.SPLITS:
        kept = []
        for sentence_id, words in fresh_pool:
            if r2.split_of(sentence_id) == split and " ".join(words) not in taken:
                kept.append((sentence_id, words))
                taken.add(" ".join(words))
        by_split[split] = kept
    if len(by_split["holdout"]) != 85621:
        raise SystemExit(f"the held-out buckets hold {len(by_split['holdout'])} sentences, and round 2 counted 85,621")

    # Only the source and, for the list-based clean categories, the intended word of each
    # held-out case of round 2 are read here.
    used_ids, used_list_words = set(), set()
    for name in ("cases.generated.holdout.jsonl", "cases.stream.holdout.jsonl"):
        with (round2_data / name).open(encoding="utf-8") as file:
            for line in file:
                case = json.loads(line)
                used_ids.add(source_id(case))
                if case["category"] in r1.LIST_CATEGORIES:
                    used_list_words.add(case["intended"])
    used_ids |= earlier_tatoeba
    used_list_words |= earlier_list_words
    # The everyday cases of the pack take Tatoeba sentences from every bucket, so a sentence of a
    # held-out bucket can be the source of a dev or test case of the pack. It stays out too,
    # and so does a sentence with the words of an everyday stream sentence of the pack.
    pack_cases = [case for half in ("dev", "test") for name in ("english-domain", "english-domain-stream")
                  for case in read_jsonl(dom.OUTPUT_DIR / f"{name}.{half}.jsonl")]
    pack_ids = {source_id(case) for case in pack_cases if case["source"].startswith("tatoeba:")}
    pack_stream_texts = {case["typed"] for case in pack_cases if case.get("stream") == "everyday"}
    sentences = [(i, words) for i, words in by_split["holdout"]
                 if i not in used_ids and i not in pack_ids and " ".join(words) not in pack_stream_texts
                 and " ".join(words) not in earlier_sentences]
    report["tatoeba"] = {"held_out_buckets": len(by_split["holdout"]), "sources_of_round2_held_out_cases": len(used_ids),
                         "sources_of_dev_or_test_cases_of_the_pack": len(pack_ids & {i for i, _ in by_split["holdout"]}),
                         "sentences_left": len(sentences)}

    # ---- Generated cases, with the generators and counts of the generated dev half ----
    taken_words = excluded | used_list_words | training_words
    wide = top_n_list("en", r1.PROXY_RANKS[1])
    # The symbol tokens that holdout_word_lists can still take from the word list, by its own test.
    listed_tokens = [w for w in wide if r1.DIGIT_TOKEN.fullmatch(w) and sum(c.isdigit() for c in w) == 1
                     and any(c.isalpha() for c in w) and base.zipf(w) >= r1.SYMBOL_PROXY_MINIMUM_ZIPF and w not in taken_words | round1_words]
    wanted_tokens = r1.TUNE_SYMBOL_TOKENS
    missing_tokens = wanted_tokens - len(listed_tokens)
    if missing_tokens > 0:
        if not arguments.earlier:
            raise SystemExit(f"only {len(listed_tokens)} symbol token stand-ins are left in the word list")
        # A later set takes the tokens that are left, and its category clean_symbol_token is smaller.
        r1.TUNE_SYMBOL_TOKENS = len(listed_tokens)
        report["symbol_tokens"] = {"left_in_the_word_list": len(listed_tokens), "of_the_earlier_sets": wanted_tokens}
    lists = r2.holdout_word_lists(taken_words, round1_words)
    r1.TUNE_SYMBOL_TOKENS = wanted_tokens
    # Everyday sentences for the neighbour controls of the pack come from one pair of ids in
    # five (build_pack.tatoeba_feeds_the_cases). They stay out of the generated cases and streams.
    neighbour_sentences = [row for row in sentences if tatoeba_feeds_the_cases(row[0])]
    plain_sentences = [row for row in sentences if not tatoeba_feeds_the_cases(row[0])]
    if arguments.earlier:
        r1.SENTENCE_READINGS = LATER_SENTENCE_READINGS
    generated = r1.english_cases("holdout", plain_sentences, lists) + r1.symbol_cases("holdout", plain_sentences, lists["symbol_tokens"]["holdout"])
    r1.SENTENCE_READINGS = 1
    by_text = {sentence_id: " ".join(words) for sentence_id, words in plain_sentences}
    kept, dropped = [], {"intended_holds_a_dev_or_test_list_word": 0, "typed_is_a_published_misspelling": 0}
    for case in generated:
        if any(word in excluded for word in case["intended"].split(" ")):
            dropped["intended_holds_a_dev_or_test_list_word"] += 1
        elif any(word in published for word in case["typed"].split(" ")):
            dropped["typed_is_a_published_misspelling"] += 1
        else:
            case["id"] = case["id"].replace("-holdout-", f"-{label}-")
            case["split"] = label
            if case["source"].startswith("tatoeba:"):
                case["sentence"] = by_text[source_id(case)]
            if case["typed"].lower() != case["intended"].lower():
                case["pair_in_training"] = (case["typed"].lower(), case["intended"].lower()) in training_pairs
            kept.append(case)
    generated = kept
    counts: dict[str, int] = {}
    for case in generated:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    report["generated"] = {"cases": len(generated), "dropped": dropped, "categories": dict(sorted(counts.items())),
                           "word_lists": {"rare": len(lists["rare"]["holdout"]), "names": len(lists["names"]["holdout"]),
                                          "symbol_tokens": len(lists["symbol_tokens"]["holdout"])}}

    # ---- Clean running text ----
    generated_ids = {source_id(case) for case in generated if case["source"].startswith("tatoeba:")}
    closed = [row for row in plain_sentences if row[0] not in generated_ids]
    random.Random(f"{seed}-stream-closed").shuffle(closed)
    open_report: dict = {}
    wide = [row for row in r2.open_sentences(held, taken | round1_texts, open_report)["holdout"]
            if row[0] not in used_ids and " ".join(row[1]) not in earlier_sentences and not any(word in training_words for word in row[2])]
    random.Random(f"{seed}-stream-open").shuffle(wide)
    stream = []
    for kind, rows in (("closed", closed), ("open", wide)):
        if len(rows) < STREAM_SENTENCES[kind]:
            raise SystemExit(f"only {len(rows)} {kind} sentences are left")
        for number, row in enumerate(rows[:STREAM_SENTENCES[kind]]):
            stream.append(r2.stream_case(label, kind, number, row[0], row[1]))
    report["stream"] = {kind: {"sentences": sum(1 for c in stream if c["category"].endswith(kind)),
                               "words": sum(len(c["typed"].split(" ")) for c in stream if c["category"].endswith(kind))}
                        for kind in STREAM_SENTENCES}

    # ---- GitHub typos of the held-out half, outside the picks of round 2 ----
    corpora = arguments.round2 / "build" / "lm-finetune2" / "corpora"
    github_file = corpora / typo.GITHUB_FILE
    if hashlib.sha256(github_file.read_bytes()).hexdigest() != typo.GITHUB_SHA256:
        raise SystemExit(f"{github_file} is not the pinned file")
    round2_picks = typo.github_cases(github_file, {})["holdout"]
    limits = dict(typo.GITHUB_CASES_PER_CATEGORY)
    typo.GITHUB_CASES_PER_CATEGORY = {category: 10**9 for category in limits}
    every = typo.github_cases(github_file, {})["holdout"]
    typo.GITHUB_CASES_PER_CATEGORY = limits
    key = lambda row: (row["category"], row["context"], row["typed"], row["intended"], row["source"])  # noqa: E731
    picked_keys = {key(row) for row in round2_picks}
    picked_pairs = {(row["typed"], row["intended"]) for row in round2_picks}
    # An earlier set of this script takes its rows, its pairs and its commits out too.
    earlier_github = [case for case in earlier_real if case["source"].startswith("github-typo-corpus:")]
    picked_keys |= {key(case) for case in earlier_github}
    picked_pairs |= {(case["typed"], case["intended"]) for case in earlier_github}
    earlier_commits = {case["source"] for case in earlier_github}
    round2_github_pairs = {(row["typed"], row["intended"]) for row in round2_picks}
    if arguments.earlier:
        # One commit can hold several edits, and the halves split by the right word. So a later
        # set leaves out every commit of a case of the select half and of round 2 too.
        earlier_commits |= {row["source"] for row in round2_picks} | {row["source"] for row in typo.github_cases(github_file, {})["select"]}
        # A later set also leaves out a pair that an earlier case of the other list holds: a
        # Birkbeck pair of round 2 or of an earlier set.
        picked_pairs |= {(case["typed"], case["intended"]) for case in earlier_real}
        picked_pairs |= {(case["typed"], case["intended"]) for case in typo.mitton_remainder(corpora / "mitton", external, {})}
    github = []
    github_report = {"picks_of_round2": len(round2_picks)}
    for category, limit in GITHUB_CASES.items():
        members = sorted((row for row in every if row["category"] == category and key(row) not in picked_keys
                          and (row["typed"], row["intended"]) not in picked_pairs and row["source"] not in earlier_commits), key=key)
        # The held-out half has fewer real-word rows left than round 2 took, so that category takes all of them.
        picks = random.Random(f"{seed}-github-{category}").sample(members, min(limit, len(members)))
        for number, row in enumerate(picks):
            github.append({"id": f"en-{label}-{category}-{number:04d}", "split": label, "category": category,
                           "context": row["context"], "typed": row["typed"], "intended": row["intended"], "source": row["source"],
                           "pair_in_training": (row["typed"], row["intended"]) in training_pairs})
        github_report[category] = {"usable_outside_round2": len(members), "kept": len(picks),
                                   "with_context": sum(1 for row in picks if row["context"])}
    report["github"] = github_report

    # ---- Real-word errors of Wikipedia revisions, for a set that the GitHub rows do not reach ----
    real_word = None
    if arguments.real_word_corpus is not None:
        real_word_report: dict = {}
        earlier_pairs = picked_pairs | {(row["typed"], row["intended"]) for row in typo.github_cases(github_file, {})["select"]}
        rows = wikipedia_real_word_rows(arguments.real_word_corpus, real_word_report)
        kept_rows = sorted((row for row in rows if (row["typed"], row["intended"]) not in earlier_pairs), key=key)
        real_word_report["pair_of_an_earlier_github_case"] = len(rows) - len(kept_rows)
        real_word = [{"id": f"en-{label}-wikipedia_real_word-{number:04d}", "split": label, **row,
                      "pair_in_training": (row["typed"], row["intended"]) in training_pairs} for number, row in enumerate(kept_rows)]
        real_word_report["kept"] = len(real_word)
        real_word_report["with_context"] = sum(1 for row in real_word if row["context"])
        real_word_report["pair_in_training"] = sum(1 for row in real_word if row["pair_in_training"])
        report["wikipedia_real_word"] = real_word_report

    # ---- Birkbeck pairs outside every earlier case ----
    mitton = corpora / "mitton"
    round2_mitton = typo.mitton_remainder(mitton, external, {})
    limit = typo.MITTON_REMAINDER_PER_SOURCE_AND_HALF
    typo.MITTON_REMAINDER_PER_SOURCE_AND_HALF = 10**9
    every_mitton = typo.mitton_remainder(mitton, external, {})
    typo.MITTON_REMAINDER_PER_SOURCE_AND_HALF = limit
    picked_pairs = {(case["typed"], case["intended"]) for case in round2_mitton}
    if arguments.earlier:
        # A later set leaves out the pairs of every earlier real misspelling, of the GitHub rows too.
        picked_pairs |= {(case["typed"], case["intended"]) for case in earlier_real} | round2_github_pairs
    rest = sorted({(case["typed"], case["intended"]) for case in every_mitton
                   if case["category"] == "real_misspelling_birkbeck" and (case["typed"], case["intended"]) not in picked_pairs})
    picks = random.Random(f"{seed}-birkbeck").sample(rest, BIRKBECK_CASES)
    birkbeck = [{"id": f"en-{label}-real_misspelling_birkbeck-{number:04d}", "split": label, "category": "real_misspelling_birkbeck",
                 "context": "", "typed": wrong, "intended": right, "source": f"mitton:missp.dat:{label}",
                 "pair_in_training": (wrong, right) in training_pairs} for number, (wrong, right) in enumerate(picks)]
    report["birkbeck"] = {"picks_of_round2": len(round2_mitton), "pairs_left": len(rest), "kept": len(birkbeck)}

    # ---- Domain cases from test-bucket documents that feed no dev or test case ----
    table, kinds, requested = dom.read_table()
    base_words = read_base_lexicon(ROOT / "Shared" / "lexicon-english.bin")
    known = set(base_words) | set(table)
    phrases = [line.split("\t")[0] for line in (dom.PACK / "ai-software.phrases.tsv").read_text(encoding="utf-8").splitlines()[1:]
               if "'" not in line.split("\t")[0]]
    # An earlier set of this script counts as evaluated text here, the same as the dev and test
    # cases of the pack: its documents, its pairs and its cases stay out.
    pack_cases = pack_cases + earlier_domain
    pack_sources = {case["source"] for case in pack_cases}
    pack_pairs = {(case["typed"].lower(), case["intended"].lower()) for case in pack_cases}
    pack_texts = {(case["context"], case["typed"], case["intended"]) for case in pack_cases}
    dom.CORPUS = arguments.data / "pack-corpus"
    dev_letters = {dom.letters_of(" ".join(row["tokens"])) for row in dom.technical_sentences("dev")}
    # The letters of every sentence of a document that feeds a dev or test case, and of every
    # sentence of a dev or test stream. A sentence of another document with the same letters is
    # text that a model was scored on, so it stays out too.
    used_letters = {dom.letters_of(case["typed"]) for case in pack_cases if "stream" in case}
    for half in ("dev", "test"):
        with (dom.CORPUS / f"sentences.{half}.jsonl").open(encoding="utf-8") as file:
            for line in file:
                row = json.loads(line)
                if dom.source_of(row) in pack_sources:
                    used_letters.add(dom.letters_of(row["text"]))
    left = [row for row in dom.technical_sentences("test", dev_letters) if dom.source_of(row) not in pack_sources]
    technical = [row for row in left if dom.letters_of(" ".join(row["tokens"])) not in used_letters]
    same_letters = len(left) - len(technical)
    random.Random(f"{seed}-technical").shuffle(technical)
    builder = dom.Builder(label, known)
    dom.build_technical(builder, technical, table, kinds, phrases)
    dom.build_everyday(builder, neighbour_sentences, table, kinds, base_words)

    def unused_slips(term: str) -> list[str]:
        return sorted(typed for typed in dom.all_slips(term) if typed not in known and (typed, term) not in pack_pairs
                      and (typed, term) not in training_pairs)

    # Slips that open the field, where the keyboard types the first capital by itself.
    rng = random.Random(f"{seed}-capital-start")
    cased = sorted(word for word, (preferred, everyday) in table.items() if preferred and not everyday and word.isalpha() and len(word) >= 4)
    rng.shuffle(cased)
    for term in cased:
        slips = unused_slips(term)
        if slips and builder.count("capital_slip_sentence_start") < START_SLIPS:
            builder.add("capital_slip_sentence_start", "", rng.choice(slips).capitalize(), table[term][0], "the pack", term=term, scoring="case")
    # The requested words, with contexts written for this file and slips that no earlier case holds.
    rng = random.Random(f"{seed}-required")
    for row in requested:
        term = row["word"]
        contexts = COMMAND_CONTEXTS[label] if term in dom.COMMAND_WORDS else NAME_CONTEXTS[label]
        clean = {context: builder.add("required_clean", context, term, term, row["source"], term=term) for context in contexts}
        slips = unused_slips(term)
        rng.shuffle(slips)
        for typed in slips[:REQUESTED_SLIPS]:
            context = rng.choice(contexts)
            builder.add("required_slip", context, typed, term, row["source"], term=term, twin=clean[context])
    requested_words = {row["word"] for row in requested}
    domain, domain_dropped = [], {"same_as_a_dev_or_test_case": 0, "pair_of_a_dev_or_test_case": 0, "pair_of_a_training_case": 0}
    for case in builder.cases:
        pair = (case["typed"].lower(), case["intended"].lower())
        if (case["context"], case["typed"], case["intended"]) in pack_texts:
            domain_dropped["same_as_a_dev_or_test_case"] += 1
        elif pair[0] != pair[1] and pair in pack_pairs:
            domain_dropped["pair_of_a_dev_or_test_case"] += 1
        elif pair[0] != pair[1] and pair in training_pairs:
            domain_dropped["pair_of_a_training_case"] += 1
        else:
            term = case.get("term")
            if term in requested_words:
                case["term_kind"] = "requested"
            elif term in kinds:
                case["term_kind"] = "withheld" if train_cases.is_withheld(term) else "trained"
            domain.append(case)
    order = {category: place for place, category in enumerate(dom.GROUP_OF)}
    domain.sort(key=lambda case: (order[case["category"]], case["id"]))
    domain_stream = dom.build_stream(label, technical, [])
    counts = {}
    for case in domain:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    report["domain"] = {"technical_sentences_left": len(technical),
                        "technical_sentences_with_the_letters_of_an_evaluated_sentence": same_letters,
                        "cases": len(domain), "dropped": domain_dropped,
                        "categories": counts, "neighbour_sentences": len(neighbour_sentences),
                        "stream": {kind: {"sentences": sum(1 for row in domain_stream if row["stream"] == kind),
                                          "words": sum(len(row["typed"].split()) for row in domain_stream if row["stream"] == kind)}
                                   for kind in ("technical", "written")}}

    arguments.out.mkdir(parents=True, exist_ok=True)
    files = {f"cases.generated.{label}.jsonl": generated, f"cases.stream.{label}.jsonl": stream, f"cases.github.{label}.jsonl": github,
             f"cases.birkbeck.{label}.jsonl": birkbeck, f"cases.domain.{label}.jsonl": domain, f"cases.domain-stream.{label}.jsonl": domain_stream}
    if real_word is not None:
        files[f"cases.real-word.{label}.jsonl"] = real_word
    report["files"] = {}
    for name, rows in files.items():
        for row in rows:
            row["split"] = label
        text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        (arguments.out / name).write_text(text, encoding="utf-8", newline="\n")
        report["files"][name] = {"cases": len(rows), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    (arguments.out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    # The report holds counts only. No case text is printed.
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()

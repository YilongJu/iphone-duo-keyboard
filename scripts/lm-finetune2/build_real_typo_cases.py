"""Builds the cases of round 2 that come from real human misspellings.

Three sources, each with one role:
- GitHub Typo Corpus v1.0.0 (Hagiwara and Mita, LREC 2020): typo fixes from commits, with the
  words before the typo. Evaluation only. A right word goes to the selection set or to the
  held-out set by a hash of the word, as build_external_english_cases.py splits its words.
- Roger Mitton's Birkbeck and Holbrook lists: the usable pairs that are in no round 1 dev or test
  case of any list. Evaluation only, held-out set. They have no context.
- Roger Mitton's Wikipedia list of common misspellings: training only (build_cases2.py puts each
  pair into training sentences).

A GitHub case is kept when the edit changes one word, both forms are plain words in lower case or
with a first capital, the right word is common (Zipf 3.5 or more) and the wrong form is at most two
edits away. The category follows the wrong form:
- `github_misspelling`: the wrong form is not a common word (Zipf under 3.0), the rule of
  build_external_english_cases.py.
- `github_real_word`: the wrong form is a common word (Zipf 4.0 or more) one edit away, the limits
  of `real_word_slip` in build_english_cases.py. Some of these edits fix grammar, not a slip.
The context is the run of plain words of the vocabulary right before the typo, inside the sentence.

Usage, from the repository root (needs wordfreq):
    python3 scripts/lm-finetune2/build_real_typo_cases.py --corpora build/lm-finetune2/corpora \
        --round1-external ROUND1/build/typing-evaluation/external --out build/lm-finetune2/data
"""
import argparse
import gzip
import hashlib
import json
import random
import re
import sys
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "typing-evaluation"))
from wordfreq import top_n_list, zipf_frequency  # noqa: E402

import build_external_english_cases as ext  # noqa: E402

GITHUB_FILE = "github-typo/github-typo-corpus.v1.0.0.jsonl.gz"
GITHUB_SHA256 = "98219d275a49ad28fca832891876c255581b890d893b6d9c974ceb454ba2909d"
WIKIPEDIA_FILE = "wikipedia/wikipedia.dat"
SEED = "lm-finetune2-20261110"
EDGE = ".,!?;:\"()[]"
SENTENCE_END = ".!?:;"
WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
RIGHT_MINIMUM_ZIPF = 3.5
MISSPELLING_MAXIMUM_ZIPF = 3.0
REAL_WORD_MINIMUM_ZIPF = 4.0
MAX_CONTEXT_WORDS = 12
# One wrong and right pair gives at most this many cases, so one frequent typo does not fill a set.
CASES_PER_PAIR = 3
GITHUB_CASES_PER_CATEGORY = {"github_misspelling": 1500, "github_real_word": 1000}
MITTON_REMAINDER_PER_SOURCE_AND_HALF = 300


def plain_shape(token: str) -> bool:
    """A word in lower case, or with a first capital only."""
    return token.isascii() and token.isalpha() and (token.islower() or (token[0].isupper() and token[1:].islower()) or token == "I")


def split_edges(token: str) -> tuple[str, str, str]:
    start, end = 0, len(token)
    while start < end and token[start] in EDGE:
        start += 1
    while end > start and token[end - 1] in EDGE:
        end -= 1
    return token[:start], token[start:end], token[end:]


def context_before(tokens: list[str], vocabulary: set[str]) -> list[str]:
    """The plain words right before the typo, back to the start of the sentence or to the first
    token that is not a plain word of the vocabulary."""
    words = []
    for raw in reversed(tokens):
        if len(words) == MAX_CONTEXT_WORDS:
            break
        head, core, tail = split_edges(raw.replace("’", "'"))
        if any(mark in tail for mark in SENTENCE_END):
            break
        word = core.lower()
        shaped = plain_shape(core.replace("'", "")) if core else False
        if not shaped or not WORD.fullmatch(word) or word not in vocabulary:
            break
        words.append(word)
        if head and any(mark in head for mark in "([\""):
            break
    return list(reversed(words))


def github_cases(path: Path, report: dict) -> dict[str, list[dict]]:
    vocabulary = set(top_n_list("en", 60000))
    seen, per_pair, found = set(), {}, {"select": [], "holdout": []}
    counts = {"english_typo_edits": 0, "one_word_edits": 0, "plain_pairs": 0}
    with gzip.open(path, "rt", encoding="utf-8") as file:
        for line in file:
            commit = json.loads(line)
            for edit in commit["edits"]:
                if edit["src"]["lang"] != "eng" or edit["tgt"]["lang"] != "eng" or not edit.get("is_typo"):
                    continue
                counts["english_typo_edits"] += 1
                source, target = edit["src"]["text"].split(), edit["tgt"]["text"].split()
                if len(source) != len(target):
                    continue
                changed = [index for index, (a, b) in enumerate(zip(source, target)) if a != b]
                if len(changed) != 1:
                    continue
                counts["one_word_edits"] += 1
                index = changed[0]
                head_a, wrong, tail_a = split_edges(source[index])
                head_b, right, tail_b = split_edges(target[index])
                if (head_a, tail_a) != (head_b, tail_b) or not wrong or not right:
                    continue
                if not (plain_shape(wrong) and plain_shape(right)) or wrong.lower() == right.lower():
                    continue
                wrong, right = wrong.lower(), right.lower()
                counts["plain_pairs"] += 1
                distance = ext.edits(wrong, right)
                wrong_zipf = zipf_frequency(wrong, "en")
                if zipf_frequency(right, "en") < RIGHT_MINIMUM_ZIPF or distance > 2 or len(wrong) < 2:
                    continue
                if wrong_zipf < MISSPELLING_MAXIMUM_ZIPF:
                    category = "github_misspelling"
                elif wrong_zipf >= REAL_WORD_MINIMUM_ZIPF and distance == 1 and len(right) >= 3:
                    category = "github_real_word"
                else:
                    continue
                context = " ".join(context_before(target[:index], vocabulary))
                key = (category, context, wrong, right)
                if key in seen or per_pair.get((wrong, right), 0) >= CASES_PER_PAIR:
                    continue
                seen.add(key)
                per_pair[(wrong, right)] = per_pair.get((wrong, right), 0) + 1
                split = "select" if zlib.crc32(right.encode()) % 2 == 0 else "holdout"
                found[split].append({"category": category, "context": context, "typed": wrong, "intended": right,
                                     "source": f"github-typo-corpus:{commit['commit'][:12]}"})
    cases = {}
    for split, rows in found.items():
        kept = []
        for category, limit in GITHUB_CASES_PER_CATEGORY.items():
            members = sorted((row for row in rows if row["category"] == category),
                             key=lambda row: (row["context"], row["typed"], row["intended"], row["source"]))
            rng = random.Random(f"{SEED}-github-{split}-{category}")
            picks = rng.sample(members, min(limit, len(members)))
            for number, row in enumerate(picks):
                kept.append({"id": f"en-{split}-{category}-{number:04d}", "split": split, **row})
            counts[f"{split}_{category}_usable"] = len(members)
            counts[f"{split}_{category}_kept"] = len(picks)
            counts[f"{split}_{category}_with_context"] = sum(1 for row in picks if row["context"])
        cases[split] = kept
    report["github"] = counts
    return cases


def mitton_remainder(cache: Path, round1_external: Path, report: dict) -> list[dict]:
    """The usable Birkbeck, Holbrook and Aspell pairs that round 1 did not sample. The function
    repeats the sample of build_external_english_cases.py and stops unless it equals the round 1
    files."""
    ext.CACHE = cache
    old = {half: [json.loads(line) for line in (round1_external / f"english.{half}.jsonl").read_text(encoding="utf-8").splitlines() if line]
           for half in ("dev", "test")}
    # A pair of one list can be a round 1 case from another list, so every round 1 pair is left out.
    published = {(case["typed"], case["intended"]) for rows in old.values() for case in rows}
    cases, counts, held = [], {}, set()
    for source, name in ext.SOURCES.items():
        kept = {"dev": [], "test": []}
        for wrong, right in sorted(set(ext.read_pairs(name))):
            if not (wrong.isalpha() and right.isalpha() and wrong.isascii() and right.isascii()) or wrong == right:
                continue
            if zipf_frequency(right, "en") < 3.5 or zipf_frequency(wrong, "en") >= 3.0 or ext.edits(wrong, right) > 2:
                continue
            kept["dev" if zlib.crc32(right.encode()) % 2 == 0 else "test"].append((wrong, right))
        for half, pairs in kept.items():
            rng = random.Random(f"{ext.SEED}-{source}-{half}")
            sampled = rng.sample(pairs, min(ext.CASES_PER_SOURCE, len(pairs)))
            before = [(case["typed"], case["intended"]) for case in old[half] if case["category"] == f"real_misspelling_{source}"]
            if sampled != before:
                raise SystemExit(f"the {source} {half} sample of round 1 does not repeat: the list file changed")
            rest = [pair for pair in pairs if pair not in published and pair not in held]
            rng = random.Random(f"{SEED}-mitton-remainder-{source}-{half}")
            picks = rng.sample(rest, min(MITTON_REMAINDER_PER_SOURCE_AND_HALF, len(rest)))
            held |= set(picks)
            for wrong, right in picks:
                cases.append({"category": f"real_misspelling_{source}", "context": "", "typed": wrong, "intended": right,
                              "source": f"mitton:{name}:{half}-remainder"})
            counts[f"{source}_{half}"] = {"usable": len(pairs), "round1": len(sampled), "remainder": len(rest), "kept": len(picks)}
    numbers = {}
    for case in cases:
        number = numbers.get(case["category"], 0)
        numbers[case["category"]] = number + 1
        case.update({"id": f"en-holdout-{case['category']}-{number:04d}", "split": "holdout"})
    report["mitton_remainder"] = counts
    return [{key: case[key] for key in ("id", "split", "category", "context", "typed", "intended", "source")} for case in cases]


def wikipedia_pairs(path: Path, report: dict) -> list[dict]:
    pairs, right = [], None
    for line in path.read_text(encoding="latin-1").splitlines():
        line = line.strip()
        if line.startswith("$"):
            right = line[1:]
        elif line and right is not None:
            pairs.append((line.split()[0], right))
    kept = []
    for wrong, right in sorted(set(pairs)):
        if not (wrong.isalpha() and right.isalpha() and wrong.isascii() and right.isascii() and wrong.islower() and right.islower()):
            continue
        if zipf_frequency(right, "en") < 3.5 or zipf_frequency(wrong, "en") >= 3.0 or ext.edits(wrong, right) > 2:
            continue
        kept.append({"typed": wrong, "intended": right})
    report["wikipedia"] = {"pairs": len(set(pairs)), "usable": len(kept)}
    return kept


def write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpora", type=Path, required=True)
    parser.add_argument("--round1-external", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    github = arguments.corpora / GITHUB_FILE
    if hashlib.sha256(github.read_bytes()).hexdigest() != GITHUB_SHA256:
        raise SystemExit(f"{github} is not the pinned file")
    wikipedia = arguments.corpora / WIKIPEDIA_FILE
    if not wikipedia.exists():
        wikipedia.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(ext.BASE_URL + "wikipedia.dat", headers={"User-Agent": "duo-keyboard-build/1.0"})
        with urllib.request.urlopen(request) as response:
            wikipedia.write_bytes(response.read())
    report = {"github_sha256": GITHUB_SHA256, "wikipedia_sha256": hashlib.sha256(wikipedia.read_bytes()).hexdigest()}
    arguments.out.mkdir(parents=True, exist_ok=True)
    cases = github_cases(github, report)
    write(arguments.out / "cases.github.select.jsonl", cases["select"])
    write(arguments.out / "cases.github.holdout.jsonl", cases["holdout"])
    remainder = mitton_remainder(arguments.corpora / "mitton", arguments.round1_external, report)
    write(arguments.out / "cases.mitton-remainder.holdout.jsonl", remainder)
    write(arguments.out / "pairs.wikipedia.train.jsonl", wikipedia_pairs(wikipedia, report))
    report["mitton_files_sha256"] = {name: hashlib.sha256((arguments.corpora / "mitton" / name).read_bytes()).hexdigest()
                                     for name in ext.SOURCES.values()}
    (arguments.out / "real-typo-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

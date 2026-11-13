"""Checks the rules of the fresh held-out set, apart from the code that built it.

The script reads the six files of build/lm-domain/data/fresh-holdout and stops at the first rule
that a case breaks. It prints counts only, and no case text.

Rules:
 1. Each file has the SHA-256 value of report.json, and the ids of a file are unique.
 2. A Tatoeba source lies in a held-out bucket of round 2: SHA-256 of "lm-finetune2:" and the id,
    modulo 20, is 0, 1 or 2.
 3. A Tatoeba source is the source of no case of round 1 (dev, test, train, stop, tune), of no
    training, stopping, tuning or selection case of round 2, of no held-out case of round 2, and
    of no dev or test case of the pack.
 4. A Tatoeba sentence of the generated cases and streams has the words of no training sentence.
 5. A Tatoeba sentence feeds one file only, except that a generated case and a stream do not share one.
 6. A GitHub case has a right word of the held-out half (CRC-32 of the word is odd). Its row and
    its pair are no pick of round 2. The script repeats the picks of round 2 with
    build_real_typo_cases.py and compares their SHA-256 value with the value that the round 2
    README gives for its file, so it does not read that file.
 7. A Birkbeck pair is in no published case of round 1 and is no pick of round 2, checked the same way.
 8. A technical source lies in the test bucket of the domain text, and is the source of no dev or
    test case of the pack. The letters of its sentence, where a stream holds the whole sentence,
    differ from every sentence of the dev and test streams.
 9. A domain slip case has the typed and intended pair of no training case and of no dev or test
    case of the pack. A domain case equals no dev or test case of the pack.
10. A word of a list-based clean category, and an open word of a stream, stands in no training sentence.
11. For a later set (--earlier): the set shares no source with an earlier set of the builder. No
    Tatoeba source, no sentence, no list word, no GitHub row, pair or commit, no Birkbeck pair, no
    technical document, no stream sentence with the same letters, and no domain pair or case.
    A GitHub case also shares no commit with a case of the select half or of round 2, and a
    GitHub or Birkbeck pair is the pair of no real misspelling of round 2 in either list.
12. For a set with a real-word file: each case names an article and a revision of the RWSE
    Wikipedia Revision Dataset, and its pair is no pair of a GitHub case of the select half, of
    round 2 or of an earlier set.

Usage, from the repository root (needs wordfreq):
    uv run --with wordfreq python scripts/lm-domain/check_fresh_holdout.py --round1 ../lm-finetune \
        --round2 ../lm-finetune2 --data build/lm-domain/data
    uv run --with wordfreq python scripts/lm-domain/check_fresh_holdout.py --round1 ../lm-finetune \\
        --round2 ../lm-finetune2 --data build/lm-domain/data --set-folder confirm-holdout --label confirm \\
        --earlier build/lm-domain/data/fresh-holdout
"""
import argparse
import hashlib
import json
import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for folder in ("lm-finetune2", "lm-finetune", "typing-evaluation", "domain-pack"):
    sys.path.insert(0, str(ROOT / "scripts" / folder))
from wordfreq import top_n_list  # noqa: E402

import build_real_typo_cases as typo  # noqa: E402
from collect_corpus import bucket_of  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
# The SHA-256 values of the held-out files of round 2, from scripts/lm-finetune2/README.md.
ROUND2_GITHUB_SHA256 = "155e480fd160c1f1ec734459ce512e23cc9bc0dc07a152beef87de514fd09cf1"
ROUND2_MITTON_SHA256 = "ab7a32e824e916033e0ecde199ce132e20cde2040520619fb672ee85db0cc935"
LIST_CATEGORIES = {"clean_rare", "clean_names_and_terms", "clean_symbol_token"}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def tatoeba_id(case: dict) -> int | None:
    return int(case["source"].split(":", 1)[1]) if case["source"].startswith("tatoeba:") else None


def letters_of(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def stop(rule: int, text: str) -> None:
    raise SystemExit(f"rule {rule} is broken: {text}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round1", type=Path, required=True)
    parser.add_argument("--round2", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--set-folder", default="fresh-holdout", help="the folder of the set under --data")
    parser.add_argument("--label", default="fresh", help="the name of the set in its ids and file names")
    parser.add_argument("--earlier", type=Path, nargs="*", default=[], help="folders of earlier sets of the builder")
    arguments = parser.parse_args()
    folder = arguments.data / arguments.set_folder
    set_label = arguments.label
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    files = {}
    for name, entry in report["files"].items():
        raw = (folder / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            stop(1, f"{name} does not have the SHA-256 value of report.json")
        files[name] = read_jsonl(folder / name)
        if len({case["id"] for case in files[name]}) != len(files[name]) or len(files[name]) != entry["cases"]:
            stop(1, f"{name} holds an id twice or another count than report.json")
    generated, stream = files[f"cases.generated.{set_label}.jsonl"], files[f"cases.stream.{set_label}.jsonl"]
    github, birkbeck = files[f"cases.github.{set_label}.jsonl"], files[f"cases.birkbeck.{set_label}.jsonl"]
    domain, domain_stream = files[f"cases.domain.{set_label}.jsonl"], files[f"cases.domain-stream.{set_label}.jsonl"]
    real_word = files.get(f"cases.real-word.{set_label}.jsonl")
    expected = 6 if real_word is None else 7
    if len(files) != expected or any(case["split"] != set_label or f"-{set_label}-" not in case["id"] for cases in files.values() for case in cases):
        stop(1, f"the set does not hold {expected} files of the label {set_label}")
    counts: dict = {}

    # ---- Rules 2 to 5: the Tatoeba sources ----
    everyday = arguments.data / "everyday"
    round2_data = arguments.round2 / "build" / "lm-finetune2" / "data"
    earlier: dict[str, set[int]] = {}
    for label, paths in {
        "round 1 dev and test": [CASES / name for name in ("english.dev.jsonl", "english.test.jsonl", "english-symbols.dev.jsonl", "english-symbols.test.jsonl")],
        "round 1 train, stop and tune": [everyday / f"cases.{split}.jsonl" for split in ("train", "stop", "tune")],
        "round 2 train, stop, tune and select": [everyday / name for name in ("cases2.train.jsonl", "cases2.stop.jsonl", "cases.stream.tune.jsonl", "cases.stream.select.jsonl")],
        # Only the field `source` of these two files is read.
        "round 2 held-out": [round2_data / "cases.generated.holdout.jsonl", round2_data / "cases.stream.holdout.jsonl"],
        "pack dev and test": [CASES / f"{name}.{half}.jsonl" for name in ("english-domain", "english-domain-stream") for half in ("dev", "test")],
    }.items():
        ids = set()
        for path in paths:
            with path.open(encoding="utf-8") as file:
                for line in file:
                    source = json.loads(line)["source"]
                    if source.startswith("tatoeba:"):
                        ids.add(int(source.split(":", 1)[1]))
        earlier[label] = ids
    training_cases = [case for name in ("cases.train.jsonl", "cases.stop.jsonl", "cases2.train.jsonl", "cases2.stop.jsonl")
                      for case in read_jsonl(everyday / name)]
    domain_training = [case for split in ("train", "stop") for case in read_jsonl(arguments.data / "domain" / f"cases.{split}.jsonl")]
    training_texts = {case["sentence"] for case in training_cases}
    training_words = {word for text in training_texts for word in text.split(" ")}
    for case in domain_training:
        for token in (case["context"] + " " + case["intended"]).lower().split():
            training_words.add(token.strip(".,!?;:\"()[]"))
    training_pairs = {(case["typed"].lower(), case["intended"].lower()) for case in training_cases + domain_training
                      if case["typed"].lower() != case["intended"].lower()}
    per_file: dict[str, set[int]] = {}
    for name, cases in files.items():
        ids = {tatoeba_id(case) for case in cases} - {None}
        per_file[name] = ids
        for sentence_id in ids:
            if int(hashlib.sha256(f"lm-finetune2:{sentence_id}".encode()).hexdigest(), 16) % 20 > 2:
                stop(2, f"{name} holds a Tatoeba source outside the held-out buckets")
        for label, used in earlier.items():
            if ids & used:
                stop(3, f"{name} shares {len(ids & used)} Tatoeba sources with {label}")
    counts["tatoeba_sources"] = {name: len(ids) for name, ids in per_file.items() if ids}
    for case in generated + stream:
        if case.get("sentence") in training_texts:
            stop(4, "a sentence has the words of a training sentence")
    if per_file[f"cases.generated.{set_label}.jsonl"] & per_file[f"cases.stream.{set_label}.jsonl"]:
        stop(5, "a generated case and a stream share a sentence")
    if per_file[f"cases.domain.{set_label}.jsonl"] & (per_file[f"cases.generated.{set_label}.jsonl"] | per_file[f"cases.stream.{set_label}.jsonl"]):
        stop(5, "a domain case shares a sentence with a generated case or a stream")

    # ---- Rules 6 and 7: real misspellings ----
    def as_file(rows: list[dict]) -> str:
        return hashlib.sha256("".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")).hexdigest()

    corpora = arguments.round2 / "build" / "lm-finetune2" / "corpora"
    external = arguments.round1 / "build" / "typing-evaluation" / "external"
    picks = typo.github_cases(corpora / typo.GITHUB_FILE, {})["holdout"]
    if as_file(picks) != ROUND2_GITHUB_SHA256:
        stop(6, "the repeated GitHub picks of round 2 do not have the SHA-256 value of the round 2 README")
    pick_rows = {(row["category"], row["context"], row["typed"], row["intended"], row["source"]) for row in picks}
    pick_pairs = {(row["typed"], row["intended"]) for row in picks}
    select_words = {case["intended"] for case in read_jsonl(everyday / "cases.github.select.jsonl")}
    for case in github:
        if zlib.crc32(case["intended"].encode()) % 2 == 0 or case["intended"] in select_words:
            stop(6, "a GitHub case has a right word of the select half")
        if (case["category"], case["context"], case["typed"], case["intended"], case["source"]) in pick_rows \
                or (case["typed"], case["intended"]) in pick_pairs:
            stop(6, "a GitHub case is a pick of round 2")
    mitton = typo.mitton_remainder(corpora / "mitton", external, {})
    if as_file(mitton) != ROUND2_MITTON_SHA256:
        stop(7, "the repeated Mitton picks of round 2 do not have the SHA-256 value of the round 2 README")
    earlier_pairs = {(case["typed"], case["intended"]) for case in mitton}
    for half in ("dev", "test"):
        earlier_pairs |= {(case["typed"], case["intended"]) for case in read_jsonl(external / f"english.{half}.jsonl")}
    for case in birkbeck:
        if (case["typed"], case["intended"]) in earlier_pairs:
            stop(7, "a Birkbeck pair is an earlier case")
    counts["github"] = len(github)
    counts["birkbeck"] = len(birkbeck)

    # ---- Rules 8 and 9: the domain cases ----
    pack_cases = [case for half in ("dev", "test") for name in ("english-domain", "english-domain-stream")
                  for case in read_jsonl(CASES / f"{name}.{half}.jsonl")]
    pack_sources = {case["source"] for case in pack_cases}
    pack_pairs = {(case["typed"].lower(), case["intended"].lower()) for case in pack_cases if case["typed"].lower() != case["intended"].lower()}
    pack_texts = {(case["context"], case["typed"], case["intended"]) for case in pack_cases}
    stream_letters = {letters_of(case["typed"]) for case in pack_cases if "stream" in case}
    technical = 0
    for case in domain + domain_stream:
        source = case["source"]
        if source.split(":", 1)[0] in ("arxiv", "stackexchange", "github"):
            technical += 1
            if bucket_of(source) != "test":
                stop(8, "a technical source lies outside the test bucket")
            if source in pack_sources:
                stop(8, "a technical source is the source of a dev or test case of the pack")
    for case in domain_stream:
        if letters_of(case["typed"]) in stream_letters:
            stop(8, "a stream sentence has the letters of a dev or test stream sentence")
    for case in domain:
        pair = (case["typed"].lower(), case["intended"].lower())
        if pair[0] != pair[1] and (pair in training_pairs or pair in pack_pairs):
            stop(9, "a domain slip case has the pair of a training case or of a dev or test case")
        if (case["context"], case["typed"], case["intended"]) in pack_texts:
            stop(9, "a domain case equals a dev or test case of the pack")
    counts["technical_sources_checked"] = technical

    # ---- Rule 10: list words and open words ----
    vocabulary = set(top_n_list("en", 60000))
    list_words = {case["intended"] for case in generated if case["category"] in LIST_CATEGORIES}
    if list_words & training_words:
        stop(10, f"{len(list_words & training_words)} list words stand in a training sentence")
    open_words = {word for case in stream if case["category"] == "clean_stream_open" for word in case["typed"].split(" ")
                  if word not in vocabulary}
    if open_words & training_words:
        stop(10, f"{len(open_words & training_words)} open words stand in a training sentence")
    counts["list_words"] = len(list_words)
    counts["open_words"] = len(open_words)

    # ---- Rule 11: no source of an earlier set of the builder ----
    if arguments.earlier:
        earlier = [case for old in arguments.earlier for path in sorted(old.glob("cases.*.jsonl")) for case in read_jsonl(path)]
        if not earlier:
            stop(11, "a folder of --earlier holds no case file")
        mine = [case for cases in files.values() for case in cases]
        old_tatoeba = {tatoeba_id(case) for case in earlier} - {None}
        shared = old_tatoeba & ({tatoeba_id(case) for case in mine} - {None})
        if shared:
            stop(11, f"{len(shared)} Tatoeba sources are sources of an earlier set")
        if {case["sentence"] for case in earlier if "sentence" in case} & {case["sentence"] for case in mine if "sentence" in case}:
            stop(11, "a sentence is a sentence of an earlier set")
        if {case["intended"] for case in earlier if case.get("category") in LIST_CATEGORIES} & list_words:
            stop(11, "a list word is a list word of an earlier set")
        old_real = [case for case in earlier if case["source"].startswith(("github-typo-corpus:", "mitton:"))]
        old_rows = {(case["category"], case["context"], case["typed"], case["intended"], case["source"]) for case in old_real}
        # The pair of an earlier real misspelling stays out of both lists, whichever list held it.
        old_pairs = {(case["typed"], case["intended"]) for case in old_real} | pick_pairs | {(case["typed"], case["intended"]) for case in mitton}
        old_commits = {case["source"] for case in old_real if case["source"].startswith("github-typo-corpus:")}
        # One commit can hold several edits, so the commits of the select half and of round 2 stay out too.
        old_commits |= {row["source"] for row in picks} | {case["source"] for case in read_jsonl(everyday / "cases.github.select.jsonl")}
        for case in github + birkbeck + (real_word or []):
            if (case["category"], case["context"], case["typed"], case["intended"], case["source"]) in old_rows \
                    or (case["typed"], case["intended"]) in old_pairs or case["source"] in old_commits:
                stop(11, "a real misspelling has the row, the pair or the commit of an earlier set")
        old_domain = [case for case in earlier if case["id"].startswith("endom-") or "stream" in case]
        old_documents = {case["source"] for case in old_domain if case["source"].split(":", 1)[0] in ("arxiv", "stackexchange", "github")}
        if old_documents & {case["source"] for case in domain + domain_stream}:
            stop(11, "a technical document is a document of an earlier set")
        if {letters_of(case["typed"]) for case in old_domain if "stream" in case} & {letters_of(case["typed"]) for case in domain_stream}:
            stop(11, "a stream sentence has the letters of a stream sentence of an earlier set")
        old_domain_pairs = {(case["typed"].lower(), case["intended"].lower()) for case in old_domain if case["typed"].lower() != case["intended"].lower()}
        old_domain_texts = {(case["context"], case["typed"], case["intended"]) for case in old_domain}
        for case in domain:
            pair = (case["typed"].lower(), case["intended"].lower())
            if (pair[0] != pair[1] and pair in old_domain_pairs) or (case["context"], case["typed"], case["intended"]) in old_domain_texts:
                stop(11, "a domain case has the pair of an earlier set or equals one of its cases")
        counts["earlier_cases_checked"] = len(earlier)

    # ---- Rule 12: the real-word file ----
    if real_word is not None:
        earlier_pairs = pick_pairs | {(case["typed"], case["intended"]) for case in read_jsonl(everyday / "cases.github.select.jsonl")}
        for case in real_word:
            if not re.fullmatch(r"rwse-wikipedia:\d+:\d+", case["source"]) or case["category"] != "wikipedia_real_word":
                stop(12, "a real-word case does not name an article and a revision")
            if (case["typed"], case["intended"]) in earlier_pairs or case["typed"] == case["intended"]:
                stop(12, "a real-word case has the pair of an earlier GitHub case")
        counts["real_word"] = len(real_word)
    print(json.dumps({"passes": True, "counts": counts}))


if __name__ == "__main__":
    main()

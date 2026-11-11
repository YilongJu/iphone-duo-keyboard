"""Checks the new cases of round 2 against every earlier split, apart from the code of build_cases2.py.

The check fails when
1. a new Tatoeba case comes from a dev or test source sentence (by id or by its words), from a
   sentence equal to a dev or test context, or from a sentence that holds a dev or test context
   followed by that case's intended text (the four rules of scripts/lm-finetune/check_leakage.py);
2. a new Tatoeba case comes from the source sentence of a round 1 training, stopping or tuning
   case, by id or by its words;
3. two of the new splits (holdout, select, tune, stop, train) share a sentence, by id or by words;
4. a new training or stopping case has the typed text of an evaluation set of real misspellings;
5. a new training or stopping sentence holds a word of a list-based clean category of the held-out
   set, or a word outside the vocabulary of a tune, select or holdout stream sentence;
6. a word of a list-based clean category of the held-out set is the intended text of a round 1 case;
7. the select half and the holdout half of the GitHub typos share a right word;
8. a Mitton held-out pair is a round 1 dev or test case of any list, or stands twice.

The check also counts, without failing, the generated held-out cases whose context and intended
text stand in a training sentence, and those whose typed and intended pair is a training case or
the typed span and target of a training or stopping list (round 1 lists and the new lists). It
counts the held-out list words that a training list shows in its context or among its readings.
The results report the held-out counts for both kinds apart.

--self-test plants one fault of each kind in a copy in memory and stops unless each one is found.

Usage, from the repository root:
    python3 scripts/lm-finetune2/check_leakage2.py --round1 ROUND1_WORKTREE --data build/lm-finetune2/data
"""
import argparse
import bz2
import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
HELD = ["english.dev.jsonl", "english.test.jsonl", "english-symbols.dev.jsonl", "english-symbols.test.jsonl"]
EDGE = ".,!?;:\"()[]"
WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
LIST_CATEGORIES = {"clean_rare", "clean_names_and_terms", "clean_symbol_token"}
NEW_FILES = {"holdout": ["cases.generated.holdout.jsonl", "cases.stream.holdout.jsonl"], "select": ["cases.stream.select.jsonl"],
             "tune": ["cases.stream.tune.jsonl"], "stop": ["cases2.stop.jsonl"], "train": ["cases2.train.jsonl"]}
REAL_TYPO_FILES = ["cases.github.select.jsonl", "cases.github.holdout.jsonl", "cases.mitton-remainder.holdout.jsonl"]


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def words_of(text: str) -> str | None:
    words = []
    for raw in text.lower().replace("’", "'").split():
        word = raw.strip(EDGE)
        if not WORD.fullmatch(word):
            return None
        words.append(word)
    return " ".join(words)


def source_id(case: dict) -> int:
    return int(case["source"].split(":")[1])


def check(new: dict, real: dict, loaded: dict) -> tuple[dict, list[str]]:
    held, round1, vocabulary = loaded["held"], loaded["round1"], loaded["vocabulary"]
    held_ids = {source_id(c) for c in held if c["source"].startswith("tatoeba:")}
    source_texts = {loaded["export_texts"][i] for i in held_ids}
    contexts = {c["context"] for c in held if c["context"]}
    phrases = {tuple((c["context"] + " " + c["intended"].strip().lower()).split(" ")) for c in held if c["context"]}
    lengths = sorted({len(p) for p in phrases})

    def holds(text: str, wanted: set, sizes: list[int]) -> bool:
        words = tuple(text.split(" "))
        return any(words[i:i + n] in wanted for n in sizes for i in range(len(words) - n + 1))

    round1_ids = {source_id(c) for c in round1}
    round1_texts = {c["sentence"] for c in round1}
    report, failures = {}, []
    sentences = {}
    for split, cases in new.items():
        by_id = {source_id(c): c["sentence"] for c in cases}
        sentences[split] = by_id
        problems = {
            "dev_or_test_id": sum(1 for i in by_id if i in held_ids),
            "same_as_dev_or_test_source": sum(1 for text in by_id.values() if text in source_texts),
            "same_as_dev_or_test_context": sum(1 for text in by_id.values() if text in contexts),
            "holds_dev_or_test_context_and_intended": sum(1 for text in by_id.values() if holds(text, phrases, lengths)),
            "context_not_from_sentence": sum(1 for c in cases if not (c["sentence"] + " ").startswith(c["context"] + " " if c["context"] else "")),
            "round1_id": sum(1 for i in by_id if i in round1_ids),
            "same_as_round1_sentence": sum(1 for text in by_id.values() if text in round1_texts),
        }
        report[split] = {"cases": len(cases), "sentences": len(by_id), **problems}
        failures += [f"{split}: {name}" for name, count in problems.items() if count]
    order = list(new)
    shared = {}
    for index, first in enumerate(order):
        for second in order[index + 1:]:
            ids = len(set(sentences[first]) & set(sentences[second]))
            texts = len(set(sentences[first].values()) & set(sentences[second].values()))
            shared[f"{first}-{second}"] = {"ids": ids, "texts": texts}
            if ids or texts:
                failures.append(f"{first} and {second} share a sentence")
    report["shared_between_new_splits"] = shared

    evaluation_typed = {c["typed"] for cases in real.values() for c in cases} | {c["typed"] for c in loaded["published"]}
    typed_hits = sum(1 for split in ("stop", "train") for c in new[split]
                     if c["category"] not in ("clean_stream_closed", "clean_stream_open") and c["typed"] in evaluation_typed)
    report["training_typed_is_an_evaluation_misspelling"] = typed_hits
    if typed_hits:
        failures.append("a training case has the typed text of an evaluation misspelling")

    guarded = {c["intended"] for c in new["holdout"] if c["category"] in LIST_CATEGORIES}
    list_words_in_round1 = sum(1 for c in round1 if any(word in guarded for word in c["intended"].split(" ")))
    for split in ("holdout", "select", "tune"):
        guarded |= {word for c in new[split] if c["category"] == "clean_stream_open" for word in c["sentence"].split(" ") if word not in vocabulary}
    guarded_hits = sum(1 for split in ("stop", "train") for text in sentences[split].values() if any(word in guarded for word in text.split(" ")))
    report["training_sentence_holds_a_guarded_word"] = guarded_hits
    report["holdout_list_word_in_a_round1_case"] = list_words_in_round1
    if guarded_hits:
        failures.append("a training sentence holds a guarded word")
    if list_words_in_round1:
        failures.append("a held-out list word is in a round 1 case")

    published_pairs = {(c["typed"], c["intended"]) for c in loaded["published"]}
    mitton = [(c["typed"], c["intended"]) for c in real["cases.mitton-remainder.holdout.jsonl"]]
    report["mitton_pair_in_round1_dev_or_test"] = sum(1 for pair in mitton if pair in published_pairs)
    report["mitton_pair_twice"] = len(mitton) - len(set(mitton))
    if report["mitton_pair_in_round1_dev_or_test"] or report["mitton_pair_twice"]:
        failures.append("a Mitton held-out pair is a round 1 case or stands twice")

    right_words = len({c["intended"] for c in real["cases.github.select.jsonl"]} & {c["intended"] for c in real["cases.github.holdout.jsonl"]})
    report["github_right_words_in_both_halves"] = right_words
    if right_words:
        failures.append("the GitHub halves share a right word")

    # Counted, not failed: held-out phrases and pairs that training also holds.
    training = [c for c in round1 if c["split"] == "train"] + new["train"]
    generated = [c for c in new["holdout"] if not c["category"].startswith("clean_stream")]
    wanted = {tuple((c["context"] + " " + c["intended"].strip().lower()).split(" ")) for c in generated if c["context"]}
    sizes = sorted({len(p) for p in wanted})
    seen_phrases = set()
    for text in {c["sentence"] for c in training}:
        words = tuple(text.split(" "))
        for n in sizes:
            for i in range(len(words) - n + 1):
                if words[i:i + n] in wanted:
                    seen_phrases.add(words[i:i + n])
    pairs = {(c["typed"], c["intended"]) for c in training if c["typed"] != c["intended"]}
    report["holdout_generated_seen_in_training"] = {
        "cases": len(generated), "with_context": sum(1 for c in generated if c["context"]),
        "phrase_in_a_training_sentence": sum(1 for c in generated if c["context"]
                                             and tuple((c["context"] + " " + c["intended"].strip().lower()).split(" ")) in seen_phrases),
        "slip_cases": sum(1 for c in generated if c["typed"] != c["intended"]),
        "slip_pair_is_a_training_case": sum(1 for c in generated if (c["typed"], c["intended"]) in pairs)}
    # A training list can hold a pair that no training case holds, such as "welcom" with the target
    # "welcome" on the way through the case "welcom e". The lists are what the model reads.
    list_pairs = loaded["training_list_pairs"]
    report["holdout_generated_seen_in_training"]["slip_pair_is_a_training_list"] = sum(
        1 for c in generated if c["typed"] != c["intended"] and (c["typed"], c["intended"]) in list_pairs)
    real_pairs = {}
    for name, cases in real.items():
        real_pairs[name] = {"cases": len(cases), "pair_is_a_training_case": sum(1 for c in cases if (c["typed"], c["intended"]) in pairs),
                            "pair_is_a_training_list": sum(1 for c in cases if (c["typed"], c["intended"]) in list_pairs)}
    list_words = {c["intended"] for c in new["holdout"] if c["category"] in LIST_CATEGORIES}
    report["holdout_list_words"] = {"words": len(list_words), "in_a_training_list_context": len(list_words & loaded["training_list_context_words"]),
                                    "among_the_readings_of_a_training_list": len(list_words & loaded["training_list_reading_words"])}
    report["real_typo_pairs_seen_in_training"] = real_pairs
    return report, failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round1", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()

    from wordfreq import top_n_list
    held = [c for name in HELD for c in read_jsonl(CASES / name)]
    held_ids = {source_id(c) for c in held if c["source"].startswith("tatoeba:")}
    export_texts = {}
    with bz2.open(arguments.round1 / "build" / "typing-evaluation" / "eng_sentences.tsv.bz2", "rt", encoding="utf-8") as file:
        for line in file:
            sentence_id, _, text = line.rstrip("\n").split("\t", 2)
            if int(sentence_id) in held_ids:
                export_texts[int(sentence_id)] = words_of(text)
    round1_data = arguments.round1 / "build" / "lm-finetune" / "data"
    loaded = {
        "held": held, "export_texts": export_texts, "vocabulary": set(top_n_list("en", 60000)),
        "round1": [c for split in ("train", "stop", "tune") for c in read_jsonl(round1_data / f"cases.{split}.jsonl")],
        "published": [c for half in ("dev", "test")
                      for c in read_jsonl(arguments.round1 / "build" / "typing-evaluation" / "external" / f"english.{half}.jsonl")],
    }
    import gzip
    list_pairs, context_words, reading_words = set(), set(), set()
    for path in (round1_data / "lists.train.jsonl.gz", round1_data / "lists.stop.jsonl.gz",
                 arguments.data / "lists2.train.jsonl.gz", arguments.data / "lists2.stop.jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as file:
            for line in file:
                item = json.loads(line)
                list_pairs.add((item["typed"], item["readings"][item["target"]][0]))
                context_words.update(item["context"].split(" "))
                for reading in item["readings"]:
                    reading_words.update(reading[0].split(" "))
    loaded.update({"training_list_pairs": list_pairs, "training_list_context_words": context_words,
                   "training_list_reading_words": reading_words})
    new = {split: [c for name in names for c in read_jsonl(arguments.data / name)] for split, names in NEW_FILES.items()}
    real = {name: read_jsonl(arguments.data / name) for name in REAL_TYPO_FILES}

    if arguments.self_test:
        dev_case = next(c for c in held if c["source"].startswith("tatoeba:") and c["context"])
        dev_text = export_texts[source_id(dev_case)]
        round1_case = loaded["round1"][0]
        plants = {
            "a dev sentence in the held-out set": lambda n, r: n["holdout"].append({**n["holdout"][0], "source": dev_case["source"], "sentence": dev_text, "context": ""}),
            "a round 1 sentence in the held-out set": lambda n, r: n["holdout"].append({**n["holdout"][0], "source": round1_case["source"], "sentence": round1_case["sentence"], "context": ""}),
            "a held-out sentence in training": lambda n, r: n["train"].append(dict(n["holdout"][0])),
            "an evaluation misspelling typed in training": lambda n, r: n["train"].append({**next(c for c in n["train"] if c["category"] == "real_misspelling_wikipedia"), "typed": r["cases.github.holdout.jsonl"][0]["typed"]}),
            "a held-out rare word in a training sentence": lambda n, r: n["train"].append({**n["train"][0], "source": "tatoeba:999999991", "context": "", "sentence": "we saw the " + next(c["intended"] for c in n["holdout"] if c["category"] == "clean_rare")}),
            "a right word in both GitHub halves": lambda n, r: r["cases.github.select.jsonl"].append(dict(r["cases.github.holdout.jsonl"][0])),
        }
        for label, plant in plants.items():
            planted_new, planted_real = copy.deepcopy(new), copy.deepcopy(real)
            plant(planted_new, planted_real)
            _, failures = check(planted_new, planted_real, loaded)
            if not failures:
                raise SystemExit(f"self-test: the check did not find {label}")
            print(f"self-test: found {label}: {failures}")

    report, failures = check(new, real, loaded)
    print(json.dumps(report, indent=2))
    (arguments.data / "leakage2-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if failures:
        raise SystemExit(f"leakage check failed: {failures}")
    print("leakage check passed")


if __name__ == "__main__":
    main()

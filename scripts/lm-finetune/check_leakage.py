"""Checks the training, stopping and tuning cases against the dev and test halves, apart from the
code of build_cases.py, with the pinned Tatoeba export.

The check fails when a new case comes from a dev or test source sentence (by id or by its
words), from a sentence equal to a dev or test context, or from a sentence that holds a dev or
test context followed by that case's intended text. It also fails when a training sentence
equals a sentence of the stopping or tuning split.

Usage, from the repository root:
    python3 scripts/lm-finetune/check_leakage.py --data build/lm-finetune/data \
        --export build/typing-evaluation/eng_sentences.tsv.bz2
"""
import argparse
import bz2
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
HELD = ["english.dev.jsonl", "english.test.jsonl", "english-symbols.dev.jsonl", "english-symbols.test.jsonl"]
EDGE = ".,!?;:\"()[]"
WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")


def words_of(text: str) -> str | None:
    words = []
    for raw in text.lower().replace("’", "'").split():
        word = raw.strip(EDGE)
        if not WORD.fullmatch(word):
            return None
        words.append(word)
    return " ".join(words)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    arguments = parser.parse_args()

    held = [json.loads(line) for name in HELD for line in (CASES / name).read_text(encoding="utf-8").splitlines() if line]
    held_ids = {int(c["source"].split(":")[1]) for c in held if c["source"].startswith("tatoeba:")}
    texts = {}
    with bz2.open(arguments.export, "rt", encoding="utf-8") as file:
        for line in file:
            sentence_id, _, text = line.rstrip("\n").split("\t", 2)
            if int(sentence_id) in held_ids:
                texts[int(sentence_id)] = words_of(text)
    source_texts = {texts[i] for i in held_ids}
    contexts = {c["context"] for c in held if c["context"]}
    phrases = {tuple((c["context"] + " " + c["intended"].strip().lower()).split(" ")) for c in held if c["context"]}
    lengths = sorted({len(p) for p in phrases})

    def holds_phrase(text: str) -> bool:
        words = tuple(text.split(" "))
        return any(words[i:i + n] in phrases for n in lengths for i in range(len(words) - n + 1))

    report, by_split = {}, {}
    for split in ("train", "stop", "tune"):
        cases = [json.loads(line) for line in (arguments.data / f"cases.{split}.jsonl").read_text(encoding="utf-8").splitlines() if line]
        sentences = {int(c["source"].split(":")[1]): c["sentence"] for c in cases}
        by_split[split] = set(sentences.values())
        problems = {
            "id": sum(1 for i in sentences if i in held_ids),
            "same_as_source": sum(1 for t in sentences.values() if t in source_texts),
            "same_as_context": sum(1 for t in sentences.values() if t in contexts),
            "holds_context_and_intended": sum(1 for t in sentences.values() if holds_phrase(t)),
            "context_not_from_sentence": sum(1 for c in cases if not (c["sentence"] + " ").startswith(c["context"] + " " if c["context"] else "")),
        }
        report[split] = {"cases": len(cases), "sentences": len(sentences), **problems}
    report["train_sentence_in_stop_or_tune"] = len(by_split["train"] & (by_split["stop"] | by_split["tune"]))
    report["stop_sentence_in_tune"] = len(by_split["stop"] & by_split["tune"])
    print(json.dumps(report, indent=2))
    failures = [k for s in ("train", "stop", "tune") for k, v in report[s].items() if k not in ("cases", "sentences") and v]
    if failures or report["train_sentence_in_stop_or_tune"] or report["stop_sentence_in_tune"]:
        raise SystemExit(f"leakage check failed: {failures}")
    print("leakage check passed")


if __name__ == "__main__":
    main()

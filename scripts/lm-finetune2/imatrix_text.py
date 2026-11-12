"""Writes the calibration text for the importance matrix of llama.cpp: 3,000 training lists of
round 2 (round 1 lists and the new lists), each as the text the model reads on the phone, the
typed format followed by the target reading.

A list whose tokens hold the lone space token is left out: llama.cpp b4846 gives token -1 for that
piece (lm_score.c repairs it), and llama-imatrix stops on it. The lists stand on one line with a
space between them, because b4846 gives token -1 for a line break too.

Usage, from the repository root, with the project's Python:
    uv run --project scripts/lm-finetune python scripts/lm-finetune2/imatrix_text.py --round1 ROUND1 \
        --data build/lm-finetune2/data --tokenizer-dir MODEL/hf --out build/lm-finetune2/imatrix-text.txt
"""
import argparse
import gzip
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import rerank  # noqa: E402

LISTS = 3000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round1", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--tokenizer-dir", type=Path, required=True, help="the Hugging Face folder of a fine-tune")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(arguments.tokenizer_dir)
    lone_space = tokenizer.convert_tokens_to_ids(chr(0x120))
    if not isinstance(lone_space, int) or lone_space < 0:
        raise SystemExit("the tokenizer does not hold the lone space token")
    lists = []
    for path in (arguments.round1 / "build" / "lm-finetune" / "data" / "lists.train.jsonl.gz", arguments.data / "lists2.train.jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as file:
            lists.extend(json.loads(line) for line in file)
    random.Random("lm-finetune2-imatrix").shuffle(lists)
    lines, skipped = [], 0
    for item in lists:
        if len(lines) == LISTS:
            break
        prompt = rerank.language_model_prompt(item["context"], item["typed"], "typed")
        target = rerank.language_model_text(item["readings"][item["target"]][0], not item["context"])
        line = prompt + " " + target
        if lone_space in tokenizer(" " + line, add_special_tokens=False)["input_ids"]:
            skipped += 1
            continue
        lines.append(line)
    # One line without a line break: b4846 also gives token -1 for the line break of this vocabulary.
    text = " ".join(lines)
    if lone_space in tokenizer(text, add_special_tokens=False)["input_ids"]:
        raise SystemExit("the whole text still holds the lone space token")
    arguments.out.write_bytes(text.encode("utf-8"))
    print(f"{len(lines)} lines, {skipped} left out for the lone space token, lone space token {lone_space}")


if __name__ == "__main__":
    main()

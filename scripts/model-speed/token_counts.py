"""Counts the tokens of English and Chinese text under each tokenizer of the shortlist.

Usage: python3 token_counts.py TOKENS_DIR CHINESE_TOKENS_DIR
  TOKENS_DIR          the tokens of the speed requests per model (speed_cli tokens on
                      Shared/model-speed-requests.tsv), MODEL.tokens
  CHINESE_TOKENS_DIR  the tokens of the Chinese texts per model (speed_cli tokens on the file
                      that `python3 token_counts.py --chinese-requests OUT.tsv` writes), MODEL.tokens
Prints per model the mean tokens of a context and of a candidate of the speed requests, the
English characters per token, and the Chinese characters per token.

`--chinese-requests OUT.tsv` writes the distinct intended texts of
scripts/typing-evaluation/cases/pinyin.dev.jsonl as contexts, each with the candidate "x".
"""

import json
import pathlib
import sys

REQUESTS = pathlib.Path("Shared/model-speed-requests.tsv")
PINYIN = pathlib.Path("scripts/typing-evaluation/cases/pinyin.dev.jsonl")


def chinese_texts():
    seen = []
    for line in PINYIN.read_text(encoding="utf-8").splitlines():
        text = json.loads(line)["intended"]
        if text not in seen:
            seen.append(text)
    return seen


def main():
    if sys.argv[1] == "--chinese-requests":
        pathlib.Path(sys.argv[2]).write_text("".join(text + "\tx\n" for text in chinese_texts()), encoding="utf-8")
        return
    tokens_dir, chinese_dir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    requests = [line.split("\t") for line in REQUESTS.read_text(encoding="utf-8").splitlines()]
    english_characters = sum(len(fields[0]) for fields in requests)
    chinese_characters = sum(len(text) for text in chinese_texts())
    print("| model | context tokens per request | tokens per candidate | English characters per token | "
          "Chinese characters per token |")
    print("| --- | --- | --- | --- | --- |")
    for path in sorted(tokens_dir.glob("*.tokens")):
        rows = [line.split("\t") for line in path.read_text().splitlines()]
        context = sum(len(row[1].split()) for row in rows)
        candidates = [len(field.split()) for row in rows for field in row[2:]]
        chinese = [line.split("\t") for line in (chinese_dir / path.name).read_text().splitlines()]
        chinese_tokens = sum(len(row[1].split()) for row in chinese)
        print(f"| {path.stem} | {context / len(rows):.1f} | {sum(candidates) / len(candidates):.2f} | "
              f"{english_characters / context:.2f} | {chinese_characters / chinese_tokens:.2f} |")


if __name__ == "__main__":
    main()

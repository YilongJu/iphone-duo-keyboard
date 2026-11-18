"""Check "Same pipeline as the first measurement" of the benchmark design.

The first measurement (README.md of the folder above) read the lower-case sentences of the dev
half of english-domain-stream, with a match that ignores capitals. With 2 typed letters, the
first 4 words held the right word at 54.2 of 100 positions for the engine's order, and at 67.8
for the model's order. This script gives the same two numbers from the parts of the benchmark:
the word tables and word values of tables.py and places.py, the stored next-token blocks of
blocks.py, and the engine lists of core.py. It keeps the text rules of the first measurement:
- every part of a sentence between two spaces is a word,
- the model reads the text with a capital at its start and with "I" for "i",
- a word's value is the highest value of its forms, and of its forms with a capital when the
  written word starts with a capital and a letter is typed,
- the first word of a field takes only the forms with a capital.

When the files of the first measurement are still in build/prediction-strip/ranks, the script
also counts the words whose place differs from the place of the first measurement.

Usage, in WSL, from the repository root:
    python3 scripts/prediction-strip/benchmark/check_pipeline.py --write-contexts
    (then blocks.py --name shipped --set legacy --half dev --contexts build/prediction-strip/bench/legacy-contexts.txt)
    uv run --with numpy python scripts/prediction-strip/benchmark/check_pipeline.py --cli build/prediction-strip/duo_cli
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import rules  # noqa: E402
from rerank import language_model_text, word_before_space  # noqa: E402

CASES = rules.ROOT / "scripts" / "typing-evaluation" / "cases" / "english-domain-stream.dev.jsonl"
CONTEXTS = rules.BENCH / "legacy-contexts.txt"
TYPED_LETTERS = 2
FIRST_WORDS = 4
WANTED = {"engine": 54.2, "model": 67.8}


def sentences() -> list[dict]:
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines()]


def contexts_of(cases: list[dict]) -> tuple[list[str], list[list[int]]]:
    numbers: dict[str, int] = {}
    per_case = []
    for case in cases:
        words = case["intended"].split(" ")
        per_case.append([numbers.setdefault(language_model_text(" ".join(words[:number]), True), len(numbers))
                         for number in range(len(words))])
    return list(numbers), per_case


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-contexts", action="store_true")
    parser.add_argument("--cli", type=Path)
    parser.add_argument("--name", default="shipped")
    args = parser.parse_args()
    cases = sentences()
    contexts, per_case = contexts_of(cases)
    if args.write_contexts:
        CONTEXTS.parent.mkdir(parents=True, exist_ok=True)
        CONTEXTS.write_text("\n".join(contexts), encoding="utf-8", newline="\n")
        print(f"{len(contexts)} texts for {sum(len(row) for row in per_case)} words")
        return

    import numpy as np
    import blocks as block_store
    import core
    from places import Values, place_of
    from tables import Tables

    tables = Tables(core.BENCH / "tables" / args.name)
    engine = core.Engine(args.cli, tables.words)
    stored = block_store.open_blocks(args.name, "legacy", "dev", contexts)
    ranks = tables.frequency_rank

    # The engine's lists, as engine_order.py of the first measurement asks for them.
    requests = []
    for case in cases:
        words = case["intended"].split(" ")
        for number, target in enumerate(words):
            if len(target) > TYPED_LETTERS:
                previous = word_before_space(" ".join(words[:number]) + " ") if number else ""
                requests.append((previous, target[:TYPED_LETTERS].lower()))
    lists = engine.lists(requests)

    old = {}
    for path in sorted((rules.ROOT / "build" / "prediction-strip" / "ranks").glob("shard-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            old[(row["id"], row["word"])] = row["places"]["A2"]
    words_total = 0
    found = {"engine": 0, "model": 0}
    compared = other = 0
    for case, numbers in zip(cases, per_case):
        words = case["intended"].split(" ")
        for number, target in enumerate(words):
            if len(target) <= TYPED_LETTERS:
                continue
            words_total += 1
            typed = target[:TYPED_LETTERS].lower()
            previous = word_before_space(" ".join(words[:number]) + " ") if number else ""
            listed = lists.get((previous, typed), [])
            if target.lower() in listed and listed.index(target.lower()) < FIRST_WORDS:
                found["engine"] += 1
            known = tables.index.get(target.lower())
            place = None
            if known is not None:
                values = Values(tables, stored[numbers[number]], bare=number == 0)
                only_capitals = number == 0 or target[0].isupper()
                vector = values.best_capital if only_capitals else values.best
                low, high, left_out = tables.span(typed)
                place = place_of(vector[low:high], vector[known], ranks[low:high], int(ranks[known]),
                                 None if left_out is None else left_out - low)
                if place < FIRST_WORDS:
                    found["model"] += 1
            before = old.get((case["id"], number))
            if before is not None:
                compared += 1
                if before[TYPED_LETTERS] != place:
                    other += 1
    failed = False
    for order in ("engine", "model"):
        share = 100.0 * found[order] / words_total
        same = round(share, 1) == WANTED[order]
        failed = failed or not same
        print(f"{order}'s order: {found[order]} of {words_total} words, {share:.2f} of 100; the first measurement gave "
              f"{WANTED[order]}: {'same' if same else 'OTHER'}")
    if compared:
        print(f"places of the model's order against the first measurement: {other} of {compared} words differ")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()

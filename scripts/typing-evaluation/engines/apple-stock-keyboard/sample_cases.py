"""Draws a fixed-seed sample of the typing test cases for the stock-keyboard measurement.

Key taps in the iOS Simulator are slow, so the measurement types a sample of each category.

Usage, from the repository root:
    python3 scripts/typing-evaluation/engines/apple-stock-keyboard/sample_cases.py \
        --cases scripts/typing-evaluation/cases/english.dev.jsonl --per-category 40 --seed 20261109 \
        --shard 0 --shards 2 --sample-out sample.jsonl --shard-out cases.jsonl

The script draws `--per-category` cases from each category with Python's `random.Random`, seeded
with the seed, the name of the case file and the category. `--first N` keeps the first N drawn
cases of each category, for a short trial run. The sample file lists the cases in turn from each
category. A shard holds every case whose position inside its category, modulo `--shards`, equals
`--shard`, so each job of the workflow types an equal share of every category.
"""
import argparse
import json
import random
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--per-category", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--first", type=int)
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shards", type=int, required=True)
    parser.add_argument("--sample-out", type=Path, required=True)
    parser.add_argument("--shard-out", type=Path, required=True)
    arguments = parser.parse_args()
    if not 0 <= arguments.shard < arguments.shards:
        raise SystemExit(f"--shard must lie in 0 to {arguments.shards - 1}")

    by_category: dict[str, list[dict]] = {}
    for line in arguments.cases.read_text(encoding="utf-8").splitlines():
        if line:
            case = json.loads(line)
            by_category.setdefault(case["category"], []).append(case)

    drawn: dict[str, list[dict]] = {}
    for category, cases in by_category.items():
        if len(cases) < arguments.per_category:
            raise SystemExit(f"category {category} holds {len(cases)} cases, fewer than {arguments.per_category}")
        generator = random.Random(f"{arguments.seed}:{arguments.cases.name}:{category}")
        picked = generator.sample(cases, arguments.per_category)
        drawn[category] = picked[: arguments.first] if arguments.first else picked

    sample = []
    shard = []
    for position in range(max(len(cases) for cases in drawn.values())):
        for cases in drawn.values():
            if position < len(cases):
                sample.append(cases[position])
                if position % arguments.shards == arguments.shard:
                    shard.append(cases[position])

    for path, cases in ((arguments.sample_out, sample), (arguments.shard_out, shard)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")
    print(f"{arguments.cases.name}: {len(sample)} sampled cases in {len(drawn)} categories, {len(shard)} in shard {arguments.shard} of {arguments.shards}")


if __name__ == "__main__":
    main()

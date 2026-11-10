"""Draws a fixed-seed sample of the typing test cases for the stock-keyboard measurement.

Key taps in the iOS Simulator are slow, so the measurement types a sample of the cases.

Usage, from the repository root:
    python3 scripts/typing-evaluation/engines/apple-stock-keyboard/sample_cases.py \
        --task english --cases scripts/typing-evaluation/cases/english.dev.jsonl --share 0.2 \
        --seed 20261109 --shard 0 --shards 2 --sample-out sample.jsonl --shard-out cases.jsonl

The script sorts the cases by id and draws with Python's `random.Random`, seeded with the seed,
the name of the case file and the name of the stratum. One seed and one case file give one sample.

English: a stratum is a category. The script draws `round(share * size)` cases from each
category, so each category keeps its share of its group. A shard holds every case whose position
inside its category, modulo `--shards`, equals `--shard`.

Pinyin: a base clause is a clean case with the slip cases that name it in `twin`. A stratum is
a length bin of the base clauses. The script draws `round(share * size)` base clauses from each
length bin and takes every case of each drawn base clause, so the scorer can pair each slip case
with its clean case. One simulator must not type one clause twice, because the keyboard learns
the text a person picks. So case number k of base clause number j goes to shard (j + k) modulo
`--shards`, and `--shards` must be at least the largest number of cases of one base clause.

`--limit N` gives a short trial run: the first N cases of each English shard, or the first N
base clauses of the Pinyin sample. 0 keeps all of them.
"""
import argparse
import json
import random
from pathlib import Path


def draw(cases: list, share: float, seed: str) -> list:
    count = round(share * len(cases))
    if count < 1:
        raise SystemExit(f"the share {share} of {len(cases)} cases gives an empty sample for {seed}")
    return random.Random(seed).sample(cases, count)


def english_shards(cases: list[dict], share: float, seed: str, shards: int, limit: int) -> list[list[dict]]:
    by_category: dict[str, list[dict]] = {}
    for case in cases:
        by_category.setdefault(case["category"], []).append(case)
    drawn = [draw(members, share, f"{seed}:{category}") for category, members in by_category.items()]
    result: list[list[dict]] = [[] for _ in range(shards)]
    # The cases go in turn from each category, so each shard mixes the categories.
    for position in range(max(len(members) for members in drawn)):
        for members in drawn:
            if position < len(members):
                result[position % shards].append(members[position])
    return [shard[:limit] for shard in result] if limit else result


def pinyin_shards(cases: list[dict], share: float, seed: str, shards: int, limit: int) -> list[list[dict]]:
    clauses: dict[str, list[dict]] = {}
    for case in cases:
        if case.get("twin") is None:
            if case["category"] != "clean":
                raise SystemExit(f"{case['id']}: a case without a twin must be a clean case")
            clauses.setdefault(case["id"], []).insert(0, case)
        else:
            clauses.setdefault(case["twin"], []).append(case)
    by_bin: dict[str, list[str]] = {}
    for base, members in clauses.items():
        if members[0]["id"] != base:
            raise SystemExit(f"{base}: a slip case names this clean case, and the clean case is missing")
        by_bin.setdefault(members[0]["length_bin"], []).append(base)
    drawn = [draw(bases, share, f"{seed}:{length_bin}") for length_bin, bases in sorted(by_bin.items())]
    result: list[list[dict]] = [[] for _ in range(shards)]
    number = 0
    for position in range(max(len(bases) for bases in drawn)):
        for bases in drawn:
            if position < len(bases) and (not limit or number < limit):
                members = clauses[bases[position]]
                if len(members) > shards:
                    raise SystemExit(f"{bases[position]} holds {len(members)} cases, more than the {shards} shards")
                for k, case in enumerate(members):
                    result[(number + k) % shards].append(case)
                number += 1
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["english", "pinyin"], required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--share", type=float, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shards", type=int, required=True)
    parser.add_argument("--sample-out", type=Path, required=True)
    parser.add_argument("--shard-out", type=Path, required=True)
    arguments = parser.parse_args()
    if not 0 <= arguments.shard < arguments.shards:
        raise SystemExit(f"--shard must lie in 0 to {arguments.shards - 1}")
    if not 0 < arguments.share <= 1:
        raise SystemExit("--share must lie above 0 and at most 1")

    cases = [json.loads(line) for line in arguments.cases.read_text(encoding="utf-8").splitlines() if line]
    cases.sort(key=lambda case: case["id"])
    seed = f"{arguments.seed}:{arguments.cases.name}"
    split = english_shards if arguments.task == "english" else pinyin_shards
    shards = split(cases, arguments.share, seed, arguments.shards, arguments.limit)
    sample = sorted((case for shard in shards for case in shard), key=lambda case: case["id"])
    shard = shards[arguments.shard]

    for path, rows in ((arguments.sample_out, sample), (arguments.shard_out, shard)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8", newline="\n")
    counts: dict[str, int] = {}
    for case in sample:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    print(f"{arguments.cases.name}: {len(sample)} sampled cases, {len(shard)} in shard {arguments.shard} of {arguments.shards}")
    print("  sampled cases per category: " + ", ".join(f"{name} {count}" for name, count in counts.items()))


if __name__ == "__main__":
    main()

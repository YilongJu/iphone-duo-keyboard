"""Paired comparison of two arms on the 6,799 generated dev cases: the cases one arm gets right
and the other gets wrong, and the exact two-sided McNemar (binomial) p value, as the fine-tune
design uses. A case is right when the output equals the intended text, ignoring case and outer
spaces, as rerank.summarize counts it.

The 95 percent interval of the difference in right cases resamples the groups of cases that
share a context and an intended text, 10,000 times, as summarize.py of the fine-tune does. Dev
holds 574 cases that repeat such a group, so the cases are not independent.

Usage: python scripts/lm-weight-edit/paired.py A_PREDICTIONS.jsonl B_PREDICTIONS.jsonl [...pairs]
Each file is a tuned.dev.jsonl of evaluate.py.
"""
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2].parent / "lm-finetune"
CASES = [ROOT / "scripts" / "typing-evaluation" / "cases" / name for name in ("english.dev.jsonl", "english-symbols.dev.jsonl")]


BOOTSTRAP_DRAWS = 10000


def read_cases() -> list[dict]:
    return [json.loads(line) for path in CASES for line in path.read_text(encoding="utf-8").splitlines()]


def intended() -> dict[str, str]:
    return {case["id"]: case["intended"].strip().lower() for case in read_cases()}


def bootstrap(cases: list[dict], first: set[str], second: set[str]) -> tuple[int, int, int]:
    """The 95 percent interval of (right by first) less (right by second), over draws of the
    groups of one context and one intended text. Returns the bounds and the group count."""
    groups: dict[tuple, int] = {}
    for case in cases:
        key = (case["context"], case["intended"].strip().lower())
        groups[key] = groups.get(key, 0) + int(case["id"] in first) - int(case["id"] in second)
    values = list(groups.values())
    rng = random.Random(20261110)
    draws = sorted(sum(rng.choices(values, k=len(values))) for _ in range(BOOTSTRAP_DRAWS))
    return draws[int(0.025 * BOOTSTRAP_DRAWS)], draws[int(0.975 * BOOTSTRAP_DRAWS) - 1], len(values)


def right_set(path: Path, truth: dict[str, str]) -> set[str]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if len(rows) != len(truth):
        raise SystemExit(f"{path}: {len(rows)} predictions, {len(truth)} dev cases")
    return {row["id"] for row in rows if row["output"].strip().lower() == truth[row["id"]]}


def binomial_two_sided(k: int, n: int) -> float:
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def main():
    cases = read_cases()
    truth = {case["id"]: case["intended"].strip().lower() for case in cases}
    paths = [Path(p) for p in sys.argv[1:]]
    if len(paths) % 2:
        raise SystemExit("give the files in pairs")
    for a, b in zip(paths[0::2], paths[1::2]):
        first, second = right_set(a, truth), right_set(b, truth)
        only_first, only_second = len(first - second), len(second - first)
        low, high, groups = bootstrap(cases, first, second)
        print(json.dumps({"a": a.parent.name, "b": b.parent.name, "a_right": len(first), "b_right": len(second),
                          "only_a": only_first, "only_b": only_second,
                          "p": round(binomial_two_sided(min(only_first, only_second), only_first + only_second), 4),
                          "difference": only_first - only_second, "interval_95": [low, high], "groups": groups}))


if __name__ == "__main__":
    main()

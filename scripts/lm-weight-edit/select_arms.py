"""Applies the selection rule of docs/lm-weight-edit-design.md to the stopping-split scores: within
each family, the arm with the most lists right wins, and a tie goes to the lower loss.

Usage: python scripts/lm-weight-edit/select_arms.py build/lm-weight-edit/stop/smollm2.jsonl [...]
"""
import json
import sys
from pathlib import Path


def family(arm: dict) -> str:
    kind = arm["kind"]
    prefix = arm["name"].split("-")[0]
    if kind in ("tv", "external"):
        return f"{prefix}-{kind}:{arm['tuned'][0]}"
    if kind in ("ta", "soup", "ties", "dare"):
        return f"{prefix}-{kind}:{'+'.join(arm['tuned'])}"
    return f"{prefix}-{kind}{'-shuffled' if arm.get('shuffle') else ''}"


def main():
    rows = []
    for path in sys.argv[1:]:
        rows += [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(family(row["arm"]), []).append(row)
    print(f"{'family':58} {'arms':>4} {'winner':32} {'right':>6} {'loss':>8}")
    for name, members in groups.items():
        best = sorted(members, key=lambda r: (-r["stop"]["right"], r["stop"]["loss"]))[0]
        print(f"{name:58} {len(members):>4} {best['arm']['name']:32} {best['stop']['right']:>6} {best['stop']['loss']:>8.4f}")


if __name__ == "__main__":
    main()

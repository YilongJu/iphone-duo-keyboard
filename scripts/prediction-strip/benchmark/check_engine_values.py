"""Check of the engine's word values that the mix M+E reads (`core.Engine.values`): the 20 words
with the highest value must be the 20 words of `duo_cli predict`, for the strip states of a
text half. Words of one value can stand in another order, so the check compares the values of
the two lists place by place.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/benchmark/check_engine_values.py \
        --cli build/prediction-strip/duo_cli --set mobile
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import core  # noqa: E402
from tables import Tables  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", required=True, type=Path)
    parser.add_argument("--set", required=True, dest="text_set")
    parser.add_argument("--name", default="shipped")
    parser.add_argument("--most", type=int, default=4000)
    args = parser.parse_args()
    states = core.states_of(args.text_set, "dev")
    tables = Tables(core.BENCH / "tables" / args.name)
    engine = core.Engine(args.cli, tables.words)
    requests = []
    for state in range(len(states.position)):
        if states.kind[state] == core.SHOWN:
            requests.append((states.previous[state], states.typed(state).lower()))
    requests = list(dict.fromkeys(requests))[:args.most]
    lists = engine.lists(requests)
    checked = other = 0
    for previous, typed in requests:
        listed = lists.get((previous, typed))
        if listed is None:
            continue
        values = engine.values(previous)
        low, high, left_out = tables.span(typed)
        part = values[low:high].astype(np.float64).copy()
        if left_out is not None:
            part[left_out - low] = -np.inf
        best = np.sort(part)[::-1][:len(listed)]
        got = np.array([values[tables.index[word]] for word in listed], dtype=np.float64)
        checked += 1
        if len(listed) != min(20, int(np.count_nonzero(np.isfinite(part)))) or not np.allclose(best, got, atol=1e-4):
            other += 1
            if other <= 3:
                print(f"other values for {previous!r} + {typed!r}: {listed[:6]} {got[:6]} against {best[:6]}")
    print(f"{checked} requests, {other} with other values than duo_cli predict")
    raise SystemExit(1 if other else 0)


if __name__ == "__main__":
    main()

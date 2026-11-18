"""Check of the benchmark's model orders against the engine's own function for the model's order
(`duo_predict_english_with_model` in Engine/duo_engine.c, by `duo_cli predict-model`).

The check takes strip states of one dev half: a word after a text and one space, with 0 to 3
typed letters. For each state the engine reads the same next-token block as the benchmark, the
word table of the keyboard (Shared/word-table-smollm2.bin) and one mix weight. The check then
compares two numbers for the written word:
  1. its place in the benchmark, by the form rules "typed_built" and "model_built" (places.py);
  2. its place in the engine's list of 64 words.
The benchmark holds the word shares as 32-bit floats, and the word table of the keyboard holds
them in steps of 1/1024. Two words whose values lie closer than that can change places.

The check also compares the lists of `duo_cli predict` of two builds of the engine, when
--other-cli names a second build.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/benchmark/check_engine_order.py \
        --cli build/prediction-strip/bench/duo_cli-504121c --set mobile [--other-cli build/prediction-strip/duo_cli]
"""
import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import blocks as block_store  # noqa: E402
import core  # noqa: E402
from places import Values, place_of  # noqa: E402
from tables import Tables  # noqa: E402

WORD_TABLE = core.ROOT / "Shared" / "word-table-smollm2.bin"
LISTED = 64
WEIGHTS = (0.0, 0.3)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", required=True, type=Path)
    parser.add_argument("--other-cli", type=Path)
    parser.add_argument("--set", required=True, dest="text_set")
    parser.add_argument("--name", default="shipped")
    parser.add_argument("--most", type=int, default=3000)
    args = parser.parse_args()
    states = core.states_of(args.text_set, "dev")
    tables = Tables(core.BENCH / "tables" / args.name)
    engine = core.Engine(args.cli, tables.words)
    contexts, of_position = states.contexts()
    stored = block_store.open_blocks(args.name, args.text_set, "dev", contexts)
    ranks = tables.frequency_rank

    chosen = [state for state in range(len(states.position))
              if states.kind[state] == core.SHOWN and states.typed_count[state] <= 3
              and not states.bare[states.position[state]] and not states.first_word[states.position[state]]
              and states.word[states.position[state]].lower() in tables.index]
    step = max(1, len(chosen) // args.most)
    chosen = chosen[::step][:args.most]

    if args.other_cli is not None:
        requests = list(dict.fromkeys((states.previous[state], states.typed(state).lower()) for state in chosen))
        first = engine.lists(requests)
        second = core.Engine(args.other_cli, tables.words).lists(requests)
        other = sum(1 for request in requests if first.get(request) != second.get(request))
        print(f"duo_cli predict of {args.cli.name} and of {args.other_cli.name}: {len(requests)} requests, {other} with other lists")

    block_of: dict[int, int] = {}
    next_file = core.BENCH / f"check_engine_order.{args.text_set}.next"
    with open(next_file, "wb") as out:
        for state in chosen:
            number = int(of_position[states.position[state]])
            if number not in block_of:
                block_of[number] = len(block_of)
                out.write(np.asarray(stored[number]).astype("<f4").tobytes())
    lines = "".join(
        f"{state}\t{states.previous[state]}\t{states.typed(state).lower()}\t{1 if states.typed(state)[:1].isupper() else 0}"
        f"\t{block_of[int(of_position[states.position[state]])]}\n" for state in chosen)

    for weight in WEIGHTS:
        run = subprocess.run(
            [str(args.cli), "predict-model", str(core.LEXICON), f"table={WORD_TABLE}", f"next={next_file}",
             f"supplement={core.SUPPLEMENT}", f"words={LISTED}", f"weight={weight}"],
            input=lines.encode("utf-8"), capture_output=True, check=False)
        if run.returncode != 0:
            raise SystemExit(f"duo_cli predict-model ended with {run.returncode}: {run.stderr.decode('utf-8', 'replace')[-2000:]}")
        listed = {}
        for line in run.stdout.decode("utf-8").splitlines():
            state, _, words = line.partition("\t")
            listed[int(state)] = [entry.rpartition("/")[0] for entry in words.split(" ")] if words else []
        if len(listed) != len(chosen):
            raise SystemExit(f"duo_cli answered {len(listed)} of {len(chosen)} requests")
        gaps: Counter = Counter()
        compared = 0
        first_three = [0, 0, 0]   # in the benchmark, in the engine, in one of the two only
        for state in chosen:
            position = states.position[state]
            word = states.word[position]
            target = tables.index[word.lower()]
            typed = states.typed(state)
            values = Values(tables, stored[of_position[position]], False)
            vector = values.best_capital if typed[:1].isupper() else values.best
            low, high, left_out = tables.span(typed.lower())
            part = vector[low:high]
            own = vector[target]
            if weight:
                mix = engine.values(states.previous[state])
                part = (1.0 - weight) * part + weight * mix[low:high]
                own = np.float32((1.0 - weight) * own + weight * mix[target])
            place = place_of(part, own, ranks[low:high], int(ranks[target]), None if left_out is None else left_out - low)
            names = listed[state]
            theirs = names.index(word.lower()) if word.lower() in names else LISTED
            if place >= LISTED and theirs >= LISTED:
                continue
            compared += 1
            gaps[min(abs(min(place, LISTED) - theirs), 3)] += 1
            first_three[0] += place < 3
            first_three[1] += theirs < 3
            first_three[2] += (place < 3) != (theirs < 3)
        print(f"weight {weight}: {compared} strip states with the word in the first {LISTED} places; "
              f"same place in {gaps[0]}, 1 place apart in {gaps[1]}, 2 places apart in {gaps[2]}, more in {gaps[3]}. "
              f"The word is among the first 3 in {first_three[0]} states of the benchmark and {first_three[1]} of the engine; "
              f"{first_three[2]} states differ.")
    next_file.unlink()


if __name__ == "__main__":
    main()

"""Check "Key press count" of the benchmark design: a list of every key press and tap of the
typist, counted one by one, against the numbers of simulate.py.

For one word order, one count of strip words and one typist, the script walks through every
sentence of a dev half key by key. It stops when its count for a sentence differs from the
count of simulate.py. It prints the list of the first sentences.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/benchmark/trace.py --set mobile \
        --order "shipped|typed|none|0.0" --words 3 --typist 1 --print 5
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import core  # noqa: E402
import rules  # noqa: E402
import simulate  # noqa: E402
from places import FORM_RULES, WEIGHTS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", required=True, dest="text_set")
    parser.add_argument("--half", default="dev")
    parser.add_argument("--order", required=True, help='"E", or a name as "shipped|typed|none|0.0"')
    parser.add_argument("--words", type=int, default=3)
    parser.add_argument("--typist", type=int, default=1)
    parser.add_argument("--print", type=int, default=5, dest="shown")
    args = parser.parse_args()
    rules.require_half(args.half)
    states = core.states_of(args.text_set, args.half)
    folder = core.BENCH / "places"
    engine = np.load(folder / f"engine.{args.text_set}.{args.half}.npy").astype(np.int64)
    if args.order == "E":
        places = np.where(states.kind == core.SHOWN, engine, core.NEVER)
    else:
        model, rule, first_word, weight = args.order.split("|")
        stored = np.load(folder / f"{model}.{args.text_set}.{args.half}.npy").astype(np.int64)
        places = simulate.assemble(states, engine, stored[FORM_RULES.index(rule), WEIGHTS.index(float(weight))], first_word)
    counted = simulate.saved_by_sentence(states, places, args.words, args.typist)

    position = 0
    total_without = total_with = 0
    for number, text in enumerate(states.sentences):
        lines = []
        presses = 0
        chunks = text.split(" ")
        for index, chunk in enumerate(chunks):
            last = index == len(chunks) - 1
            parts = rules.parse_chunk(chunk)
            if parts is None:
                presses += len(chunk)
                lines.append(f"    {len(chunk)} keys for {chunk!r}, no plain word")
            else:
                lead, word, trail = parts
                presses += len(lead)
                first = states.start_of_position[position]
                tapped = False
                typed_keys = 0
                for typed_count in range(len(word)):
                    state = first + typed_count
                    place = int(places[state])
                    saving = int(states.saving[state])
                    visible = place < args.words - int(states.emoji[state])
                    if visible and saving >= args.typist and states.tap_fits[position]:
                        presses += 1
                        tapped = True
                        lines.append(f"    {len(lead) + typed_keys} keys {lead + word[:typed_count]!r}, then 1 tap on {word!r} "
                                     f"at place {place + 1} after {int(states.emoji[state])} emoji, saves {saving}")
                        break
                    presses += 1
                    typed_keys += 1
                if not tapped:
                    lines.append(f"    {len(lead) + len(word)} keys for {lead + word!r}")
                presses += len(trail)
                if trail:
                    lines.append(f"    {len(trail)} keys for {trail!r}")
                if tapped and not trail:
                    if not last:
                        lines.append("    the space comes with the tap")
                    position += 1
                    continue
                position += 1
            if not last:
                presses += 1
                lines.append("    1 key for the space")
        without = len(text)
        if without - presses != int(counted[number]):
            raise SystemExit(f"sentence {number} {text!r}: the list saves {without - presses} key presses, "
                             f"and simulate.py counts {int(counted[number])}")
        total_without += without
        total_with += presses
        if number < args.shown:
            print(f"{text!r}: {without} key presses without the strip, {presses} with it")
            print("\n".join(lines))
    if position != len(states.word):
        raise SystemExit("the walk did not reach every plain word")
    print(f"{args.text_set}.{args.half}, {args.order}, {args.words} strip words, typist {args.typist}: "
          f"{total_without} key presses without the strip, {total_with} with it, saved {100 * (1 - total_with / total_without):.2f} of 100. "
          f"Every one of the {len(states.sentences)} sentences agrees with simulate.py.")


if __name__ == "__main__":
    main()

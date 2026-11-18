"""The word order M+R of the benchmark of the predicted words: the model's order, and one more
request at each strip state (docs/prediction-strip-benchmark-design.md, "Word orders").

At a strip state with 0 to 3 typed letters, the request gives the 8 first words of the model's
order their full value: the log probability of every token of the shown form, plus the log
probability that the next token starts with a space, so the word ends there. The 8 words then
stand in the order of these values, and the words after them keep their places.

`lm_score` puts one space between a text and a form, and no space after an empty text. So a
strip state right after an opening bracket or quote, where no space comes before the form,
gets no request and keeps the model's order. A strip state with 4 or more typed letters keeps
the model's order too.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/benchmark/rescore.py --lm LM_SCORE \
        --model MODEL.gguf --name shipped --set technical --half dev --rule typed --first-word none
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import blocks as block_store  # noqa: E402
import core  # noqa: E402
import rules  # noqa: E402
from places import FORM_RULES, MINUS, Values, all_capitals, candidates_of, place_of  # noqa: E402
from tables import Tables  # noqa: E402

FIRST = 8
MOST_TYPED_LETTERS = 3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--set", required=True, dest="text_set")
    parser.add_argument("--half", required=True)
    parser.add_argument("--rule", required=True, choices=FORM_RULES)
    parser.add_argument("--first-word", required=True, choices=("none", "engine", "model"))
    parser.add_argument("--cli", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    rules.require_half(args.half)
    states = core.states_of(args.text_set, args.half)
    tables = Tables(core.BENCH / "tables" / args.name)
    engine = core.Engine(args.cli, tables.words)
    contexts, of_position = states.contexts()
    stored = block_store.open_blocks(args.name, args.text_set, args.half, contexts)
    ranks = tables.frequency_rank
    out = core.BENCH / "places"
    places = np.full(len(states.position), core.NEVER, dtype=np.int16)
    requests = [0]
    seconds: list[float] = []
    lock = threading.Lock()
    started = time.monotonic()

    rule_number = FORM_RULES.index(args.rule)

    def shown_text(number: int, values: Values, typed: str, field_start: bool, automatic: bool) -> str:
        """The text that the strip shows for a word of the tables, by the form rule of this run."""
        name = tables.words[number]
        if args.rule.endswith("_built") and not field_start and all_capitals(typed):
            return name.upper()
        if args.rule.startswith("typed"):
            if field_start:
                letter = name[0].upper()
                return engine.capitals.form(rules.predicted_word(name, letter), letter, True)
            return engine.capitals.form(rules.predicted_word(name, typed), typed, automatic)
        forms = values.best_capital_form if typed[:1].isupper() else values.best_form
        return tables.forms[number][forms[number]]

    def work(scorer: block_store.Scorer, positions: list[int]) -> None:
        for position in positions:
            word = states.word[position]
            target = tables.index.get(word.lower())
            if target is None:
                continue
            first = states.start_of_position[position]
            values = None
            for state in range(first, first + len(word)):
                kind = states.kind[state]
                if kind == core.NO_STRIP:
                    continue
                field_start = kind == core.FIELD_START
                automatic = bool(states.automatic[state])
                # A strip state where the rule for the first word shows the engine's order, or
                # nothing, needs no request. simulate.py takes the engine's place there.
                if states.first_word[position] and args.first_word != "model":
                    continue
                if values is None:
                    values = Values(tables, stored[of_position[position]], states.bare[position])
                typed = word[:states.typed_count[state]]
                low, high, left_out = tables.span(typed.lower())
                if not low <= target < high or target == left_out:
                    continue
                for form_rules, vector, own in candidates_of(tables, engine, values, word, target, typed, field_start, automatic):
                    if rule_number not in form_rules or own == MINUS:
                        continue
                    part = vector[low:high]
                    place = place_of(part, own, ranks[low:high], int(ranks[target]), None if left_out is None else left_out - low)
                    context = states.context[position]
                    asks = (states.typed_count[state] <= MOST_TYPED_LETTERS and place < FIRST
                            and not (states.bare[position] and context != ""))
                    if asks:
                        order = np.lexsort((ranks[low:high], -part.astype(np.float64)))
                        numbers = [low + int(index) for index in order[:FIRST + 1] if left_out is None or low + int(index) != left_out]
                        numbers = [number for number in numbers[:FIRST] if vector[number] > MINUS]
                        texts = [shown_text(number, values, typed, field_start, automatic) for number in numbers]
                        at = numbers.index(target)
                        if texts[at] != word:
                            raise SystemExit(f"the strip shows {texts[at]!r} for the written word {word!r} after {typed!r}")
                        began = time.monotonic()
                        exact = scorer.exact(context, texts)
                        full = [log_probability + space_after for log_probability, space_after in exact]
                        place = sum(1 for index, value in enumerate(full) if value > full[at] or (value == full[at] and index < at))
                        with lock:
                            requests[0] += 1
                            seconds.append(time.monotonic() - began)
                    places[state] = min(place, core.NEVER)
            with lock:
                if position % 2000 == 0:
                    print(f"  position {position} of {len(states.word)}, {requests[0]} requests, {time.monotonic() - started:.0f} s", flush=True)

    scorers = [block_store.Scorer(args.lm, args.model, args.threads, out / f"rescore-{args.name}-{args.text_set}-{index}.lm_score.log")
               for index in range(args.workers)]
    order = list(range(len(states.word)))
    threads = [threading.Thread(target=work, args=(scorer, order[index::args.workers])) for index, scorer in enumerate(scorers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for scorer in scorers:
        scorer.close()
    np.save(out / f"{args.name}.{args.text_set}.{args.half}.rescored.{args.rule}-{args.first_word}.npy", places)
    facts = {"requests": requests[0], "request_ms_median": float(np.median(seconds) * 1000) if seconds else None,
             "request_ms_mean": float(np.mean(seconds) * 1000) if seconds else None, "wall_seconds": time.monotonic() - started,
             "positions": len(states.word), "workers": args.workers, "threads": args.threads}
    (out / f"{args.name}.{args.text_set}.{args.half}.rescored.{args.rule}-{args.first_word}.json").write_text(
        json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    print(f"{args.name} {args.text_set}.{args.half} rescored: {json.dumps(facts)}", flush=True)


if __name__ == "__main__":
    main()

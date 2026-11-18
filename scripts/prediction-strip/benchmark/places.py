"""The place of the written word in the strip, at every strip state of a text half, for the
engine's order and for the model orders of one model file
(docs/prediction-strip-benchmark-design.md, "Word orders").

A model order gives each word a value: the log probability of the first token of its form, plus
the log of the word share. With a mix weight w, the value is (1 - w) times that value plus w
times the engine's log value of the word.

Form rules of the design:
  typed  the typed capitals give the form, as in build 62. The value of a word is the value of
         that form. A word in capitals that is none of the three forms, as "NASA", takes the
         highest value of the word's forms that start with a capital.
  model  the form with the highest value among the allowed forms. A first typed letter in
         capitals allows only the forms that start with a capital.

Form rules as the keyboard of commit 504121c computes them (`modelPredictedWords` in
Shared/KeyboardTextController.swift). Both give a word the highest value of its allowed forms,
as `duo_predict_english_with_model` does, and both write every word in capitals after 2 or
more typed capitals:
  typed_built  the typed capitals give the form, as in build 62.
  model_built  the form with the highest value among the allowed forms.
The keyboard of that commit has no model order at the start of a field. At that strip state
the two rules take the places of "typed" and "model".

A word is found when the strip shows it in its written form. Its place is the count of words
of the strip before it: words with a higher value, and words of the same value that the
lexicon holds as more frequent. The file holds the value NEVER for a word that is not shown.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/benchmark/places.py --name shipped \
        --set technical --half dev --cli build/prediction-strip/duo_cli
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import blocks as block_store  # noqa: E402
import core  # noqa: E402
import rules  # noqa: E402
from tables import Tables  # noqa: E402

WEIGHTS = (0.0, 0.1, 0.2, 0.3, 0.5)
FORM_RULES = ("typed", "model", "typed_built", "model_built")
MINUS = np.float32(-np.inf)


class Values:
    """The values of every word at one position, for the form rules."""

    def __init__(self, tables: Tables, block: np.ndarray, bare: bool):
        scores = np.append(block.astype(np.float32), MINUS)
        place = "bare" if bare else "spaced"
        self.all = scores[tables.first[place]] + tables.share[place]
        capital = np.where(tables.capital, self.all, MINUS)
        self.best = self.all.max(axis=1)
        self.best_form = self.all.argmax(axis=1)
        self.best_capital = capital.max(axis=1)
        self.best_capital_form = capital.argmax(axis=1)
        rows = tables.rows
        # The forms of build 62 for typed letters in lower case, with a first capital, and in capitals.
        self.lower = self.all[:, 0]
        self.capital = self.all[rows, tables.capital_form]
        self.capitals = np.where(tables.preferred_form >= 0, self.all[rows, np.maximum(tables.preferred_form, 0)], self.best_capital)


def typed_class(typed: str, field_start: bool) -> str:
    """Which form build 62 shows for the typed letters: "lower", "capital" or "capitals"."""
    if field_start:
        return "capital"
    if all_capitals(typed):
        return "capitals"
    return "capital" if typed[:1].isupper() else "lower"


def all_capitals(typed: str) -> bool:
    """True for 2 or more typed letters that are all capitals."""
    letters = [character for character in typed if character.isalpha()]
    return len(letters) >= 2 and all(character.isupper() for character in letters)


def place_of(values: np.ndarray, own: np.float32, ranks: np.ndarray, own_rank: int, left_out: int | None) -> int:
    """How many words come before a word of the value `own`: a higher value, or the same value
    and an earlier place in the frequency order. `values` holds the words of the span."""
    before = int(np.count_nonzero(values > own))
    before += int(np.count_nonzero((values == own) & (ranks < own_rank)))
    if left_out is not None and (values[left_out] > own or (values[left_out] == own and ranks[left_out] < own_rank)):
        before -= 1
    return before


def candidates_of(tables: Tables, engine: core.Engine, values: Values, word: str, target: int, typed: str,
                  field_start: bool, automatic: bool) -> list[tuple[tuple[int, ...], np.ndarray, np.float32]]:
    """For one strip state: the groups of form rules that share one order of the words. Each
    group holds the numbers of its form rules that show the written word, the values of all
    words, and the value of the written word."""
    # The form rule "typed".
    group = typed_class(typed, field_start)
    if field_start:
        letter = word[0].upper()
        shown = engine.capitals.form(rules.predicted_word(word.lower(), letter), letter, True)
    else:
        shown = engine.capitals.form(rules.predicted_word(word.lower(), typed), typed, automatic)
    typed_vector = {"lower": values.lower, "capital": values.capital, "capitals": values.capitals}[group]
    if shown in tables.forms[target]:
        typed_own = values.all[target, tables.forms[target].index(shown)]
    else:
        typed_own = values.best_capital[target]
    # The form rule "model".
    if typed[:1].isupper():
        best_vector, form = values.best_capital, values.best_capital_form[target]
    else:
        best_vector, form = values.best, values.best_form[target]
    model_shown = tables.forms[target][form]
    if field_start:
        # No model order of the keyboard exists here, so the built rules follow the design rules.
        return [((0, 2) if shown == word else (), typed_vector, typed_own),
                ((1, 3) if model_shown == word else (), best_vector, best_vector[target])]
    capitals = all_capitals(typed)
    built = tuple(rule for rule, text in ((1, model_shown), (2, word.upper() if capitals else shown),
                                          (3, word.upper() if capitals else model_shown)) if text == word)
    return [((0,) if shown == word else (), typed_vector, typed_own), (built, best_vector, best_vector[target])]


def measure(tables: Tables, states: core.States, engine: core.Engine, stored: np.ndarray, of_position: np.ndarray,
            log=print) -> np.ndarray:
    """Places with the shape (form rules, weights, strip states)."""
    places = np.full((len(FORM_RULES), len(WEIGHTS), len(states.position)), core.NEVER, dtype=np.int16)
    ranks = tables.frequency_rank
    started = time.monotonic()
    for position in range(len(states.word)):
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
            if values is None:
                values = Values(tables, stored[of_position[position]], states.bare[position])
            typed = word[:states.typed_count[state]]
            low, high, left_out = tables.span(typed.lower())
            if not low <= target < high or target == left_out:
                continue
            mix = None
            for form_rules, vector, own in candidates_of(tables, engine, values, word, target, typed,
                                                         kind == core.FIELD_START, bool(states.automatic[state])):
                if not form_rules or own == MINUS:
                    continue
                part = vector[low:high]
                for index, weight in enumerate(WEIGHTS):
                    if weight == 0.0:
                        mixed, mixed_own = part, own
                    else:
                        if mix is None:
                            mix = engine.values(states.previous[state])
                        mixed = (1.0 - weight) * part + weight * mix[low:high]
                        mixed_own = np.float32((1.0 - weight) * own + weight * mix[target])
                    place = place_of(mixed, mixed_own, ranks[low:high], int(ranks[target]),
                                     None if left_out is None else left_out - low)
                    for rule in form_rules:
                        places[rule, index, state] = min(place, core.NEVER)
        if position % 2000 == 0:
            log(f"  position {position} of {len(states.word)}, {time.monotonic() - started:.0f} s")
    return places


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="the name of the model file in the benchmark")
    parser.add_argument("--set", required=True, dest="text_set")
    parser.add_argument("--half", required=True)
    parser.add_argument("--cli", required=True, type=Path)
    args = parser.parse_args()
    rules.require_half(args.half)
    states = core.states_of(args.text_set, args.half)
    tables = Tables(core.BENCH / "tables" / args.name)
    engine = core.Engine(args.cli, tables.words)
    out = core.BENCH / "places"
    out.mkdir(parents=True, exist_ok=True)
    engine_file = out / f"engine.{args.text_set}.{args.half}.npy"
    if not engine_file.exists():
        np.save(engine_file, core.engine_places(states, engine).astype(np.int16))
    contexts, of_position = states.contexts()
    stored = block_store.open_blocks(args.name, args.text_set, args.half, contexts)
    places = measure(tables, states, engine, stored, of_position,
                     log=lambda text: print(f"{args.name} {args.text_set}.{args.half}{text}", flush=True))
    np.save(out / f"{args.name}.{args.text_set}.{args.half}.npy", places)
    print(f"{args.name} {args.text_set}.{args.half}: {len(states.word)} positions, {len(states.position)} strip states", flush=True)


if __name__ == "__main__":
    main()

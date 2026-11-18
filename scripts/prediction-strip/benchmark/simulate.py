"""The typist of the benchmark of the predicted words: saved key presses and found share for
every word order, with intervals (docs/prediction-strip-benchmark-design.md, "Typist and key
presses" and "Decision rule").

The script reads the places that places.py and rescore.py wrote, and writes the numbers of one
half into scripts/prediction-strip/benchmark/results/HALF.json. The bootstrap samples go into
build/prediction-strip/bench/results/HALF.npz.

A word order has this name: the model file, the form rule, the rule for the first word of a
field, and the mix weight, as "shipped|typed|none|0.0". "E" is the engine's order. A name that
ends in "|R" is the order with one more request at each strip state.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/benchmark/simulate.py --half dev \
        --models shipped base135
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import core  # noqa: E402
import rules  # noqa: E402
from places import FORM_RULES, WEIGHTS  # noqa: E402

STRIP_WORDS = (3, 4, 5, 6, 7, 10)   # the closed phone shows 3 to 5 words, the open phone 4 to 7, and 10 is the design's count for the split layout
TYPISTS = (1, 2)           # the fewest key presses that a tap must save
FIRST_WORD_RULES = ("none", "engine", "model")
TYPED_LETTERS = (0, 1, 2, 3)
SAMPLES = 1000
RESULTS = Path(__file__).with_name("results")
SAMPLES_FOLDER = core.BENCH / "results"   # the bootstrap samples, outside the repository


def assemble(states: core.States, engine: np.ndarray, model: np.ndarray, first_word: str) -> np.ndarray:
    """The places of a model order: the model's places, and for the first word of a field the
    places that the rule `first_word` gives."""
    places = np.where(states.kind == core.SHOWN, model, core.NEVER)
    of_first = states.first_word[states.position]
    start = states.kind == core.FIELD_START
    if first_word == "none":
        places = np.where(of_first & (states.kind == core.SHOWN), engine, places)
    elif first_word == "engine":
        places = np.where(of_first & (states.kind != core.NO_STRIP), engine, places)
    else:
        places = np.where(start, model, places)
    return places


def saved_by_sentence(states: core.States, places: np.ndarray, strip_words: int, least_saving: int) -> np.ndarray:
    """The key presses that the taps save in each sentence. The typist taps at the first strip
    state of a word whose first entries hold the word, when the tap saves enough key presses
    and the tap gives the written text."""
    seen = places < (strip_words - states.emoji)
    taps = seen & (states.saving >= least_saving) & states.tap_fits[states.position]
    # The saving falls with each typed letter, so the first tap of a word saves the most.
    saved = np.maximum.reduceat(np.where(taps, states.saving, 0), states.start_of_position)
    return np.bincount(states.sentence, weights=saved, minlength=len(states.base))


def found_share(states: core.States, places: np.ndarray, strip_words: int) -> list[tuple[int, int]]:
    """For each count of typed letters: the strip states whose first entries hold the word, and
    all strip states of plain words with that count."""
    seen = places < (strip_words - states.emoji)
    return [(int(np.count_nonzero(seen & (states.typed_count == count))), int(np.count_nonzero(states.typed_count == count)))
            for count in TYPED_LETTERS]


def interval(samples: np.ndarray) -> list[float]:
    return [round(float(np.percentile(samples, 2.5)), 6), round(float(np.percentile(samples, 97.5)), 6)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--half", required=True)
    parser.add_argument("--models", nargs="+", required=True)
    args = parser.parse_args()
    rules.require_half(args.half)
    folder = core.BENCH / "places"
    names: list[str] = []
    saved: dict[str, dict[str, np.ndarray]] = {}       # set -> order -> (strip words, typists, sentences)
    found: dict[str, dict[str, list]] = {}
    base: dict[str, np.ndarray] = {}
    counts: dict[str, dict] = {}
    for text_set in core.SETS:
        states = core.states_of(text_set, args.half)
        base[text_set] = states.base.astype(np.float64)
        engine = np.load(folder / f"engine.{text_set}.{args.half}.npy").astype(np.int64)
        orders = {"E": np.where(states.kind == core.SHOWN, engine, core.NEVER)}
        for model in args.models:
            model_places = np.load(folder / f"{model}.{text_set}.{args.half}.npy").astype(np.int64)
            for rule_index, rule in enumerate(FORM_RULES):
                for first_word in FIRST_WORD_RULES:
                    for weight_index, weight in enumerate(WEIGHTS):
                        name = f"{model}|{rule}|{first_word}|{weight}"
                        orders[name] = assemble(states, engine, model_places[rule_index, weight_index], first_word)
            for path in sorted(folder.glob(f"{model}.{text_set}.{args.half}.rescored.*.npy")):
                rule, first_word = path.name.split(".")[-2].split("-")
                rescored = np.load(path).astype(np.int64)
                orders[f"{model}|{rule}|{first_word}|0.0|R"] = assemble(states, engine, rescored, first_word)
        if args.half == "test":
            # Rule 5 of the decision rule: the test halves get the chosen word order and E only.
            chosen = json.loads(rules.CHOSEN.read_text(encoding="utf-8"))["order"]
            if chosen not in orders:
                raise SystemExit(f"{rules.CHOSEN} names the word order {chosen!r}, and the places of the test halves do not hold it")
            orders = {name: orders[name] for name in ("E", chosen)}
        if names and names != list(orders):
            raise SystemExit(f"{text_set} has other word orders than the set before")
        names = list(orders)
        saved[text_set] = {name: np.array([[saved_by_sentence(states, places, words, least) for least in TYPISTS]
                                           for words in STRIP_WORDS]) for name, places in orders.items()}
        found[text_set] = {name: [found_share(states, places, words) for words in STRIP_WORDS] for name, places in orders.items()}
        counts[text_set] = {"sentences": len(states.base), "chunks": sum(len(text.split(" ")) for text in states.sentences),
                            "plain_words": len(states.word), "strip_states": len(states.position),
                            "key_presses": int(states.base.sum()),
                            "plain_words_where_a_tap_fits": int(states.tap_fits.sum()),
                            "states_with_words": int(np.count_nonzero(states.kind == core.SHOWN)),
                            "field_starts": int(np.count_nonzero(states.kind == core.FIELD_START))}

    # Bootstrap: the same sample of sentences for every word order, one sample stream per set.
    samples = np.zeros((len(core.SETS), len(names), len(STRIP_WORDS), len(TYPISTS), SAMPLES))
    values = np.zeros((len(core.SETS), len(names), len(STRIP_WORDS), len(TYPISTS)))
    for set_index, text_set in enumerate(core.SETS):
        size = len(base[text_set])
        generator = np.random.default_rng(20261118 + set_index)
        drawn = generator.integers(0, size, size=(SAMPLES, size))
        weights = np.zeros((SAMPLES, size))
        np.add.at(weights, (np.arange(SAMPLES)[:, None], drawn), 1.0)
        total = weights @ base[text_set]
        for name_index, name in enumerate(names):
            table = saved[text_set][name]
            values[set_index, name_index] = table.sum(axis=2) / base[text_set].sum()
            samples[set_index, name_index] = (table @ weights.T) / total
    mean_values = values.mean(axis=0)
    mean_samples = samples.mean(axis=0)

    result = {"half": args.half, "samples": SAMPLES, "strip_words": STRIP_WORDS, "typists": TYPISTS, "counts": counts, "orders": {}}
    for name_index, name in enumerate(names):
        entry = {"saved": {}, "found": {}}
        for words_index, words in enumerate(STRIP_WORDS):
            for typist_index, least in enumerate(TYPISTS):
                key = f"{words}/{least}"
                entry["saved"][key] = {
                    "mean": [round(float(mean_values[name_index, words_index, typist_index]), 6),
                             *interval(mean_samples[name_index, words_index, typist_index])]}
                for set_index, text_set in enumerate(core.SETS):
                    entry["saved"][key][text_set] = [round(float(values[set_index, name_index, words_index, typist_index]), 6),
                                                     *interval(samples[set_index, name_index, words_index, typist_index])]
            entry["found"][str(words)] = {text_set: found[text_set][name][words_index] for text_set in core.SETS}
        result["orders"][name] = entry
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{args.half}.json").write_text(json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    SAMPLES_FOLDER.mkdir(exist_ok=True)
    np.savez_compressed(SAMPLES_FOLDER / f"{args.half}.npz",names=np.array(names), values=values, samples=samples.astype(np.float32))
    eager = {name: mean_values[index, 0, 0] for index, name in enumerate(names)}
    for name in sorted(eager, key=eager.get, reverse=True)[:12] + ["E"]:
        print(f"{100 * eager[name]:6.2f}  {name}")


if __name__ == "__main__":
    main()

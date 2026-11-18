"""The word tables of the benchmark of the predicted words, for one model file.

The candidates are the words of Shared/lexicon-english.bin with the words of
Shared/supplement-ai-software.bin laid over them (build_tables.py of the folder above reads
them). A word has up to three forms: lower case, first letter capital, and the preferred
capitals of the work area. The word "i" and its contractions have no lower-case form.

A form can stand at two kinds of place:
  spaced  after a text and one space. The model reads the form with that space.
  bare    with no space before it: at the start of the field, and right after an opening
          bracket or quote.
For each kind of place the table holds the first token of every form and its word share: the
word's probability over the summed probability of the forms of its pool with the same first
token. A kind of place has two pools: the forms that start with a capital, and the others.

The table also holds the form that the keyboard of build 62 shows for typed capitals
(`KeyboardTextController.predictedWords`): the form for a first typed letter in capitals, and
the preferred form for two or more typed letters in capitals, when the work area gives one.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/benchmark/tables.py --lm LM_SCORE \
        --model MODEL.gguf --name shipped
"""
import argparse
import bisect
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import build_tables as first  # noqa: E402
import rules  # noqa: E402
from rerank import language_model_text  # noqa: E402

MAX_FORMS = 3
PLACES = ("spaced", "bare")


def build(lm: str, model: str, out: Path) -> None:
    main_words = first.read_lexicon(first.LEXICON)
    extra_words = first.read_lexicon(first.SUPPLEMENT)
    capitals = rules.PreferredCapitals(first.CAPITALS_TABLE)
    log_probability = dict(main_words)
    for word, value in extra_words.items():
        log_probability[word] = max(value, log_probability.get(word, value))
    words = sorted(log_probability)
    forms = []
    for word in words:
        entry = capitals.entries.get(word)
        listed = [language_model_text(word, False), word[0].upper() + word[1:]] + ([entry[0]] if entry else [])
        forms.append(first.unique_in_order(listed))
    count = len(words)
    probability = np.exp(np.array([log_probability[word] for word in words], dtype=np.float64))
    arrays = {}
    vocabulary = None
    for place in PLACES:
        tokens, size = first.tokenize(lm, model, [form for listed in forms for form in listed], place == "spaced")
        if vocabulary not in (None, size):
            raise SystemExit("the vocabulary changed between two runs")
        vocabulary = size
        first_token = np.full((count, MAX_FORMS), vocabulary, dtype=np.int32)
        length = np.zeros((count, MAX_FORMS), dtype=np.int16)
        pool = np.full((count, MAX_FORMS), -1, dtype=np.int8)
        for index, listed in enumerate(forms):
            for at, form in enumerate(listed):
                first_token[index, at] = tokens[form][0]
                length[index, at] = len(tokens[form])
                pool[index, at] = 1 if form[0].isupper() else 0
        share = np.zeros((count, MAX_FORMS), dtype=np.float32)
        for number in (0, 1):
            rows, places = np.nonzero(pool == number)
            totals = np.bincount(first_token[rows, places], weights=probability[rows], minlength=vocabulary + 1)
            share[rows, places] = np.log(probability[rows] / totals[first_token[rows, places]])
        arrays[f"{place}_first"] = first_token
        arrays[f"{place}_length"] = length
        arrays[f"{place}_share"] = share
    capital = np.zeros((count, MAX_FORMS), dtype=bool)
    capital_form = np.zeros(count, dtype=np.int8)
    preferred_form = np.full(count, -1, dtype=np.int8)
    for index, (word, listed) in enumerate(zip(words, forms)):
        for at, form in enumerate(listed):
            capital[index, at] = form[0].isupper()
        letter = word[0].upper()
        # The form of build 62 for typed letters that start with a capital.
        shown = capitals.form(rules.predicted_word(word, letter), letter, False)
        if shown not in listed:
            raise SystemExit(f"{word!r} shows {shown!r} for a capital, which is none of its forms {listed}")
        capital_form[index] = listed.index(shown)
        # The form for two or more typed letters in capitals: the preferred form, or the word in capitals.
        typed = word[:2].upper()
        shown = capitals.form(rules.predicted_word(word, typed), typed, False) if len(word) > 2 else word.upper()
        if shown in listed:
            preferred_form[index] = listed.index(shown)
        elif shown != word.upper():
            raise SystemExit(f"{word!r} shows {shown!r} for capitals, which is no form and not the word in capitals")
    order = sorted(range(count), key=lambda index: (-log_probability[words[index]], words[index]))
    frequency_rank = np.empty(count, dtype=np.int32)
    frequency_rank[order] = np.arange(count, dtype=np.int32)
    out.mkdir(parents=True, exist_ok=True)
    np.savez(out / "tables.npz", vocabulary=np.int32(vocabulary), capital=capital, capital_form=capital_form,
             preferred_form=preferred_form, frequency_rank=frequency_rank,
             log_probability=np.array([log_probability[word] for word in words], dtype=np.float32), **arrays)
    (out / "forms.json").write_text(json.dumps({"words": words, "forms": forms}, ensure_ascii=False), encoding="utf-8")
    facts = {"candidate_words": count, "vocabulary": int(vocabulary), "forms": int(sum(len(listed) for listed in forms)),
             "one_token_spaced_forms": int(np.count_nonzero(arrays["spaced_length"] == 1)),
             "one_token_bare_forms": int(np.count_nonzero(arrays["bare_length"] == 1))}
    (out / "facts.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(facts))


class Tables:
    def __init__(self, folder: Path):
        arrays = np.load(folder / "tables.npz")
        data = json.loads((folder / "forms.json").read_text(encoding="utf-8"))
        self.words: list[str] = data["words"]
        self.forms: list[list[str]] = data["forms"]
        self.index = {word: number for number, word in enumerate(self.words)}
        self.vocabulary = int(arrays["vocabulary"])
        self.frequency_rank = arrays["frequency_rank"]
        self.log_probability = arrays["log_probability"]
        self.capital = arrays["capital"]
        self.capital_form = arrays["capital_form"].astype(np.int64)
        self.preferred_form = arrays["preferred_form"].astype(np.int64)
        self.first = {place: arrays[f"{place}_first"] for place in PLACES}
        self.share = {place: arrays[f"{place}_share"] for place in PLACES}
        self.length = {place: arrays[f"{place}_length"] for place in PLACES}
        self.rows = np.arange(len(self.words))
        if self.words != sorted(self.words):
            raise SystemExit("the words of the tables are not sorted")

    def span(self, typed: str) -> tuple[int, int, int | None]:
        """The words that start with the lower-case letters `typed`, as a range of word numbers,
        and the number of the word that equals `typed`, which the strip leaves out."""
        if not typed:
            return 0, len(self.words), None
        low = bisect.bisect_left(self.words, typed)
        high = bisect.bisect_left(self.words, typed + "\U0010FFFF")
        return low, high, (low if low < high and self.words[low] == typed else None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--name", required=True, help="the name of the model file in the benchmark, as shipped")
    args = parser.parse_args()
    build(args.lm, args.model, rules.BENCH / "tables" / args.name)


if __name__ == "__main__":
    main()

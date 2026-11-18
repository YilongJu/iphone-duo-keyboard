"""Builds the word tables of the predicted-word measurement (scripts/prediction-strip/README.md).

The candidates are the words of Shared/lexicon-english.bin with the words of
Shared/supplement-ai-software.bin laid over them, as the keyboard does with the work area on:
a word of both files gets the higher of its two log probabilities (`exact_word` in
Engine/duo_engine.c).

A word has up to three forms that the language model can read: lower case, first letter
capital, and the preferred capitals of the work area (Shared/supplement-ai-software.tsv). Each
form goes through `language_model_text` of scripts/lm-rerank/rerank.py, so "i'm" is "I'm".
- Spaced forms follow a text, so the model reads them after one space.
- Start forms open the field. The keyboard types their first letter as a capital, and no space
  comes before them.

`lm_score MODEL THREADS tokens` gives the tokens of every form, with the repair of token -1.
For each form the table holds its first token, its count of tokens and its unigram share: the
word's probability over the summed probability of the forms of the same pool that have the
same first token. The pools are the spaced forms that start with a capital, the other spaced
forms, and the start forms.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/build_tables.py \
        --lm ~/predstrip/bin/lm_score --model MODEL.gguf --out build/prediction-strip/tables
"""
import argparse
import json
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
from rerank import language_model_text  # noqa: E402

LEXICON = ROOT / "Shared" / "lexicon-english.bin"
SUPPLEMENT = ROOT / "Shared" / "supplement-ai-software.bin"
CAPITALS_TABLE = ROOT / "Shared" / "supplement-ai-software.tsv"
MAGIC = 0x4C4F5544
# lm_score reads at most 64 candidates in one request line.
CANDIDATES_PER_LINE = 64
MAX_FORMS = 3


def read_lexicon(path: Path) -> dict[str, float]:
    """The words of a lexicon file of version 2 with their natural-log probabilities
    (scripts/typing-engine/lexicon_format.py)."""
    data = path.read_bytes()
    magic, version, nodes, words, string_bytes, pairs, model, _ = struct.unpack_from("<8I", data, 0)
    if magic != MAGIC or version != 2 or model != 0:
        raise SystemExit(f"{path} is not an English lexicon of version 2")
    word_table = 32 + nodes * 12
    strings = len(data) - string_bytes
    if word_table + words * 12 + (words + 1) * 4 + pairs * 8 != strings:
        raise SystemExit(f"{path}: the parts of the file do not add up to its size")
    result: dict[str, float] = {}
    for index in range(words):
        offset, log_probability, _ = struct.unpack_from("<Iff", data, word_table + index * 12)
        end = data.index(b"\0", strings + offset)
        text = data[strings + offset:end].decode("utf-8")
        if text in result:
            raise SystemExit(f"{path} holds the word {text!r} twice")
        result[text] = log_probability
    return result


def read_preferred(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines[0].split("\t") != ["word", "zipf", "preferred", "everyday", "new"]:
        raise SystemExit(f"{path} does not have the columns word, zipf, preferred, everyday, new")
    result = {}
    for line in lines[1:]:
        word, _, preferred, _, _ = line.split("\t")
        if preferred:
            result[word] = preferred
    return result


def tokenize(lm: str, model: str, texts: list[str], after_space: bool) -> tuple[dict[str, list[int]], int]:
    """The tokens of each text as lm_score reads a candidate: after one space when a context
    comes before it, and without a space when it opens the field. Also returns the size of the
    vocabulary."""
    unique = sorted(set(texts))
    for text in unique:
        if not text or "\t" in text or "\n" in text:
            raise SystemExit(f"a form is empty or holds a tab or a line break: {text!r}")
    chunks = [unique[start:start + CANDIDATES_PER_LINE] for start in range(0, len(unique), CANDIDATES_PER_LINE)]
    requests = "".join(("x" if after_space else "") + "\t" + "\t".join(chunk) + "\n" for chunk in chunks)
    run = subprocess.run([lm, model, "1", "tokens"], input=requests.encode("utf-8"), capture_output=True, check=False)
    if run.returncode != 0:
        raise SystemExit(f"lm_score tokens ended with {run.returncode}: {run.stderr.decode('utf-8', 'replace')[-2000:]}")
    lines = run.stdout.decode("utf-8").splitlines()
    if not lines or not lines[0].startswith("ready vocabulary="):
        raise SystemExit(f"lm_score did not start: {lines[:1]}")
    vocabulary = int(lines[0].split()[1].split("=")[1])
    if len(lines) - 1 != len(chunks):
        raise SystemExit(f"lm_score gave {len(lines) - 1} token lines for {len(chunks)} requests")
    tokens: dict[str, list[int]] = {}
    for chunk, line in zip(chunks, lines[1:]):
        fields = line.split("\t")
        if len(fields) != len(chunk) + 1:
            raise SystemExit(f"a token line has {len(fields) - 1} candidates for {len(chunk)}")
        for text, field in zip(chunk, fields[1:]):
            tokens[text] = [int(value) for value in field.split(" ")]
    return tokens, vocabulary


def unique_in_order(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm", required=True, help="the lm_score program")
    parser.add_argument("--model", required=True, help="the model file, for its vocabulary")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    main_words = read_lexicon(LEXICON)
    extra_words = read_lexicon(SUPPLEMENT)
    preferred = read_preferred(CAPITALS_TABLE)
    log_probability = dict(main_words)
    for word, value in extra_words.items():
        log_probability[word] = max(value, log_probability.get(word, value))
    words = sorted(log_probability)
    odd = [word for word in words if not word.isascii() or word != word.lower() or not word.replace("'", "").isalpha()]
    if odd:
        raise SystemExit(f"{len(odd)} words are not lower-case ASCII letters with apostrophes, as {odd[:5]}")

    spaced_forms, start_forms = [], []
    for word in words:
        forms = [word, word[0].upper() + word[1:]] + ([preferred[word]] if word in preferred else [])
        spaced = unique_in_order([language_model_text(form, False) for form in forms])
        spaced_forms.append(spaced)
        start_forms.append(unique_in_order([language_model_text(form, True) for form in spaced]))

    spaced_tokens, vocabulary = tokenize(args.lm, args.model, [f for forms in spaced_forms for f in forms], True)
    start_tokens, start_vocabulary = tokenize(args.lm, args.model, [f for forms in start_forms for f in forms], False)
    if vocabulary != start_vocabulary:
        raise SystemExit("the vocabulary changed between two runs")

    count = len(words)
    logp = np.array([log_probability[word] for word in words], dtype=np.float64)
    probability = np.exp(logp)

    def table(all_forms: list[list[str]], tokens: dict[str, list[int]], pools):
        """`pools(form)` names the pool of a form. Returns the first tokens (the vocabulary size
        where a word has no such form), the counts of tokens, the log shares and the capital flags."""
        first = np.full((count, MAX_FORMS), vocabulary, dtype=np.int32)
        length = np.zeros((count, MAX_FORMS), dtype=np.int16)
        capital = np.zeros((count, MAX_FORMS), dtype=bool)
        pool_of = np.full((count, MAX_FORMS), -1, dtype=np.int8)
        for index, forms in enumerate(all_forms):
            if len(forms) > MAX_FORMS:
                raise SystemExit(f"{words[index]!r} has more than {MAX_FORMS} forms")
            for place, form in enumerate(forms):
                first[index, place] = tokens[form][0]
                length[index, place] = len(tokens[form])
                capital[index, place] = form[0].isupper()
                pool_of[index, place] = pools(form)
        share = np.zeros((count, MAX_FORMS), dtype=np.float32)
        for pool in sorted(set(pool_of[pool_of >= 0].tolist())):
            rows, places = np.nonzero(pool_of == pool)
            totals = np.bincount(first[rows, places], weights=probability[rows], minlength=vocabulary + 1)
            share[rows, places] = np.log(probability[rows] / totals[first[rows, places]])
        return first, length, share, capital

    spaced = table(spaced_forms, spaced_tokens, lambda form: 1 if form[0].isupper() else 0)
    start = table(start_forms, start_tokens, lambda form: 0)

    order = sorted(range(count), key=lambda index: (-logp[index], words[index]))
    frequency_rank = np.empty(count, dtype=np.int32)
    frequency_rank[order] = np.arange(count, dtype=np.int32)

    # The bar opens the typed span in the prompt format that the shipped model was trained on
    # ("How much | sutar |"). measure.py writes how much of the probability the model gives it.
    bar_after_space = tokenize(args.lm, args.model, ["|"], True)[0]["|"]
    bar_at_start = tokenize(args.lm, args.model, ["|"], False)[0]["|"]
    if len(bar_after_space) != 1 or len(bar_at_start) != 1:
        raise SystemExit(f"the bar is not one token: {bar_after_space} {bar_at_start}")

    args.out.mkdir(parents=True, exist_ok=True)
    np.savez(
        args.out / "tables.npz", log_probability=logp.astype(np.float32), frequency_rank=frequency_rank,
        vocabulary=np.int32(vocabulary), bar_after_space=np.int32(bar_after_space[0]), bar_at_start=np.int32(bar_at_start[0]),
        spaced_first=spaced[0], spaced_length=spaced[1], spaced_share=spaced[2], spaced_capital=spaced[3],
        start_first=start[0], start_length=start[1], start_share=start[2])
    (args.out / "forms.json").write_text(
        json.dumps({"words": words, "spaced": spaced_forms, "start": start_forms}, ensure_ascii=False), encoding="utf-8")

    def one_token(forms_of_word, tokens, pick) -> int:
        return sum(1 for forms in forms_of_word if (form := pick(forms)) is not None and len(tokens[form]) == 1)

    lower = lambda forms: next((f for f in forms if not f[0].isupper()), None)  # noqa: E731
    capital = lambda forms: next((f for f in forms if f[0].isupper()), None)  # noqa: E731
    facts = {
        "lexicon_words": len(main_words), "supplement_words": len(extra_words),
        "supplement_words_outside_the_lexicon": sum(1 for word in extra_words if word not in main_words),
        "candidate_words": count, "words_with_preferred_capitals": len(preferred),
        "vocabulary": vocabulary,
        "spaced_forms": sum(len(forms) for forms in spaced_forms), "start_forms": sum(len(forms) for forms in start_forms),
        "words_with_a_lower_case_form": sum(1 for forms in spaced_forms if lower(forms) is not None),
        "one_token_lower_case_form_after_a_space": one_token(spaced_forms, spaced_tokens, lower),
        "one_token_capital_form_after_a_space": one_token(spaced_forms, spaced_tokens, capital),
        "one_token_start_form": one_token(start_forms, start_tokens, lambda forms: forms[0]),
        "most_tokens_of_a_form": int(max(spaced[1].max(), start[1].max())),
    }
    (args.out / "facts.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(facts, indent=2))


if __name__ == "__main__":
    main()

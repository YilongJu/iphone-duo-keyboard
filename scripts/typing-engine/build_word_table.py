"""Builds Shared/word-table-smollm2.bin: the word table that the engine reads to order the
predicted words with the numbers of the language model (duo_predict_english_with_model in
Engine/duo_engine.c).

For each word of Shared/lexicon-english.bin and of Shared/supplement-ai-software.bin, and for
each form of the word, the table holds two values:
- the first token that the model reads for the form after a space, and
- the word share: the word's probability over the summed probability of the forms of the same
  pool that start with the same token.

The forms of a word are the lower-case word, the word with a capital first letter, and for a
word of the supplement its preferred capitals (Shared/supplement-ai-software.tsv). Each form
goes through `language_model_text` of scripts/lm-rerank/rerank.py, so "i'm" is "I'm". A form
that equals an earlier form of its word is left out. There are two pools: the forms that start
with a capital, and the other forms. A word of both files counts once in a pool, at the higher
of its two probabilities, as the engine reads it (`exact_word`).

`lm_score MODEL THREADS tokens` (scripts/lm-rerank/lm_score.c) gives the tokens, with the same
tokenizer and the same repair of token -1 as the keyboard's scorer. The table belongs to one
vocabulary: every SmolLM2-135M file has the same one.

File format, all numbers little-endian:
    header   8 x uint32: magic "DUOW", version 1, count of tokens of the vocabulary, count of
             words of the lexicon, count of words of the supplement, 2, 3, and the FNV-1a hash
             of every word text with its ending zero, the lexicon first
    lexicon forms     2 per word, in the order of the lexicon's word table: lower case, capital
    supplement forms  3 per word, in the order of the supplement's word table: lower case,
                      capital, preferred capitals
    form     4 bytes: the first token (uint16, 0xFFFF for a form that is left out), then a
             uint16 with bit 15 set for a form that starts with a capital, and in bits 0 to 14
             the negated natural log of the word share in steps of 1/1024, at most 32767

Usage, in WSL or on Linux, from the repository root:
    python3 scripts/typing-engine/build_word_table.py --lm LM_SCORE --model MODEL.gguf [--check]

With --check the script writes no file. It builds the table in memory and stops with an error
when the bytes differ from Shared/word-table-smollm2.bin.
"""
import argparse
import math
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
from rerank import language_model_text  # noqa: E402

LEXICON = ROOT / "Shared" / "lexicon-english.bin"
SUPPLEMENT = ROOT / "Shared" / "supplement-ai-software.bin"
CAPITALS_TABLE = ROOT / "Shared" / "supplement-ai-software.tsv"
OUTPUT = ROOT / "Shared" / "word-table-smollm2.bin"
LEXICON_MAGIC = 0x4C4F5544
TABLE_MAGIC = 0x574F5544
TABLE_VERSION = 1
NO_FORM_TOKEN = 0xFFFF
FORM_IS_CAPITAL = 0x8000
SHARE_STEPS = 1024
# lm_score reads at most 64 candidates in one request line.
CANDIDATES_PER_LINE = 64


def read_lexicon(path: Path) -> list[tuple[str, float]]:
    """The words of a lexicon file of version 2 in the order of its word table, each with its
    natural-log probability (scripts/typing-engine/lexicon_format.py)."""
    data = path.read_bytes()
    magic, version, nodes, words, string_bytes, pairs, model, _ = struct.unpack_from("<8I", data, 0)
    if magic != LEXICON_MAGIC or version != 2 or model != 0:
        raise SystemExit(f"{path} is not an English lexicon of version 2")
    word_table = 32 + nodes * 12
    strings = len(data) - string_bytes
    if word_table + words * 12 + (words + 1) * 4 + pairs * 8 != strings:
        raise SystemExit(f"{path}: the parts of the file do not add up to its size")
    result = []
    for index in range(words):
        offset, log_probability, _ = struct.unpack_from("<Iff", data, word_table + index * 12)
        end = data.index(b"\0", strings + offset)
        result.append((data[strings + offset:end].decode("utf-8"), log_probability))
    if len({text for text, _ in result}) != len(result):
        raise SystemExit(f"{path} holds a word twice")
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


def first_tokens(lm: str, model: str, texts: list[str]) -> tuple[dict[str, int], int]:
    """The first token of each text as the scorer reads it after a context and one space, and
    the count of tokens of the vocabulary."""
    unique = sorted(set(texts))
    for text in unique:
        if not text or "\t" in text or "\n" in text:
            raise SystemExit(f"a form is empty or holds a tab or a line break: {text!r}")
    chunks = [unique[start:start + CANDIDATES_PER_LINE] for start in range(0, len(unique), CANDIDATES_PER_LINE)]
    # A context of one letter stands for any text before the word: the form then follows a space.
    requests = "".join("x\t" + "\t".join(chunk) + "\n" for chunk in chunks)
    run = subprocess.run([lm, model, "1", "tokens"], input=requests.encode("utf-8"), capture_output=True, check=False)
    if run.returncode != 0:
        raise SystemExit(f"lm_score tokens ended with {run.returncode}: {run.stderr.decode('utf-8', 'replace')[-2000:]}")
    lines = run.stdout.decode("utf-8").splitlines()
    if not lines or not lines[0].startswith("ready vocabulary="):
        raise SystemExit(f"lm_score did not start: {lines[:1]}")
    vocabulary = int(lines[0].split()[1].split("=")[1])
    if len(lines) - 1 != len(chunks):
        raise SystemExit(f"lm_score gave {len(lines) - 1} token lines for {len(chunks)} requests")
    tokens: dict[str, int] = {}
    for chunk, line in zip(chunks, lines[1:]):
        fields = line.split("\t")
        if len(fields) != len(chunk) + 1:
            raise SystemExit(f"a token line has {len(fields) - 1} candidates for {len(chunk)}")
        for text, field in zip(chunk, fields[1:]):
            tokens[text] = int(field.split(" ")[0])
    return tokens, vocabulary


def forms_of(word: str, preferred: str | None, slots: int) -> list[str | None]:
    """The forms of a word in the slots lower case, capital and preferred capitals. A form that
    equals an earlier form of the word is None."""
    wanted = [word, word[0].upper() + word[1:], preferred][:slots]
    result: list[str | None] = []
    for form in wanted:
        text = language_model_text(form, False) if form else None
        result.append(None if text is None or text in result else text)
    return result


def fnv1a(words: list[str]) -> int:
    value = 2166136261
    for word in words:
        for byte in word.encode("utf-8") + b"\0":
            value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value


def build(lm: str, model: str) -> tuple[bytes, dict]:
    main = read_lexicon(LEXICON)
    extra = read_lexicon(SUPPLEMENT)
    preferred = read_preferred(CAPITALS_TABLE)
    odd = [word for word, _ in main + extra
           if not word.isascii() or word != word.lower() or not word.replace("'", "").isalpha()]
    if odd:
        raise SystemExit(f"{len(odd)} words are not lower-case ASCII letters with apostrophes, as {odd[:5]}")
    # A word of both files counts once, at the higher of its two log probabilities.
    log_probability = dict(main)
    for word, value in extra:
        log_probability[word] = max(value, log_probability.get(word, value))

    main_forms = [forms_of(word, None, 2) for word, _ in main]
    extra_forms = [forms_of(word, preferred.get(word), 3) for word, _ in extra]
    every_form = {form: word for (word, _), forms in list(zip(main, main_forms)) + list(zip(extra, extra_forms))
                  for form in forms if form is not None}
    tokens, vocabulary = first_tokens(lm, model, list(every_form))
    if vocabulary >= NO_FORM_TOKEN:
        raise SystemExit(f"the vocabulary of {vocabulary} tokens does not fit 16 bits")

    # The summed probability of the forms of each pool with each first token. A form of a word
    # of both files is in both lists above, and counts once.
    totals: dict[tuple[bool, int], float] = {}
    for form, word in every_form.items():
        key = (form[0].isupper(), tokens[form])
        totals[key] = totals.get(key, 0.0) + math.exp(log_probability[word])

    def record(word: str, form: str | None) -> bytes:
        if form is None:
            return struct.pack("<HH", NO_FORM_TOKEN, 0)
        capital = form[0].isupper()
        share = log_probability[word] - math.log(totals[(capital, tokens[form])])
        if share > 1e-6:
            raise SystemExit(f"the word share of {form!r} is above 1")
        steps = min(32767, round(max(-share, 0.0) * SHARE_STEPS))
        return struct.pack("<HH", tokens[form], steps | (FORM_IS_CAPITAL if capital else 0))

    body = b"".join(record(word, form) for (word, _), forms in zip(main, main_forms) for form in forms)
    body += b"".join(record(word, form) for (word, _), forms in zip(extra, extra_forms) for form in forms)
    header = struct.pack(
        "<8I", TABLE_MAGIC, TABLE_VERSION, vocabulary, len(main), len(extra), 2, 3,
        fnv1a([word for word, _ in main] + [word for word, _ in extra]))
    facts = {
        "lexicon words": len(main), "supplement words": len(extra), "tokens of the vocabulary": vocabulary,
        "forms": len(every_form), "forms with a capital": sum(1 for form in every_form if form[0].isupper()),
        "bytes": len(header) + len(body),
    }
    return header + body, facts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm", required=True, help="the lm_score program")
    parser.add_argument("--model", required=True, help="a model file with the vocabulary of the shipped model")
    parser.add_argument("--check", action="store_true", help="compare with the file in Shared and write nothing")
    arguments = parser.parse_args()
    table, facts = build(arguments.lm, arguments.model)
    for name, value in facts.items():
        print(f"{name}: {value}")
    if arguments.check:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != table:
            raise SystemExit(f"{OUTPUT.relative_to(ROOT)} is not the table of this lexicon and this model")
        print(f"{OUTPUT.relative_to(ROOT)} is the table of this lexicon and this model")
        return
    OUTPUT.write_bytes(table)
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

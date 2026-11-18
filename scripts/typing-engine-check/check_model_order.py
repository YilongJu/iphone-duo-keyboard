"""Checks duo_predict_english_with_model (Engine/duo_engine.c) against a second computation in
Python, on next-token blocks of the real model.

The check reads Shared/lexicon-english.bin, Shared/supplement-ai-software.bin and
Shared/word-table-smollm2.bin by itself. For each strip state it computes the value of every
word that starts with the typed letters, by the rule in Engine/duo_engine.h:
    model value of a form  = next[first token] - share steps / 1024
    model value of a word  = the highest model value of its allowed forms
    value                  = (1 - weight) * model value + weight * engine value
It then compares the list of `duo_cli predict-model`, which runs with the compiler's memory
checks, with these values:
1. The list holds as many words as the rule allows, up to 20.
2. The values of the listed words do not rise from one place to the next.
3. No word outside the list has a higher value than the last listed word.
4. Each listed word names the form with the highest model value.
Two words of one value can stand in either order, so the check compares values and not places.

The strip states come from the first sentences of the dev half of english-domain-stream: the
text before each of the first words, with 0, 1 and 2 typed letters, with and without the rule
for a typed capital, and with the engine weights 0 and 0.3.

Usage, in WSL, from the repository root, after `build_word_table.py`:
    uv run --with numpy python scripts/typing-engine-check/check_model_order.py \\
        --lm LM_SCORE --model MODEL.gguf --cli DUO_CLI [--sentences 12] [--tables FOLDER]
With --tables, the check also compares the word shares of the word table with the tables of
scripts/prediction-strip/build_tables.py in FOLDER.
"""
import argparse
import bisect
import json
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases" / "english-domain-stream.dev.jsonl"
LEXICON = ROOT / "Shared" / "lexicon-english.bin"
SUPPLEMENT = ROOT / "Shared" / "supplement-ai-software.bin"
TABLE = ROOT / "Shared" / "word-table-smollm2.bin"
PAIR_WEIGHT = 0.6  # duo_english_params in Engine/duo_engine.c
NO_FORM_TOKEN = 0xFFFF
TOLERANCE = 1e-4


class Lexicon:
    def __init__(self, path: Path):
        data = path.read_bytes()
        _, version, nodes, words, string_bytes, pairs, model, _ = struct.unpack_from("<8I", data, 0)
        assert version == 2 and model == 0, path
        word_table = 32 + nodes * 12
        strings = len(data) - string_bytes
        records = np.frombuffer(data, dtype=np.dtype([("offset", "<u4"), ("logp", "<f4"), ("backoff", "<f4")]),
                                count=words, offset=word_table)
        self.own = records["logp"].astype(np.float32)
        self.words = []
        for offset in records["offset"]:
            end = data.index(b"\0", strings + int(offset))
            self.words.append(data[strings + int(offset):end].decode("utf-8"))
        self.index = {word: number for number, word in enumerate(self.words)}
        pair_index = word_table + words * 12
        self.pair_start = np.frombuffer(data, dtype="<u4", count=words + 1, offset=pair_index)
        self.pairs = np.frombuffer(data, dtype=np.dtype([("second", "<u4"), ("logp", "<f4")]), count=pairs,
                                   offset=pair_index + (words + 1) * 4)
        self.pair_count = pairs


def read_table(path: Path, main_words: int, extra_words: int):
    data = path.read_bytes()
    magic, version, vocabulary, main, extra, main_forms, extra_forms, _ = struct.unpack_from("<8I", data, 0)
    assert magic == 0x574F5544 and version == 1 and (main, extra, main_forms, extra_forms) == (main_words, extra_words, 2, 3)
    forms = np.frombuffer(data, dtype="<u2", offset=32).reshape(-1, 2)
    return vocabulary, forms[:main * 2].reshape(main, 2, 2), forms[main * 2:].reshape(extra, 3, 2)


def model_value(forms: np.ndarray, block: np.ndarray, capital_only: bool):
    """The highest model value of the allowed forms of one word, and that form, or None."""
    best = None
    for number, (token, packed) in enumerate(forms):
        if token == NO_FORM_TOKEN or (capital_only and not packed & 0x8000):
            continue
        value = np.float32(block[token]) - np.float32(packed & 0x7FFF) / np.float32(1024)
        if best is None or value > best[0]:
            best = (value, number)
    return best


def reference(main: Lexicon, extra: Lexicon, table, sorted_words, block, previous: str, typed: str,
              capital_only: bool, weight: float) -> dict[str, tuple[float, int]]:
    """The value and the form of every word that starts with the typed letters and is longer."""
    _, main_forms, extra_forms = table
    previous_main = main.index.get(previous)
    after_a_word = previous != "" and (previous_main is not None or previous in extra.index)
    base = np.float32(math.log(1 - PAIR_WEIGHT)) if after_a_word else np.float32(0)
    listed = {}
    if previous_main is not None:
        for pair in range(int(main.pair_start[previous_main]), int(main.pair_start[previous_main + 1])):
            listed[int(main.pairs["second"][pair])] = float(main.pairs["logp"][pair])
    weight32 = np.float32(weight)
    result: dict[str, tuple[float, int]] = {}
    start = bisect.bisect_left(sorted_words, typed)
    for word in sorted_words[start:]:
        if not word.startswith(typed):
            break
        if len(word) <= len(typed) or (typed == "" and not ("a" <= word[0] <= "z")):
            continue
        candidates = []
        if word in main.index:
            number = main.index[word]
            own = float(main.own[number])
            engine = own + float(base)
            if number in listed:
                engine = math.log(PAIR_WEIGHT * math.exp(listed[number]) + (1 - PAIR_WEIGHT) * math.exp(own))
            candidates.append((main_forms[number], engine))
        if word in extra.index:
            number = extra.index[word]
            candidates.append((extra_forms[number], float(extra.own[number]) + float(base)))
        for forms, engine in candidates:
            best = model_value(forms, block, capital_only)
            if best is None:
                continue
            value = float((np.float32(1) - weight32) * best[0] + weight32 * np.float32(engine))
            if word not in result or value > result[word][0]:
                result[word] = (value, best[1])
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--cli", required=True, help="duo_cli, built with -fsanitize=address,undefined")
    parser.add_argument("--sentences", type=int, default=12)
    parser.add_argument("--tables", type=Path)
    arguments = parser.parse_args()

    main_lexicon, extra_lexicon = Lexicon(LEXICON), Lexicon(SUPPLEMENT)
    table = read_table(TABLE, len(main_lexicon.words), len(extra_lexicon.words))
    vocabulary = table[0]
    sorted_words = sorted(set(main_lexicon.words) | set(extra_lexicon.words))

    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    contexts, states = [], []
    for case in cases[:arguments.sentences]:
        words = case["intended"].split(" ")
        for count in range(1, min(len(words), 6)):
            target = words[count].lower()
            if not target.replace("'", "").isalpha() or not target.isascii():
                continue
            context = " ".join(words[:count])
            previous = words[count - 1].lower()
            previous = previous if previous.replace("'", "").isalpha() and previous.isascii() else ""
            block = len(contexts)
            contexts.append(context)
            for typed_count in range(0, min(3, len(target))):
                for capital_only in (False, True):
                    for weight in (0.0, 0.3):
                        states.append((block, previous, target[:typed_count], capital_only, weight))
    text = "".join(context + "\n" for context in contexts)
    run = subprocess.run([arguments.lm, arguments.model, "2", "next"], input=text.encode("utf-8"), capture_output=True)
    if run.returncode != 0:
        sys.exit(f"lm_score ended with {run.returncode}: {run.stderr.decode('utf-8', 'replace')[-600:]}")
    ready, _, blocks = run.stdout.partition(b"\n")
    assert ready.startswith(b"ready "), ready[:60]
    assert len(blocks) == len(contexts) * vocabulary * 4, (len(blocks), len(contexts))
    numbers = np.frombuffer(blocks, dtype="<f4").reshape(len(contexts), vocabulary)

    failures = 0
    with tempfile.TemporaryDirectory() as folder:
        next_file = Path(folder) / "next.bin"
        next_file.write_bytes(blocks)
        for weight in (0.0, 0.3):
            mine = [state for state in states if state[4] == weight]
            lines = "".join(f"{number}\t{previous}\t{typed}\t{int(capital)}\t{block}\n"
                            for number, (block, previous, typed, capital, _) in enumerate(mine))
            cli = subprocess.run(
                [arguments.cli, "predict-model", str(LEXICON), f"supplement={SUPPLEMENT}", f"table={TABLE}",
                 f"next={next_file}", f"weight={weight}"], input=lines, capture_output=True, text=True)
            if cli.returncode != 0:
                sys.exit(f"duo_cli ended with {cli.returncode}: {cli.stderr[-800:]}")
            answers = cli.stdout.splitlines()
            assert len(answers) == len(mine), (len(answers), len(mine))
            for (block, previous, typed, capital, _), answer in zip(mine, answers):
                listed = [entry.rsplit("/", 1) for entry in answer.split("\t", 1)[1].split(" ") if entry]
                values = reference(main_lexicon, extra_lexicon, table, sorted_words, numbers[block], previous, typed,
                                   capital, weight)
                problems = []
                if len(listed) != min(20, len(values)):
                    problems.append(f"{len(listed)} words for {len(values)} candidates")
                unknown = [word for word, _ in listed if word not in values]
                if unknown:
                    problems.append(f"words outside the rule: {unknown[:3]}")
                else:
                    shown = [values[word][0] for word, _ in listed]
                    if any(later > earlier + TOLERANCE for earlier, later in zip(shown, shown[1:])):
                        problems.append("the values rise inside the list")
                    names = {word for word, _ in listed}
                    if shown and len(values) > len(listed):
                        best_outside = max(value for word, (value, _) in values.items() if word not in names)
                        if best_outside > shown[-1] + TOLERANCE:
                            problems.append(f"a word outside the list has the value {best_outside:.4f} above {shown[-1]:.4f}")
                    wrong_form = [word for word, form in listed if int(form) != values[word][1]]
                    if wrong_form:
                        problems.append(f"other forms for {wrong_form[:3]}")
                if problems:
                    failures += 1
                    if failures <= 5:
                        print(f"PROBLEM context {contexts[block]!r} typed {typed!r} capital {capital} weight {weight}: {problems}")
    print(f"{len(states)} strip states on {len(contexts)} next-token blocks, {failures} with a problem")

    if arguments.tables:
        arrays = np.load(arguments.tables / "tables.npz")
        forms = json.loads((arguments.tables / "forms.json").read_text(encoding="utf-8"))
        position = {word: number for number, word in enumerate(forms["words"])}
        widest, compared, other_tokens = 0.0, 0, 0
        for number, word in enumerate(main_lexicon.words):
            row = position[word]
            for form in forms["spaced"][row]:
                place = forms["spaced"][row].index(form)
                slot = 1 if form[0].isupper() and form != word else 0
                if form[0].isupper() and len(forms["spaced"][row]) == 1:
                    slot = 0
                token, packed = table[1][number][slot]
                if token == NO_FORM_TOKEN:
                    continue
                compared += 1
                other_tokens += int(token != arrays["spaced_first"][row, place])
                widest = max(widest, abs(-(packed & 0x7FFF) / 1024 - float(arrays["spaced_share"][row, place])))
        print(f"word shares against {arguments.tables}: {compared} forms, {other_tokens} with another token, "
              f"widest difference {widest:.5f}")
        if other_tokens or widest > 1 / 1024:
            failures += 1
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()

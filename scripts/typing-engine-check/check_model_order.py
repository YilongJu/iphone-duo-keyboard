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


def model_values(forms: np.ndarray, block: np.ndarray, capital_only: bool):
    """For every word of one file: the highest model value of its allowed forms and that form.
    A word without an allowed form has the value -inf."""
    tokens = forms[:, :, 0].astype(np.int64)
    packed = forms[:, :, 1]
    allowed = tokens != NO_FORM_TOKEN
    if capital_only:
        allowed &= (packed & 0x8000) != 0
    numbers = block[np.where(allowed, tokens, 0)].astype(np.float32)
    values = numbers - (packed & 0x7FFF).astype(np.float32) / np.float32(1024)
    values = np.where(allowed, values, np.float32(-np.inf))
    # argmax gives the first form of the highest value, as the engine keeps the earlier form.
    best = np.argmax(values, axis=1)
    return values[np.arange(len(forms)), best], best


def reference(main: Lexicon, extra: Lexicon, table, starts: dict, block, previous: str, typed: str,
              capital_only: bool, weight: float) -> dict[str, tuple[float, int]]:
    """The value and the form of every word that starts with the typed letters and is longer."""
    _, main_forms, extra_forms = table
    previous_main = main.index.get(previous)
    after_a_word = previous != "" and (previous_main is not None or previous in extra.index)
    base = np.float32(math.log(1 - PAIR_WEIGHT)) if after_a_word else np.float32(0)
    weight32 = np.float32(weight)
    result: dict[str, tuple[float, int]] = {}
    for lexicon, forms, is_main in ((main, main_forms, True), (extra, extra_forms, False)):
        engine = (lexicon.own + base).astype(np.float32)
        if is_main and previous_main is not None:
            first, last = int(main.pair_start[previous_main]), int(main.pair_start[previous_main + 1])
            second = main.pairs["second"][first:last]
            listed = main.pairs["logp"][first:last].astype(np.float64)
            own = main.own[second].astype(np.float64)
            engine[second] = np.log(PAIR_WEIGHT * np.exp(listed) + (1 - PAIR_WEIGHT) * np.exp(own)).astype(np.float32)
        model, best = model_values(forms, block, capital_only)
        mixed = (np.float32(1) - weight32) * model + weight32 * engine
        for number in starts[(is_main, typed)]:
            if not np.isfinite(mixed[number]):
                continue
            word, value = lexicon.words[number], float(mixed[number])
            if word not in result or value > result[word][0]:
                result[word] = (value, int(best[number]))
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
    # The numbers of the words of each file that start with given typed letters and are longer.
    starts: dict = {}

    def words_with_start(typed: str) -> None:
        for is_main, lexicon in ((True, main_lexicon), (False, extra_lexicon)):
            if (is_main, typed) not in starts:
                starts[(is_main, typed)] = [
                    number for number, word in enumerate(lexicon.words)
                    if word.startswith(typed) and len(word) > len(typed) and (typed != "" or "a" <= word[0] <= "z")]

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
                words_with_start(target[:typed_count])
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
                values = reference(main_lexicon, extra_lexicon, table, starts, numbers[block], previous, typed,
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
    print(f"{len(states)} strip states on {len(contexts)} next-token blocks, {failures} with a problem", flush=True)

    if arguments.tables:
        arrays = np.load(arguments.tables / "tables.npz")
        # One read of each array: an access through the archive reads the whole array again.
        spaced_first, spaced_share = arrays["spaced_first"], arrays["spaced_share"]
        forms = json.loads((arguments.tables / "forms.json").read_text(encoding="utf-8"))
        position = {word: number for number, word in enumerate(forms["words"])}

        def shown(text: str) -> str:
            """`language_model_text` of scripts/lm-rerank/rerank.py for one word."""
            return "I" + text[1:] if text == "i" or text.startswith("i'") else text

        widest, compared, other_tokens, missing = 0.0, 0, 0, 0
        for lexicon, entries in ((main_lexicon, table[1]), (extra_lexicon, table[2])):
            for number, word in enumerate(lexicon.words):
                row = position[word]
                texts = [shown(word), shown(word[0].upper() + word[1:])]
                for slot in range(entries.shape[1]):
                    token, packed = int(entries[number][slot][0]), int(entries[number][slot][1])
                    if token == NO_FORM_TOKEN:
                        continue
                    # The third slot is the preferred form: the form of the measurement that is
                    # neither of the first two.
                    if slot < 2:
                        wanted = [place for place, form in enumerate(forms["spaced"][row]) if form == texts[slot]]
                    else:
                        wanted = [place for place, form in enumerate(forms["spaced"][row]) if form not in texts]
                    if len(wanted) != 1:
                        missing += 1
                        continue
                    compared += 1
                    other_tokens += int(token != int(spaced_first[row, wanted[0]]))
                    share = -(packed & 0x7FFF) / 1024
                    widest = max(widest, abs(share - max(float(spaced_share[row, wanted[0]]), -32767 / 1024)))
        print(f"word table against {arguments.tables}: {compared} forms, {missing} without a form of the measurement, "
              f"{other_tokens} with another token, widest difference of a word share {widest:.5f}")
        if missing or other_tokens or widest > 1 / 1024:
            failures += 1
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()

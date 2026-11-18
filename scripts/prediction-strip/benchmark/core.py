"""The strip states of a text half, and the engine's word order and word values, for the
benchmark of the predicted words (docs/prediction-strip-benchmark-design.md).

A position is one plain word of a sentence. A strip state is a position with a count of typed
letters, from 0 to the length of the word less 1.
"""
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import rules  # noqa: E402

ROOT = rules.ROOT
BENCH = rules.BENCH
LEXICON = ROOT / "Shared" / "lexicon-english.bin"
SUPPLEMENT = ROOT / "Shared" / "supplement-ai-software.bin"
CAPITALS_TABLE = ROOT / "Shared" / "supplement-ai-software.tsv"
SETS = ("technical", "everyday", "mobile")
ENGINE_WORDS = 20
ENGINE_TYPED = re.compile(r"[a-z']{0,32}")
PAIR_WEIGHT = 0.6  # duo_english_params in Engine/duo_engine.c
NEVER = 30000  # the place of a word that the strip does not show

# Kinds of strip state.
SHOWN = 0        # the keyboard shows predicted words (KeyboardTextLogic.predictionContext)
FIELD_START = 1  # no text before the cursor: the setting "first word of a field" decides
NO_STRIP = 2     # the keyboard shows no predicted words


def read_texts(name: str, half: str) -> list[dict]:
    rules.require_half(half)
    path = BENCH / "texts" / f"{name}.{half}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class States:
    """The positions and the strip states of a list of sentences."""

    def __init__(self, sentences: list[str]):
        emoji = rules.EmojiTable()
        self.sentences = sentences
        self.base = np.array([len(text) for text in sentences], dtype=np.int64)
        # Positions.
        self.sentence, self.word, self.context, self.bare, self.first_word, self.tap_fits = [], [], [], [], [], []
        # States.
        self.position, self.typed_count, self.kind, self.previous, self.emoji, self.saving, self.automatic = (
            [], [], [], [], [], [], [])
        self.start_of_position = []
        for number, text in enumerate(sentences):
            chunks = text.split(" ")
            offset = 0
            for index, chunk in enumerate(chunks):
                parts = rules.parse_chunk(chunk)
                if parts is not None:
                    lead, word, trail = parts
                    before_word = text[:offset] + lead
                    separator = 0 if index == len(chunks) - 1 else 1
                    position = len(self.word)
                    self.sentence.append(number)
                    self.word.append(word)
                    self.first_word.append(index == 0)
                    self.tap_fits.append(rules.tap_fits(before_word + word, trail))
                    if before_word.endswith(" "):
                        self.context.append(before_word[:-1])
                        self.bare.append(False)
                    else:
                        self.context.append(before_word)
                        self.bare.append(True)
                    self.start_of_position.append(len(self.position))
                    for typed_count in range(len(word)):
                        before = before_word + word[:typed_count]
                        found = rules.prediction_context(before, "")
                        self.position.append(position)
                        self.typed_count.append(typed_count)
                        if found is not None:
                            self.kind.append(SHOWN)
                            self.previous.append(found[0])
                        else:
                            self.kind.append(FIELD_START if before == "" else NO_STRIP)
                            self.previous.append("")
                        self.emoji.append(emoji.count_before(before))
                        # A tap types the rest of the word and a space for one key press. With a
                        # mark after the word, the typist still types the space after the mark.
                        self.saving.append(len(word) - typed_count - 1 + (separator if not trail else 0))
                        self.automatic.append(rules.should_auto_capitalize(before_word))
                offset += len(chunk) + 1
        self.sentence = np.array(self.sentence, dtype=np.int64)
        self.first_word = np.array(self.first_word, dtype=bool)
        self.tap_fits = np.array(self.tap_fits, dtype=bool)
        self.position = np.array(self.position, dtype=np.int64)
        self.typed_count = np.array(self.typed_count, dtype=np.int64)
        self.kind = np.array(self.kind, dtype=np.int8)
        self.emoji = np.array(self.emoji, dtype=np.int64)
        self.saving = np.array(self.saving, dtype=np.int64)
        self.start_of_position = np.array(self.start_of_position, dtype=np.int64)

    def typed(self, state: int) -> str:
        return self.word[self.position[state]][:self.typed_count[state]]

    def contexts(self) -> tuple[list[str], np.ndarray]:
        """The different texts that a model reads, and the number of the text of each position."""
        numbers: dict[str, int] = {}
        of_position = np.array([numbers.setdefault(context, len(numbers)) for context in self.context], dtype=np.int64)
        return list(numbers), of_position


def states_of(name: str, half: str) -> States:
    return States([row["text"] for row in read_texts(name, half)])


def read_lexicon_file(path: Path):
    """The words of a lexicon file of version 2 with their log probabilities, and its word pairs
    as (first word number, second word number, log probability) arrays."""
    data = path.read_bytes()
    magic, version, nodes, words, string_bytes, pairs, model, _ = struct.unpack_from("<8I", data, 0)
    if magic != 0x4C4F5544 or version != 2 or model != 0:
        raise SystemExit(f"{path} is not an English lexicon of version 2")
    word_table = 32 + nodes * 12
    pair_index = word_table + words * 12
    pair_table = pair_index + (words + 1) * 4
    strings = len(data) - string_bytes
    if pair_table + pairs * 8 != strings:
        raise SystemExit(f"{path}: the parts of the file do not add up to its size")
    records = np.frombuffer(data, dtype=np.dtype([("offset", "<u4"), ("log", "<f4"), ("weight", "<f4")]), count=words, offset=word_table)
    texts = []
    for offset in records["offset"]:
        end = data.index(b"\0", strings + int(offset))
        texts.append(data[strings + int(offset):end].decode("utf-8"))
    starts = np.frombuffer(data, dtype="<u4", count=words + 1, offset=pair_index).astype(np.int64)
    listed = np.frombuffer(data, dtype=np.dtype([("second", "<u4"), ("log", "<f4")]), count=pairs, offset=pair_table)
    return texts, records["log"].astype(np.float64), starts, listed["second"].astype(np.int64), listed["log"].astype(np.float64)


class Engine:
    """The word order of `duo_predict_english` (Engine/duo_engine.c): the lists of `duo_cli
    predict`, and the engine's log value of every candidate word after a previous word, which
    this class computes from the lexicon files as `word_after` and `supplement_word_value` do."""

    def __init__(self, cli: Path, words: list[str]):
        self.cli = cli
        self.capitals = rules.PreferredCapitals(CAPITALS_TABLE)
        main_texts, main_log, self.pair_start, self.pair_second, self.pair_log = read_lexicon_file(LEXICON)
        extra_texts, extra_log, _, _, _ = read_lexicon_file(SUPPLEMENT)
        index = {word: number for number, word in enumerate(words)}
        self.main_number = {word: number for number, word in enumerate(main_texts)}
        self.extra_words = set(extra_texts)
        self.main_own = np.full(len(words), -np.inf)
        self.extra_own = np.full(len(words), -np.inf)
        self.table_of_main = np.array([index[word] for word in main_texts], dtype=np.int64)
        self.main_own[self.table_of_main] = main_log
        self.main_log = main_log
        self.extra_own[[index[word] for word in extra_texts]] = extra_log
        self.cache: dict[str, np.ndarray] = {}

    def values(self, previous: str) -> np.ndarray:
        """The log value of every candidate word after `previous`, in the order of the tables."""
        cached = self.cache.get(previous)
        if cached is not None:
            return cached
        number = self.main_number.get(previous) if previous else None
        known = previous != "" and (number is not None or previous in self.extra_words)
        base = np.log(1.0 - PAIR_WEIGHT) if known else 0.0
        main = self.main_own + base
        if number is not None:
            low, high = self.pair_start[number], self.pair_start[number + 1]
            second = self.pair_second[low:high]
            blend = np.log(PAIR_WEIGHT * np.exp(self.pair_log[low:high]) + (1.0 - PAIR_WEIGHT) * np.exp(self.main_log[second]))
            main[self.table_of_main[second]] = blend
        values = np.maximum(main, self.extra_own + base).astype(np.float32)
        if len(self.cache) < 4000:
            self.cache[previous] = values
        return values

    def lists(self, requests: list[tuple[str, str]]) -> dict[tuple[str, str], list[str]]:
        """The first 20 words of `duo_cli predict` for each pair of previous word and lower-case
        typed letters. Typed letters outside the engine's input give no words."""
        asked = [pair for pair in dict.fromkeys(requests) if ENGINE_TYPED.fullmatch(pair[1])]
        lines = "".join(f"{number}\t{previous}\t{typed}\n" for number, (previous, typed) in enumerate(asked))
        run = subprocess.run(
            [str(self.cli), "predict", str(LEXICON), f"supplement={SUPPLEMENT}", f"words={ENGINE_WORDS}"],
            input=lines.encode("utf-8"), capture_output=True, check=False)
        if run.returncode != 0:
            raise SystemExit(f"duo_cli predict ended with {run.returncode}: {run.stderr.decode('utf-8', 'replace')[-2000:]}")
        answers: dict[tuple[str, str], list[str]] = {}
        for line in run.stdout.decode("utf-8").splitlines():
            number, _, listed = line.partition("\t")
            answers[asked[int(number)]] = listed.split(" ") if listed else []
        if len(answers) != len(asked):
            raise SystemExit(f"duo_cli answered {len(answers)} of {len(asked)} requests")
        return answers

    def shown(self, words: list[str], typed: str, automatic_first: bool) -> list[str]:
        """The forms that build 62 shows for the engine's words (`KeyboardTextController.predictedWords`)."""
        shown: list[str] = []
        for word in words:
            form = self.capitals.form(rules.predicted_word(word, typed), typed, automatic_first)
            if form not in shown:
                shown.append(form)
        return shown

    def shown_with_a_capital(self, words: list[str]) -> list[str]:
        """The engine's words at the start of a field, where the keyboard types the first letter
        as a capital by itself."""
        shown: list[str] = []
        for word in words:
            letter = word[0].upper()
            form = self.capitals.form(rules.predicted_word(word, letter), letter, True)
            if form not in shown:
                shown.append(form)
        return shown


def engine_places(states: States, engine: Engine) -> np.ndarray:
    """The place of the written word in the engine's list at every strip state, or NEVER. A
    state at the start of a field gets the place in the list with a capital."""
    requests = []
    for state in range(len(states.position)):
        if states.kind[state] == SHOWN:
            requests.append((states.previous[state], states.typed(state).lower()))
    requests.append(("", ""))
    lists = engine.lists(requests)
    start_list = engine.shown_with_a_capital(lists[("", "")])
    places = np.full(len(states.position), NEVER, dtype=np.int64)
    for state in range(len(states.position)):
        target = states.word[states.position[state]]
        if states.kind[state] == SHOWN:
            typed = states.typed(state)
            listed = lists.get((states.previous[state], typed.lower()), [])
            shown = engine.shown(listed, typed, bool(states.automatic[state]))
        elif states.kind[state] == FIELD_START:
            shown = start_list
        else:
            continue
        if target in shown:
            places[state] = shown.index(target)
    return places

"""Ranks the predicted words at every word of the dev stream sentences
(scripts/prediction-strip/README.md gives the definitions).

For each word of each sentence the script asks `lm_score ... next` for the log probability of
every token after the text before the word. It then writes the place of the right word in the
list of each method, for every count of typed letters from 0 to the length of the word less 1.

Methods:
  F    the lexicon's frequency order.
  A    the log probability of the first token of the word. Words of one value keep the order of F.
  A2   A plus the log of the word's unigram share among the forms with the same first token.
  B    A2, and the 8 words of 2 or more tokens with the highest A2 value without a typed letter
       get an exact value from one more request: the log probability of all tokens of the form,
       plus the log probability that the next token starts with a space.
  B0   B without the term of the next token.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/measure.py --lm ~/predstrip/bin/lm_score \
        --model MODEL.gguf --tables build/prediction-strip/tables --shard 0/4 \
        --out build/prediction-strip/ranks/shard-0.jsonl
    ... --show endomstream-dev-technical-0002:3     prints the lists at one word and writes no file
"""
import argparse
import bisect
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
from rerank import language_model_text  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases" / "english-domain-stream.dev.jsonl"
METHODS = ("F", "A", "A2", "B", "B0")
EXACT_WORDS = 8
NEVER = np.float32(-np.inf)


class Scorer:
    """One `lm_score MODEL THREADS next` process."""

    def __init__(self, program: str, model: str, threads: int, log: Path):
        self.log = log.open("wb")
        self.process = subprocess.Popen(
            [program, model, str(threads), "next"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log)
        ready = self.process.stdout.readline().decode("utf-8")
        if not ready.startswith("ready vocabulary="):
            raise SystemExit(f"lm_score did not start: {ready!r}")
        self.vocabulary = int(ready.split()[1].split("=")[1])
        self.next_seconds: list[float] = []
        self.exact_seconds: list[float] = []

    def send(self, line: str) -> None:
        if "\n" in line:
            raise SystemExit(f"a request holds a line break: {line!r}")
        self.process.stdin.write(line.encode("utf-8") + b"\n")
        self.process.stdin.flush()

    def next_tokens(self, context: str) -> np.ndarray:
        """The log probability of every token right after `context`."""
        if "\t" in context:
            raise SystemExit(f"a context holds a tab: {context!r}")
        started = time.monotonic()
        self.send(context)
        wanted = self.vocabulary * 4
        data = bytearray()
        while len(data) < wanted:
            part = self.process.stdout.read(wanted - len(data))
            if not part:
                raise SystemExit(f"lm_score ended in a next-token block; see {self.log.name}")
            data += part
        self.next_seconds.append(time.monotonic() - started)
        return np.frombuffer(bytes(data), dtype=np.float32)

    def exact(self, context: str, forms: list[str]) -> list[tuple[float, float]]:
        """(log probability, log probability of a space-led next token) of each form after `context`."""
        started = time.monotonic()
        self.send("\t".join([context, *forms]))
        fields = self.process.stdout.readline().decode("utf-8").rstrip("\n").split("\t")
        if len(fields) != len(forms):
            raise SystemExit(f"lm_score answered {fields!r} for {forms!r}; see {self.log.name}")
        self.exact_seconds.append(time.monotonic() - started)
        return [tuple(float(value) for value in field.split(" ")) for field in fields]

    def close(self) -> None:
        self.process.stdin.close()
        self.process.wait()
        self.log.close()


class Tables:
    def __init__(self, folder: Path):
        arrays = np.load(folder / "tables.npz")
        forms = json.loads((folder / "forms.json").read_text(encoding="utf-8"))
        self.words: list[str] = forms["words"]
        self.spaced_forms: list[list[str]] = forms["spaced"]
        self.start_forms: list[list[str]] = forms["start"]
        self.index = {word: number for number, word in enumerate(self.words)}
        self.vocabulary = int(arrays["vocabulary"])
        self.frequency_rank = arrays["frequency_rank"]
        self.spaced = (arrays["spaced_first"], arrays["spaced_length"], arrays["spaced_share"], arrays["spaced_capital"])
        self.start = (arrays["start_first"], arrays["start_length"], arrays["start_share"])
        # The token of the bar that opens the typed span in the prompt format of the shipped model.
        self.bar_after_space = int(arrays["bar_after_space"])
        self.bar_at_start = int(arrays["bar_at_start"])
        if self.words != sorted(self.words):
            raise SystemExit("the words of the tables are not sorted")

    def span(self, typed: str) -> tuple[int, int, int | None]:
        """The words that start with `typed`, as a range of word numbers, and the number of the
        word that equals `typed`, which the list leaves out."""
        if not typed:
            return 0, len(self.words), None
        low = bisect.bisect_left(self.words, typed)
        high = bisect.bisect_left(self.words, typed + "\U0010FFFF")
        return low, high, (low if low < high and self.words[low] == typed else None)


def place(values: np.ndarray, tables: Tables, target: int, span: tuple[int, int, int | None]) -> int:
    """How many words of the span come before the target: a higher value, or the same value
    and an earlier place in the frequency order."""
    low, high, left_out = span
    own = values[target]
    ranks = tables.frequency_rank
    part = values[low:high]
    before = int(np.count_nonzero(part > own))
    before += int(np.count_nonzero((part == own) & (ranks[low:high] < ranks[target])))
    if left_out is not None and (values[left_out] > own or (values[left_out] == own and ranks[left_out] < ranks[target])):
        before -= 1
    return before


def first_words(values: np.ndarray, tables: Tables, span: tuple[int, int, int | None], count: int) -> list[int]:
    low, high, left_out = span
    order = np.lexsort((tables.frequency_rank[low:high], -values[low:high].astype(np.float64)))
    numbers = [low + int(index) for index in order[:count + 1] if low + int(index) != left_out]
    return [number for number in numbers[:count] if values[number] > NEVER]


def position_values(tables: Tables, scorer: Scorer, context: str, at_start: bool):
    """The value of every word after `context` for each model method. Returns two dictionaries,
    method to values: with every form allowed, and with only the forms that start with a
    capital. Also returns the form that each word shows (the form with the highest A2 value),
    and the log probability of the bar token."""
    scores = np.append(scorer.next_tokens(context), NEVER)
    bar = float(scores[tables.bar_at_start if at_start else tables.bar_after_space])
    if at_start:
        first, length, share = tables.start
        capital = None
        forms = tables.start_forms
    else:
        first, length, share, capital = tables.spaced
        forms = tables.spaced_forms
    token = scores[first]
    with_share = token + share
    rows = np.arange(len(tables.words))
    shown = np.argmax(with_share, axis=1)
    every = {"A": token.max(axis=1), "A2": with_share[rows, shown]}

    # One more request: the exact value of the multi-token words that A2 puts first.
    values = every["A2"]
    multi = np.nonzero(length[rows, shown] >= 2)[0]
    if len(multi) > 8 * EXACT_WORDS:
        # The few highest values first, so the full order below sorts a short list.
        multi = multi[np.argpartition(-values[multi], 8 * EXACT_WORDS)[:8 * EXACT_WORDS]]
    best = multi[np.lexsort((tables.frequency_rank[multi], -values[multi].astype(np.float64)))[:EXACT_WORDS]]
    exact = scorer.exact(context, [forms[int(number)][int(shown[number])] for number in best])
    every["B"] = values.copy()
    every["B0"] = values.copy()
    for number, (log_probability, space_after) in zip(best, exact):
        every["B"][number] = log_probability + space_after
        every["B0"][number] = log_probability

    if capital is None:
        # The keyboard types the first letter of the field as a capital, so every start form has one.
        return every, every, shown, bar
    capital_token = np.where(capital, token, NEVER)
    capital_share = np.where(capital, with_share, NEVER)
    only = {"A": capital_token.max(axis=1), "A2": capital_share.max(axis=1)}
    only["B"] = only["A2"].copy()
    only["B0"] = only["A2"].copy()
    for number, (log_probability, space_after) in zip(best, exact):
        if capital[number, shown[number]]:
            only["B"][number] = log_probability + space_after
            only["B0"][number] = log_probability
    return every, only, shown, bar


def measure(tables: Tables, scorer: Scorer, case: dict, show: int | None = None):
    words = case["intended"].split(" ")
    if any(not word for word in words):
        raise SystemExit(f"{case['id']} holds an empty word")
    frequency = -tables.frequency_rank.astype(np.float32)
    rows = []
    for number, target in enumerate(words):
        if show is not None and number != show:
            continue
        context = language_model_text(" ".join(words[:number]), True)
        every, only, shown, bar = position_values(tables, scorer, context, at_start=number == 0)
        every["F"] = only["F"] = frequency
        known = tables.index.get(target.lower())
        capital_typed = target[0].isupper()
        places: dict[str, list[int | None]] = {method: [] for method in METHODS}
        for typed_count in range(len(target)):
            span = tables.span(target[:typed_count].lower())
            allowed = only if typed_count > 0 and capital_typed else every
            for method in METHODS:
                places[method].append(None if known is None else place(allowed[method], tables, known, span))
            if show is not None and typed_count in (0, 2):
                forms = tables.start_forms if number == 0 else tables.spaced_forms
                print(f"--- {case['id']} word {number}: context {context!r}, target {target!r}, typed {target[:typed_count]!r}")
                for method in METHODS:
                    listed = first_words(allowed[method], tables, span, 10)
                    texts = [tables.words[w] if method == "F" else forms[w][int(shown[w])] for w in listed]
                    print(f"{method:>3} (target at place {places[method][-1]}): " + "  ".join(texts))
        rows.append({"id": case["id"], "stream": case["stream"], "word": number, "target": target,
                     "known": known is not None, "bar": round(bar, 4), "places": places})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--tables", required=True, type=Path)
    parser.add_argument("--shard", default="0/1", help="INDEX/COUNT: this run takes every COUNT-th sentence")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--show", help="CASE ID:WORD NUMBER: print the lists at one word")
    args = parser.parse_args()

    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines()]
    if any(case["split"] != "dev" or case["context"] for case in cases):
        raise SystemExit("the measurement reads only dev sentences that open the field")
    tables = Tables(args.tables)

    if args.show:
        case_id, word = args.show.rsplit(":", 1)
        case = next(case for case in cases if case["id"] == case_id)
        scorer = Scorer(args.lm, args.model, args.threads, args.tables / "show.lm_score.log")
        if scorer.vocabulary != tables.vocabulary:
            raise SystemExit("the tables come from another vocabulary")
        measure(tables, scorer, case, show=int(word))
        scorer.close()
        return

    if args.out is None:
        raise SystemExit("--out is required without --show")
    shard, shards = (int(value) for value in args.shard.split("/"))
    mine = cases[shard::shards]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.out.exists():
        # A run that stopped goes on after its last whole sentence.
        kept = []
        for line in args.out.read_text(encoding="utf-8").splitlines():
            try:
                kept.append(json.loads(line))
            except json.JSONDecodeError:
                break
        counts: dict[str, int] = {}
        for row in kept:
            counts[row["id"]] = counts.get(row["id"], 0) + 1
        lengths = {case["id"]: len(case["intended"].split(" ")) for case in mine}
        done = {case_id for case_id, count in counts.items() if lengths.get(case_id) == count}
        with args.out.open("w", encoding="utf-8") as file:
            for row in kept:
                if row["id"] in done:
                    file.write(json.dumps(row, ensure_ascii=False) + "\n")
    scorer = Scorer(args.lm, args.model, args.threads, args.out.with_suffix(".lm_score.log"))
    if scorer.vocabulary != tables.vocabulary:
        raise SystemExit("the tables come from another vocabulary")
    started = time.monotonic()
    with args.out.open("a", encoding="utf-8") as file:
        for count, case in enumerate(mine):
            if case["id"] in done:
                continue
            for row in measure(tables, scorer, case):
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
            file.flush()
            if count % 50 == 0:
                print(f"shard {args.shard}: sentence {count} of {len(mine)}, {time.monotonic() - started:.0f} s", flush=True)
    scorer.close()
    timing = {"threads": args.threads, "next_requests": len(scorer.next_seconds), "exact_requests": len(scorer.exact_seconds),
              "next_ms_median": float(np.median(scorer.next_seconds) * 1000) if scorer.next_seconds else None,
              "next_ms_mean": float(np.mean(scorer.next_seconds) * 1000) if scorer.next_seconds else None,
              "exact_ms_median": float(np.median(scorer.exact_seconds) * 1000) if scorer.exact_seconds else None,
              "exact_ms_mean": float(np.mean(scorer.exact_seconds) * 1000) if scorer.exact_seconds else None}
    args.out.with_suffix(".timing.json").write_text(json.dumps(timing, indent=2) + "\n", encoding="utf-8")
    print(f"shard {args.shard}: done, {json.dumps(timing)}", flush=True)


if __name__ == "__main__":
    main()

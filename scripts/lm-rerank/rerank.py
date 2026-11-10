"""Re-ranks the English typing engine's readings with a small language model, on the dev half.

The script types every dev case through a Python copy of the keyboard's correction rules
(`correctLastWord` in Shared/KeyboardTextController.swift), as Tests/TypingEvaluationTests.swift
does on the Mac: the context is already in the field, then come the typed characters and one
space. At each correction the engine (`duo_english_readings` in Engine/duo_engine.c) gives its
readings of the typed span. Two choosers pick one:

- control: the engine's own choice, the text that `duo_correct_english` returns.
- re-ranked: combined = engine score + weight * language-model log probability of the reading
  after the text before the span. The engine's choice stays unless another reading's combined
  score is higher by a margin. The margin depends on the move: from the text as typed to a
  correction, from a correction back to the text as typed, and from one correction to another.

The weight, the three margins and the use of the "space after" probability are tuned on the dev
half by grid search. The test half is never read.

Usage, from the repository root, on Linux:
    python3 scripts/lm-rerank/rerank.py --shim build/lm-rerank/libduo_shim.so \
        --lm build/lm-rerank/lm_score --model build/lm-rerank/models/NAME.gguf --name NAME \
        --out build/lm-rerank/results/NAME
    python3 scripts/lm-rerank/rerank.py --shim build/lm-rerank/libduo_shim.so --name control \
        --out build/lm-rerank/results/control          # control only, without a model
"""
import argparse
import ctypes
import hashlib
import itertools
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "typing-evaluation"))
from score import load_cases, score  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
# Only the dev half. The test half stays unread.
CASE_FILES = [CASES / "english.dev.jsonl", CASES / "english-symbols.dev.jsonl"]
LEXICON = ROOT / "Shared" / "lexicon-english.bin"
# Readings per correction that the language model scores, as in the phone measurement (8 candidates).
READINGS = 8

TERMINATORS = set(" .,!?;:\n")
SYMBOLS_BESIDE_LETTERS = set(",-.0123456789;[")
SYMBOLS_INSIDE_WORDS = set("0123456789[")
RECENT_CONTEXT_LENGTH = 48

GRID = {
    "weight": [0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0],
    "margin_from_typed": [0, 1, 2, 3, 4, 6, 8, 12, 16, 24],
    "margin_to_typed": [0, 2, 4, 8, 99],
    "margin_other": [0, 2],
    "space_after": [0, 1],
}


# ---- The engine ----

class Engine:
    def __init__(self, shim: Path, lexicon: Path):
        self.library = ctypes.CDLL(str(shim))
        self.library.shim_open.argtypes = [ctypes.c_char_p]
        self.library.shim_readings.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        self.library.shim_correct.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        if self.library.shim_open(str(lexicon).encode()) != 1:
            raise SystemExit(f"{lexicon} is not a valid lexicon file")
        self.buffer = ctypes.create_string_buffer(1 << 16)
        self.cache: dict[tuple[str, str], list[dict] | None] = {}

    def readings(self, previous_word: str, typed: str) -> list[dict] | None:
        key = (previous_word, typed)
        if key in self.cache:
            return self.cache[key]
        count = self.library.shim_readings(previous_word.encode(), typed.encode(), READINGS, self.buffer, len(self.buffer))
        if count < 0:
            raise SystemExit("the readings do not fit the buffer")
        result = None
        if count > 0:
            result = []
            for line in self.buffer.value.decode().splitlines():
                text, engine_score, slips, as_typed, chosen = line.split("\t")
                result.append({"text": text, "score": float(engine_score), "slips": float(slips),
                               "as_typed": as_typed == "1", "chosen": chosen == "1"})
            if sum(r["chosen"] for r in result) != 1 or sum(r["as_typed"] for r in result) != 1:
                raise SystemExit(f"readings of {typed!r} need one chosen and one as typed: {result}")
            # The chosen reading must be the text that duo_correct_english gives.
            if self.library.shim_correct(previous_word.encode(), typed.encode(), self.buffer, len(self.buffer)) != 1:
                raise SystemExit(f"duo_correct_english refused {typed!r} that duo_english_readings read")
            correct = self.buffer.value.decode()
            if next(r["text"] for r in result if r["chosen"]) != correct:
                raise SystemExit(f"chosen reading of {typed!r} differs from duo_correct_english: {correct!r}")
        self.cache[key] = result
        return result


# ---- The language model ----

def language_model_text(text: str, at_start: bool) -> str:
    """The text as a person would see it with automatic capitals: the word i and its
    contractions, and the first letter of the text when it opens the field."""
    words = ["I" + word[1:] if word == "i" or word.startswith("i'") else word for word in text.split(" ")]
    text = " ".join(words)
    if at_start and text:
        text = text[0].upper() + text[1:]
    return text


class LanguageModel:
    def __init__(self, program: Path, model: Path, threads: int):
        self.process = subprocess.Popen([str(program), str(model), str(threads)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        ready = self.process.stdout.readline()
        if not ready.startswith("ready"):
            raise SystemExit(f"lm_score did not start: {ready!r} {self.process.stderr.read()}")
        self.ready = ready.strip()
        self.cache: dict[tuple[str, tuple[str, ...]], dict[str, tuple[float, float]]] = {}
        self.requests = 0
        self.seconds = 0.0

    def scores(self, context: str, candidates: list[str]) -> dict[str, tuple[float, float]]:
        key = (context, tuple(sorted(candidates)))
        if key not in self.cache:
            lm_context = language_model_text(context, True)
            lm_candidates = [language_model_text(c, not context) for c in key[1]]
            for text in [lm_context, *lm_candidates]:
                if "\t" in text or "\n" in text:
                    raise SystemExit(f"a text holds a tab or a line break: {text!r}")
            started = time.monotonic()
            self.process.stdin.write("\t".join([lm_context, *lm_candidates]) + "\n")
            self.process.stdin.flush()
            answer = self.process.stdout.readline()
            self.seconds += time.monotonic() - started
            self.requests += 1
            fields = answer.rstrip("\n").split("\t")
            if len(fields) != len(key[1]):
                raise SystemExit(f"lm_score answered {answer!r} to {key}: {self.process.stderr.read()}")
            self.cache[key] = {c: tuple(float(v) for v in f.split(" ")) for c, f in zip(key[1], fields)}
        return self.cache[key]

    def close(self) -> str:
        self.process.stdin.close()
        report = self.process.stderr.read()
        self.process.wait()
        return report


# ---- Choosers ----

@dataclass(frozen=True)
class Setting:
    weight: float
    margin_from_typed: float
    margin_to_typed: float
    margin_other: float
    space_after: int


def choose(readings: list[dict], context: str, setting: Setting | None, model: LanguageModel | None) -> str:
    chosen = next(r for r in readings if r["chosen"])
    if setting is None or len(readings) == 1:
        return chosen["text"]
    lm = model.scores(context, [r["text"] for r in readings])

    def combined(reading: dict) -> float:
        log_probability, space_after = lm[reading["text"]]
        return reading["score"] + setting.weight * (log_probability + (space_after if setting.space_after else 0.0))

    best = max(readings, key=combined)
    if best is chosen:
        return chosen["text"]
    if chosen["as_typed"]:
        margin = setting.margin_from_typed
    elif best["as_typed"]:
        margin = setting.margin_to_typed
    else:
        margin = setting.margin_other
    return best["text"] if combined(best) - combined(chosen) >= margin else chosen["text"]


# ---- The keyboard's correction rules, from Shared/KeyboardTextLogic.swift and KeyboardTextController.swift ----

def correctable_word(before: str) -> str | None:
    start = len(before)
    while start > 0:
        character = before[start - 1]
        if character.isascii() and (character.isalpha() or character == "'" or character in SYMBOLS_INSIDE_WORDS):
            start -= 1
        else:
            break
    if 0 < start < len(before) and before[start - 1] in SYMBOLS_BESIDE_LETTERS:
        start -= 1
    word = before[start:]
    if len(word) >= 2 and word[0] in SYMBOLS_BESIDE_LETTERS and word[1].isupper():
        start += 1
        word = before[start:]
    if not word or word[-1] == "'":
        return None
    symbol_count = sum(c in SYMBOLS_BESIDE_LETTERS for c in word)
    if symbol_count == 0:
        if not word[0].isalpha():
            return None
    else:
        letter_count = sum(c.isalpha() for c in word)
        if symbol_count != 1 or letter_count < 2 or word[0] == "'":
            return None
    if start > 0:
        preceding = before[start - 1]
        if not (preceding.isspace() or preceding in "([{\""):
            return None
        if symbol_count > 0 and preceding in SYMBOLS_BESIDE_LETTERS:
            return None
    if any(c.isupper() for c in word[1:]):
        return None
    return word


def word_before_space(text: str) -> str:
    if not text.endswith(" "):
        return ""
    head = text[:-1]
    start = len(head)
    while start > 0 and head[start - 1].isascii() and (head[start - 1].isalpha() or head[start - 1] == "'"):
        start -= 1
    return head[start:].lower()


@dataclass
class RecentWord:
    typed: str
    shown: str
    context: str


def type_case(case: dict, engine: Engine, setting: Setting | None, model: LanguageModel | None) -> str:
    """Types one case and returns the text the field holds after the context."""
    start = case["context"] + " " if case["context"] else ""
    document = start
    recent: RecentWord | None = None
    for character in case["typed"] + " ":
        if character in TERMINATORS:
            earlier, recent = recent, None
            before = document
            word = correctable_word(before)
            if word is None:
                if earlier is not None and character in SYMBOLS_BESIDE_LETTERS and before.endswith(earlier.context):
                    recent = earlier
            else:
                typed_span, shown_span = word, word
                if (earlier is not None and before.endswith(earlier.context + word)
                        and correctable_word(before[:len(before) - (len(word) + 1)]) == earlier.shown):
                    typed_span = earlier.typed + " " + word
                    shown_span = earlier.shown + " " + word
                typed_words = [w for w in typed_span.split(" ") if w]
                text_before = before[:len(before) - len(shown_span)]
                reading = None
                if len(typed_span) >= 2:
                    readings = engine.readings(word_before_space(text_before), typed_span.lower())
                    if readings is not None:
                        reading = choose(readings, text_before.rstrip(" "), setting, model)
                final = reading if reading is not None else shown_span
                final_words = [w for w in final.split(" ") if w]
                if final != shown_span:
                    document = text_before + final
                if character == " " and final_words:
                    same_count = len(final_words) == len(typed_words)
                    recent = RecentWord(typed=word if same_count else final_words[-1], shown=final_words[-1],
                                        context=(document + " ")[-RECENT_CONTEXT_LENGTH:])
        document += character
    return document[len(start):].strip()


# ---- Scoring ----

def run(cases: list[dict], engine: Engine, setting: Setting | None, model: LanguageModel | None) -> dict[str, str]:
    return {case["id"]: type_case(case, engine, setting, model) for case in cases}


def summarize(cases: list[dict], predictions: dict[str, str]) -> dict:
    """Groups of both case files, and the count of right cases over all of them."""
    summary = score("english", cases, predictions)
    groups = {name: {"right": entry["right"], "cases": entry["cases"], "accuracy": entry["accuracy"]}
              for name, entry in summary["groups"].items()}
    categories = {name: {"right": entry["right"], "cases": entry["cases"]} for name, entry in summary["categories"].items()}
    total = sum(entry["right"] for entry in summary["categories"].values())
    return {"groups": groups, "categories": categories, "right": total, "cases": len(cases)}


def keeps_clean(candidate: dict, control: dict) -> bool:
    return all(candidate["groups"][g]["right"] >= control["groups"][g]["right"] for g in ("clean", "clean_symbols"))


def fold_of(case_id: str) -> int:
    return hashlib.sha256(case_id.encode()).digest()[0] & 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.lm is None) != (arguments.model is None):
        raise SystemExit("--lm and --model go together")

    cases = load_cases(CASE_FILES)
    if any(case["split"] != "dev" for case in cases):
        raise SystemExit("a case outside the dev half")
    engine = Engine(arguments.shim, LEXICON)
    arguments.out.mkdir(parents=True, exist_ok=True)

    control_predictions = run(cases, engine, None, None)
    control = summarize(cases, control_predictions)
    print("control", json.dumps(control["groups"]), flush=True)
    result = {"name": arguments.name, "cases": [p.name for p in CASE_FILES], "readings_per_correction": READINGS,
              "control": control}
    write_predictions(arguments.out / "control.dev.jsonl", cases, control_predictions)
    calls = [len(r) for r in engine.cache.values() if r is not None]
    result["engine_calls"] = {"distinct_spans": len(calls), "mean_readings": sum(calls) / max(1, len(calls))}

    if arguments.model is not None:
        model = LanguageModel(arguments.lm, arguments.model, arguments.threads)
        result["lm_ready"] = model.ready
        settings = [Setting(*values) for values in itertools.product(*GRID.values())]
        rows = []
        started = time.monotonic()
        for index, setting in enumerate(settings):
            predictions = run(cases, engine, setting, model)
            summary = summarize(cases, predictions)
            per_fold = [sum(1 for c in cases if fold_of(c["id"]) == f and predictions[c["id"]].lower() == c["intended"].lower())
                        for f in (0, 1)]
            rows.append({"setting": setting.__dict__, "summary": summary, "fold_right": per_fold})
            if index % 50 == 0:
                print(f"setting {index + 1} of {len(settings)}, {time.monotonic() - started:.0f} s, "
                      f"{model.requests} model requests in {model.seconds:.0f} s", flush=True)
        control_fold = [sum(1 for c in cases if fold_of(c["id"]) == f and control_predictions[c["id"]].lower() == c["intended"].lower())
                        for f in (0, 1)]
        allowed = [row for row in rows if keeps_clean(row["summary"], control)]
        best = max(allowed, key=lambda row: row["summary"]["right"]) if allowed else None
        result["grid"] = {name: values for name, values in GRID.items()}
        result["settings_tried"] = len(rows)
        result["settings_keeping_clean"] = len(allowed)
        result["tuned"] = best
        # Two-fold check inside the dev half: tune on one fold, read the gain on the other.
        result["control_fold_right"] = control_fold
        folds = []
        for tune_fold in (0, 1):
            other = 1 - tune_fold
            pick = max(allowed, key=lambda row: row["fold_right"][tune_fold]) if allowed else None
            folds.append({"tuned_on": tune_fold, "setting": pick and pick["setting"],
                          "gain_on_tuning_fold": pick and pick["fold_right"][tune_fold] - control_fold[tune_fold],
                          "gain_on_other_fold": pick and pick["fold_right"][other] - control_fold[other]})
        result["fold_check"] = folds
        if best is not None:
            tuned_predictions = run(cases, engine, Setting(**best["setting"]), model)
            write_predictions(arguments.out / "reranked.dev.jsonl", cases, tuned_predictions)
        result["lm_requests"] = model.requests
        result["lm_seconds"] = model.seconds
        result["lm_report"] = model.close()
        with (arguments.out / "grid.jsonl").open("w", encoding="utf-8") as file:
            for row in rows:
                file.write(json.dumps(row) + "\n")
        print("tuned", json.dumps(best and {"setting": best["setting"], "groups": best["summary"]["groups"]}), flush=True)
        print("fold check", json.dumps(folds), flush=True)
    (arguments.out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


def write_predictions(path: Path, cases: list[dict], predictions: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for case in cases:
            file.write(json.dumps({"id": case["id"], "output": predictions[case["id"]]}) + "\n")


if __name__ == "__main__":
    main()

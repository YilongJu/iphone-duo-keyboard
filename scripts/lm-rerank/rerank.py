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
    "weight": [0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0],
    "margin_from_typed": [0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48],
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
    def __init__(self, program: Path, model: Path, threads: int, no_context: bool):
        # With no_context the model reads each reading alone, after the start token only.
        self.no_context = no_context
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
        # A reading that opens the field gets its capital, also when the model does not see the text before it.
        opens_field = not context
        if self.no_context:
            context = ""
        key = (context, tuple(sorted(candidates)), opens_field)
        if key not in self.cache:
            lm_context = language_model_text(context, True)
            lm_candidates = [language_model_text(c, opens_field) for c in key[1]]
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
    # None leaves out the apostrophe step of choose(). A number is the lead in model score that
    # a reading of the typed letters with other apostrophes needs over the choice of the margins.
    margin_apostrophe: float | None = None
    # "all": the step runs at every correction, and a twin spells the typed letters with other
    # apostrophes. "next": the step runs only in a span of two or more typed words, and a twin
    # changes the apostrophes of the first word alone and keeps every later word as typed. The
    # model then sees the word after the changed word, and a typed "its" alone stays as it is.
    apostrophe_scope: str = "all"
    # "model": the step compares the model scores alone. "slips": it also takes off each
    # reading's slip cost, 0.5 for a missing apostrophe and 5.5 for an extra one. "slips_only":
    # the slip costs alone, as the comparison without the model.
    apostrophe_score: str = "model"


def engine_choice(readings: list[dict], text_before: str) -> str:
    return next(r for r in readings if r["chosen"])["text"]


def oracle_chooser(target: str):
    """A chooser that knows the intended text: it takes the reading that keeps the field a
    prefix of the intended text, when the list holds one, and the engine's choice otherwise.
    Its score is an upper bound for any chooser over the same lists, one correction at a time."""
    def chooser(readings: list[dict], text_before: str) -> str:
        for reading in readings:
            if target.startswith(text_before + reading["text"] + " "):
                return reading["text"]
        return engine_choice(readings, text_before)
    return chooser


def setting_chooser(setting: Setting, model: LanguageModel | None):
    def chooser(readings: list[dict], text_before: str) -> str:
        return choose(readings, text_before.rstrip(" "), setting, model)
    return chooser


def choose(readings: list[dict], context: str, setting: Setting, model: LanguageModel | None) -> str:
    chosen = next(r for r in readings if r["chosen"])
    if len(readings) == 1:
        return chosen["text"]
    # Weight 0 is the control without the model: the same margins on the engine score alone.
    lm = model.scores(context, [r["text"] for r in readings]) if setting.weight != 0 else None

    def combined(reading: dict) -> float:
        if lm is None:
            return reading["score"]
        log_probability, space_after = lm[reading["text"]]
        return reading["score"] + setting.weight * (log_probability + (space_after if setting.space_after else 0.0))

    best = max(readings, key=combined)
    if best is chosen:
        choice = chosen
    else:
        if chosen["as_typed"]:
            margin = setting.margin_from_typed
        elif best["as_typed"]:
            margin = setting.margin_to_typed
        else:
            margin = setting.margin_other
        choice = best if combined(best) - combined(chosen) >= margin else chosen
    if setting.margin_apostrophe is not None and lm is not None:
        choice = apostrophe_step(readings, choice, lm, setting)
    return choice["text"]


def is_twin(text: str, typed: str, scope: str) -> bool:
    """Whether a reading's text is a twin of the typed text: the same letters, other
    apostrophes. In the scope "next" only the first word may change, and the span holds two
    words or more."""
    if text == typed:
        return False
    if scope == "all":
        return text.replace("'", "") == typed.replace("'", "")
    if scope != "next":
        raise SystemExit(f"unknown apostrophe_scope {scope!r}")
    words, typed_words = text.split(" "), typed.split(" ")
    return (len(typed_words) >= 2 and len(words) == len(typed_words) and words[1:] == typed_words[1:]
            and words[0].replace("'", "") == typed_words[0].replace("'", ""))


def apostrophe_step(readings: list[dict], choice: dict, lm: dict, setting: Setting) -> dict:
    """The apostrophe step. The twin with the highest step score, the first one in the list on a
    tie, replaces the choice when its step score leads the choice's by `margin_apostrophe`. The
    text as typed is never a twin. The step score is the model score, the log probability plus
    the space-after term when the rule uses it, and with `apostrophe_score` "slips" less the
    reading's slip cost.

    The engine's word statistics do not count. They come from a list of word pairs without a
    single contraction, so a contraction never gets a listed pair, and a word beside it never
    gets one either."""
    if setting.apostrophe_score not in ("model", "slips", "slips_only"):
        raise SystemExit(f"unknown apostrophe_score {setting.apostrophe_score!r}")

    def step_score(reading: dict) -> float:
        # "slips_only" is the comparison without the model: the cheaper repair wins.
        if setting.apostrophe_score == "slips_only":
            return -reading["slips"]
        log_probability, space_after = lm[reading["text"]]
        value = log_probability + (space_after if setting.space_after else 0.0)
        return value - reading["slips"] if setting.apostrophe_score == "slips" else value

    typed = next(r for r in readings if r["as_typed"])["text"]
    twins = [r for r in readings if r is not choice and not r["as_typed"] and is_twin(r["text"], typed, setting.apostrophe_scope)]
    if not twins:
        return choice
    twin = max(twins, key=step_score)
    return twin if step_score(twin) - step_score(choice) >= setting.margin_apostrophe else choice


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


def type_case(case: dict, engine: Engine, chooser) -> str:
    """Types one case and returns the text the field holds after the context. `chooser` takes
    the readings and the text before the span and returns the reading to show."""
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
                        reading = chooser(readings, text_before)
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

# The categories of the groups clean and clean_symbols. A setting must keep as many of them right as the control.
CLEAN_CATEGORIES = {"clean_common", "clean_rare", "clean_names_and_terms", "clean_two_words",
                    "clean_symbol_token", "clean_bracket_or_dot_word"}


def run(cases: list[dict], engine: Engine, chooser) -> dict[str, str]:
    return {case["id"]: type_case(case, engine, chooser) for case in cases}


def fold_of(case: dict) -> int:
    """The fold of a case inside the dev half. Cases with the same context and intended text
    share a fold, so one fold does not hold the same phrase as the other."""
    key = case["context"] + "|" + case["intended"].strip().lower()
    return hashlib.sha256(key.encode()).digest()[0] & 1


def summarize(cases: list[dict], predictions: dict[str, str]) -> dict:
    """Groups of both case files, the count of right cases over all of them, and the same
    counts inside each fold of the dev half."""
    summary = score("english", cases, predictions)
    groups = {name: {"right": entry["right"], "cases": entry["cases"], "accuracy": entry["accuracy"]}
              for name, entry in summary["groups"].items()}
    categories = {name: {"right": entry["right"], "cases": entry["cases"]} for name, entry in summary["categories"].items()}
    total = sum(entry["right"] for entry in summary["categories"].values())
    folds = []
    for fold in (0, 1):
        members = [c for c in cases if fold_of(c) == fold]
        right = [c for c in members if predictions[c["id"]].strip().lower() == c["intended"].strip().lower()]
        folds.append({"cases": len(members), "right": len(right),
                      "clean_right": sum(1 for c in right if c["category"] in CLEAN_CATEGORIES)})
    return {"groups": groups, "categories": categories, "right": total, "cases": len(cases), "folds": folds}


def keeps_clean(candidate: dict, control: dict) -> bool:
    return all(candidate["groups"][g]["right"] >= control["groups"][g]["right"] for g in ("clean", "clean_symbols"))


def tune(rows: list[dict], control: dict) -> dict:
    """The best setting on the whole dev half, and the two-fold check. In the check, the clean
    rule and the choice both use the tuning fold only, and the gain is read on the other fold."""
    allowed = [row for row in rows if keeps_clean(row["summary"], control)]
    best = max(allowed, key=lambda row: row["summary"]["right"]) if allowed else None
    folds = []
    for tune_fold in (0, 1):
        other = 1 - tune_fold
        base = control["folds"][tune_fold]
        fold_allowed = [row for row in rows if row["summary"]["folds"][tune_fold]["clean_right"] >= base["clean_right"]]
        pick = max(fold_allowed, key=lambda row: row["summary"]["folds"][tune_fold]["right"])
        folds.append({"tuned_on": tune_fold, "setting": pick["setting"],
                      "gain_on_tuning_fold": pick["summary"]["folds"][tune_fold]["right"] - base["right"],
                      "gain_on_other_fold": pick["summary"]["folds"][other]["right"] - control["folds"][other]["right"],
                      "clean_change_on_other_fold": pick["summary"]["folds"][other]["clean_right"]
                      - control["folds"][other]["clean_right"]})
    return {"settings_tried": len(rows), "settings_keeping_clean": len(allowed), "tuned": best, "fold_check": folds}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--no-context", action="store_true",
                        help="the model reads each reading without the text before it, as a control")
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

    control_predictions = run(cases, engine, engine_choice)
    control = summarize(cases, control_predictions)
    print("control", json.dumps(control["groups"]), flush=True)
    result = {"name": arguments.name, "cases": [p.name for p in CASE_FILES], "readings_per_correction": READINGS,
              "no_context": arguments.no_context, "control": control}
    write_predictions(arguments.out / "control.dev.jsonl", cases, control_predictions)
    calls = [len(r) for r in engine.cache.values() if r is not None]
    result["engine_calls"] = {"distinct_spans": len(calls), "mean_readings": sum(calls) / max(1, len(calls))}

    # The upper bound over the same reading lists.
    oracle_predictions = {case["id"]: type_case(case, engine, oracle_chooser(
        (case["context"] + " " if case["context"] else "") + case["intended"].strip().lower() + " ")) for case in cases}
    result["oracle"] = summarize(cases, oracle_predictions)
    print("oracle", json.dumps(result["oracle"]["groups"]), flush=True)

    # The same margins without the model, tuned the same way.
    no_model_settings = [Setting(0.0, *values, 0) for values in itertools.product(
        GRID["margin_from_typed"], GRID["margin_to_typed"], GRID["margin_other"])]
    no_model_rows = [{"setting": s.__dict__, "summary": summarize(cases, run(cases, engine, setting_chooser(s, None)))}
                     for s in no_model_settings]
    result["without_model"] = tune(no_model_rows, control)
    print("without model", json.dumps({"setting": result["without_model"]["tuned"]["setting"],
                                       "right": result["without_model"]["tuned"]["summary"]["right"],
                                       "fold_check": result["without_model"]["fold_check"]}), flush=True)

    if arguments.model is not None:
        model = LanguageModel(arguments.lm, arguments.model, arguments.threads, arguments.no_context)
        result["lm_ready"] = model.ready
        settings = [Setting(*values) for values in itertools.product(*GRID.values())]
        rows = []
        started = time.monotonic()
        for index, setting in enumerate(settings):
            predictions = run(cases, engine, setting_chooser(setting, model))
            rows.append({"setting": setting.__dict__, "summary": summarize(cases, predictions)})
            if index % 100 == 0:
                print(f"setting {index + 1} of {len(settings)}, {time.monotonic() - started:.0f} s, "
                      f"{model.requests} model requests in {model.seconds:.0f} s", flush=True)
        result["grid"] = {name: values for name, values in GRID.items()}
        result.update(tune(rows, control))
        best = result["tuned"]
        if best is not None:
            tuned_predictions = run(cases, engine, setting_chooser(Setting(**best["setting"]), model))
            write_predictions(arguments.out / "reranked.dev.jsonl", cases, tuned_predictions)
        result["lm_requests"] = model.requests
        result["lm_seconds"] = model.seconds
        result["lm_report"] = model.close()
        with (arguments.out / "grid.jsonl").open("w", encoding="utf-8") as file:
            for row in rows:
                file.write(json.dumps(row) + "\n")
        print("tuned", json.dumps(best and {"setting": best["setting"], "groups": best["summary"]["groups"]}), flush=True)
        print("fold check", json.dumps(result["fold_check"]), flush=True)
        print(result["lm_report"], flush=True)
    (arguments.out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


def write_predictions(path: Path, cases: list[dict], predictions: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for case in cases:
            file.write(json.dumps({"id": case["id"], "output": predictions[case["id"]]}) + "\n")


if __name__ == "__main__":
    main()

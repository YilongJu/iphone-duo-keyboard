"""The shared parts of the model-search harness of the domain round.

Every typing of this harness runs as the keyboard ships: the work area "AI and software" is on.
The engine reads with the supplement Shared/supplement-ai-software.bin, the field keeps the typed
capitals, the pack gives its preferred capitals, and the model may not change a typed word that
is new in the pack (rerank.PreferredCapitals.keeping_new_words). The rule of the model is the
keyboard's rule: the weight and the three margins of a setting, then the apostrophe step of
scripts/lm-keyboard/harness_trace.py.

The module holds:
- the evaluation sets and the tuning sets, by name (load_sets);
- the typing of a set with the engine alone, with the perfect chooser and with a model;
- the counts of a set: right cases per category and group, and changed words of running text;
- a scorer that keeps every answer of lm_score in a file, so a run that stops goes on from there.
"""
import hashlib
import json
import os
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-keyboard"))
sys.path.insert(0, str(ROOT / "scripts" / "typing-evaluation"))
import apostrophe_words  # noqa: E402
import harness_trace  # noqa: E402
import rerank  # noqa: E402
from score import GROUPS  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
SHIPPED = harness_trace.TUNED
# The parts of a setting that the grid does not change: the apostrophe step of the keyboard.
STEP = {"margin_apostrophe": SHIPPED.margin_apostrophe, "apostrophe_scope": SHIPPED.apostrophe_scope,
        "apostrophe_score": SHIPPED.apostrophe_score, "apostrophe_prompt": SHIPPED.apostrophe_prompt}
GRID_FIELDS = ("weight", "margin_from_typed", "margin_to_typed", "margin_other", "space_after")

CLEAN = ["clean_common", "clean_rare", "clean_names_and_terms", "clean_two_words"]
GENERATED_GROUPS = {"clean": CLEAN, **GROUPS["english"], "apostrophe_missing": ["apostrophe_missing"],
                    "real_word_slip": ["real_word_slip"]}
NON_WORD_SLIP_GROUPS = ("letter_slips", "space_slips", "symbol_slips", "apostrophe_missing")


def setting_of(values: dict) -> rerank.Setting:
    """A setting of the grid with the apostrophe step of the keyboard."""
    return rerank.Setting(**{name: values[name] for name in GRID_FIELDS}, **STEP)


def grid_settings() -> list[dict]:
    import itertools
    return [dict(zip(GRID_FIELDS, values)) for values in itertools.product(*(rerank.GRID[name] for name in GRID_FIELDS))]


# ---- The sets ----

def load(path: Path) -> list[dict]:
    return rerank.load_cases([path])


def load_sets(data: Path, which: str) -> dict[str, dict]:
    """The sets of one role. Each set is {"kind": ..., "cases": [...]}. The kinds:
    generated   cases with the categories of english.dev.jsonl, counted per group of score.py
    listed      cases counted per category
    domain      cases that name their group, some scored with their capitals
    stream      whole sentences typed without a slip, counted in changed words
    apostrophe  the apostrophe words, counted per category
    `data` holds the sets that the repository does not hold (build/lm-domain/data)."""
    everyday = data / "everyday"
    if which == "tune":
        sets = {"tune_generated": ("generated", load(everyday / "cases.tune.jsonl")),
                "tune_stream": ("stream", load(everyday / "cases.stream.tune.jsonl"))}
        splits = {"tune"}
    elif which == "evaluation":
        apostrophe = load(CASES / "english-apostrophe-words.dev.jsonl")
        sets = {"dev": ("generated", rerank.load_cases(rerank.CASE_FILES)),
                "apostrophe_word": ("apostrophe", apostrophe),
                "apostrophe_next_word": ("apostrophe", [apostrophe_words.with_next_word(case) for case in apostrophe]),
                "published_dev": ("listed", load(everyday / "published.dev.jsonl")),
                "stream_select": ("stream", load(everyday / "cases.stream.select.jsonl")),
                "github_select": ("listed", load(everyday / "cases.github.select.jsonl")),
                "domain_dev": ("domain", load(CASES / "english-domain.dev.jsonl")),
                "domain_stream_dev": ("stream", load(CASES / "english-domain-stream.dev.jsonl")),
                "domain_test": ("domain", load(CASES / "english-domain.test.jsonl")),
                "domain_stream_test": ("stream", load(CASES / "english-domain-stream.test.jsonl"))}
        splits = {"dev", "select", "test"}
        for name in ("domain_test", "domain_stream_test"):
            if any(case["split"] != "test" for case in sets[name][1]):
                raise SystemExit(f"{name} holds a case outside the test half")
    else:
        raise SystemExit(f"unknown role {which!r}")
    for name, (_, cases) in sets.items():
        if any(case["split"] not in splits for case in cases):
            raise SystemExit(f"{name} holds a case outside {splits}")
        if len({case["id"] for case in cases}) != len(cases):
            raise SystemExit(f"{name} holds an id twice")
    return {name: {"kind": kind, "cases": cases} for name, (kind, cases) in sets.items()}


# ---- Typing ----

class Typist:
    """Types cases as the keyboard ships: the pack on, the typed capitals kept, the preferred
    capitals, and the protection of a typed new word."""

    def __init__(self, shim: Path, protect_new_words: bool = True, readings_file: Path | None = None):
        """`readings_file` keeps the engine's readings of every typed span between runs. The
        readings depend only on the span, the word before it, the engine and its two lexicon
        files, so the file holds the SHA-256 values of the shim, the lexicon and the supplement,
        and a file with other values is not read."""
        self.engine = rerank.Engine(shim, rerank.LEXICON, rerank.SUPPLEMENT, use_supplement=True)
        self.capitals = rerank.PreferredCapitals(rerank.CAPITALS_TABLE)
        self.protect = protect_new_words
        self.readings_file = readings_file
        self.readings_key = [sha256_of(path) for path in (shim, rerank.LEXICON, rerank.SUPPLEMENT)]
        self.readings_loaded = 0
        if readings_file is not None and readings_file.exists():
            with readings_file.open("rb") as file:
                key, cache = pickle.load(file)
            if key == self.readings_key:
                self.engine.cache.update(cache)
                self.readings_loaded = len(cache)

    def save_readings(self) -> None:
        """Writes the readings back when this run added some. Another run may have written the
        file in between, so the file is read again first and the two are joined."""
        if self.readings_file is None or len(self.engine.cache) == self.readings_loaded:
            return
        cache = dict(self.engine.cache)
        if self.readings_file.exists():
            with self.readings_file.open("rb") as file:
                key, other = pickle.load(file)
            if key == self.readings_key:
                cache = {**other, **cache}
        temporary = self.readings_file.with_name(f"{self.readings_file.name}.{os.getpid()}.tmp")
        with temporary.open("wb") as file:
            pickle.dump((self.readings_key, cache), file, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temporary, self.readings_file)

    def type(self, case: dict, chooser) -> str:
        return rerank.type_case(case, self.engine, chooser, self.capitals, keep_capitals=True, protect_new_words=self.protect)

    def run(self, cases: list[dict], chooser) -> dict[str, str]:
        return {case["id"]: self.type(case, chooser) for case in cases}

    def run_perfect(self, cases: list[dict]) -> dict[str, str]:
        return {case["id"]: perfect_typing(self, case)[0] for case in cases}


PERFECT_TRIES = 40


def perfect_typing(typist: Typist, case: dict) -> tuple[str, list[dict]]:
    """Types a case with a chooser that knows the intended text, and returns the field text and
    the corrections on the way.

    A reading matches at a correction when it keeps the field a start of the intended text and
    ends at the end of a word of it. The compare leaves the letter case out.
    - A case typed without a slip: the chooser keeps the text as typed at every correction, so
      its field text is the best that any chooser reaches. The engine also lists readings that
      add the next word of the sentence, as "far from my" for the typed "far from". Such a
      reading matches too, and it is not the intended reading, because the person types the
      next word after it.
    - A case with a slip: the chooser takes the longest match first, as the list builder of
      round 1 does. When the field text is then wrong, it tries the other matches, and the text
      as typed at a correction without a match, the last correction first, for PERFECT_TRIES
      typings at most. So its count of right cases is a lower bound of the true ceiling, and it
      is the true ceiling whenever the search ends before its limit.
    At a correction without a match the chooser first takes the engine's choice.

    Each correction is {"text_before", "typed", "readings", "matches", "options", "choice"}.
    `matches` holds the matching reading texts, and `options` the texts that the search tries
    at this correction, in its order."""
    target = ((case["context"] + " " if case["context"] else "") + case["intended"].strip() + " ").lower()
    clean = case["typed"].strip().lower() == case["intended"].strip().lower()

    def run(script: list[str]) -> tuple[str, list[dict]]:
        log: list[dict] = []

        def chooser(readings: list[dict], text_before: str, typed: str | None = None) -> str:
            before = text_before.lower()
            matches = [r["text"] for r in readings if target.startswith(before + r["text"])
                       and target[len(before) + len(r["text"])] in rerank.TERMINATORS]
            as_typed = next(r["text"] for r in readings if r["as_typed"])
            options = sorted(matches, key=len, reverse=True)
            if clean:
                options = [text for text in options if text == as_typed] + [text for text in options if text != as_typed]
            elif not options:
                # The field can still come out right through the capitals rules, as "Next.js".
                engine = rerank.engine_choice(readings, text_before)
                options = [engine] + ([as_typed] if as_typed != engine else [])
            if len(log) < len(script):
                choice = script[len(log)]
            elif options:
                choice = options[0]
            else:
                choice = rerank.engine_choice(readings, text_before)
            log.append({"text_before": text_before, "typed": typed, "readings": readings, "matches": matches,
                        "options": options, "choice": choice})
            return choice

        return typist.type(case, chooser), log

    first = run([])
    if clean or is_right(case, first[0]):
        return first
    tries = 1
    pending = [(first[1], 0)]
    while pending and tries < PERFECT_TRIES:
        log, start = pending.pop()
        for index in range(len(log) - 1, start - 1, -1):
            for other in log[index]["options"][1:]:
                if tries >= PERFECT_TRIES:
                    break
                output, new_log = run([entry["choice"] for entry in log[:index]] + [other])
                tries += 1
                if is_right(case, output):
                    return output, new_log
                pending.append((new_log, index + 1))
    return first


# ---- Counts ----

def is_right(case: dict, output: str) -> bool:
    return rerank.case_is_right(case, output)


def changed_words(case: dict, output: str) -> int:
    """The word edit distance between the field and the typed sentence. The stream "written"
    counts a change of capitals too."""
    exact = case.get("stream") == "written"
    typed = (case["intended"] if exact else case["intended"].lower()).split()
    shown = (output if exact else output.lower()).replace("’", "'").split()
    previous = list(range(len(shown) + 1))
    for i, a in enumerate(typed, 1):
        current = [i]
        for j, b in enumerate(shown, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def stream_name(case: dict) -> str:
    return case.get("stream") or case["category"]


def summarize(kind: str, cases: list[dict], outputs: dict[str, str]) -> dict:
    """The counts of one set. Every kind gives `right` and `cases`, and `categories` as
    {name: [right, cases]}. A set with groups gives `groups` the same way. A stream gives, per
    stream name, the sentences, the words, the changed words and the changed sentences."""
    categories: dict[str, list[int]] = {}
    for case in cases:
        entry = categories.setdefault(case["category"] if "category" in case else stream_name(case), [0, 0])
        # A sentence of running text is right when no word of it changed. The stream "written"
        # counts a change of capitals, so its sentences do too.
        right = changed_words(case, outputs[case["id"]]) == 0 if kind == "stream" else is_right(case, outputs[case["id"]])
        entry[0] += int(right)
        entry[1] += 1
    summary = {"cases": len(cases), "right": sum(v[0] for v in categories.values()), "categories": categories}
    if kind == "generated":
        groups = {}
        for name, members in GENERATED_GROUPS.items():
            present = [categories[m] for m in members if m in categories]
            if present:
                groups[name] = [sum(v[0] for v in present), sum(v[1] for v in present)]
        summary["groups"] = groups
        if all(name in groups for name in NON_WORD_SLIP_GROUPS):
            summary["non_word_slips"] = [sum(groups[name][0] for name in NON_WORD_SLIP_GROUPS),
                                         sum(groups[name][1] for name in NON_WORD_SLIP_GROUPS)]
    elif kind == "domain":
        groups = {}
        for case in cases:
            entry = groups.setdefault(case["group"], [0, 0])
            entry[0] += int(is_right(case, outputs[case["id"]]))
            entry[1] += 1
        summary["groups"] = groups
    elif kind == "stream":
        streams: dict[str, dict] = {}
        for case in cases:
            entry = streams.setdefault(stream_name(case), {"sentences": 0, "words": 0, "changed_words": 0, "changed_sentences": 0})
            distance = changed_words(case, outputs[case["id"]])
            entry["sentences"] += 1
            entry["words"] += len(case["intended"].split())
            entry["changed_words"] += distance
            entry["changed_sentences"] += int(distance > 0)
        summary["streams"] = streams
        summary["words"] = sum(e["words"] for e in streams.values())
        summary["changed_words"] = sum(e["changed_words"] for e in streams.values())
    elif kind not in ("listed", "apostrophe"):
        raise SystemExit(f"unknown kind {kind!r}")
    return summary


# ---- The scorer with a file of its answers ----

class StoredAnswers:
    """Stands between rerank.LanguageModel and lm_score. An answer of lm_score depends only on the
    request line and the model file. The object keeps every answer in a file, one JSON line per
    request, and gives a stored answer without asking lm_score. So a run that stops goes on from
    the stored answers, and a second run of the same model costs no model time."""

    def __init__(self, process, path: Path, model_sha256: str):
        self.process, self.path = process, path
        self.stdin = self.stdout = self
        self.stderr = process.stderr
        self.answers: dict[str, str] = {}
        self.asked = 0
        self.line = None
        if path.exists():
            with path.open(encoding="utf-8") as file:
                header = json.loads(file.readline())
                if header.get("model_sha256") != model_sha256:
                    raise SystemExit(f"{path} holds the answers of another model file")
                for line in file:
                    if not line.endswith("\n"):
                        break  # a line that a stop cut short
                    request, answer = json.loads(line)
                    self.answers[request] = answer
            self.file = path.open("a", encoding="utf-8")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.file = path.open("w", encoding="utf-8")
            self.file.write(json.dumps({"model_sha256": model_sha256}) + "\n")
        self.loaded = len(self.answers)

    def write(self, line: str) -> None:
        self.line = line

    def flush(self) -> None:
        pass

    def readline(self) -> str:
        line = self.line
        if line not in self.answers:
            self.process.stdin.write(line)
            self.process.stdin.flush()
            answer = self.process.stdout.readline()
            if not answer.endswith("\n"):
                raise SystemExit(f"lm_score ended at the request {line!r}: {self.process.stderr.read()}")
            self.answers[line] = answer
            self.asked += 1
            self.file.write(json.dumps([line, answer]) + "\n")
            if self.asked % 200 == 0:
                self.file.flush()
        return self.answers[line]

    def close(self) -> None:
        self.file.close()
        self.process.stdin.close()

    def wait(self) -> int:
        return self.process.wait()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def open_model(program: Path, model: Path, threads: int, answers: Path) -> tuple[rerank.LanguageModel, StoredAnswers, str]:
    """The scorer of one model file in the typed format, with its file of answers."""
    digest = sha256_of(model)
    scorer = rerank.LanguageModel(program, model, threads, no_context=False, prompt_format=harness_trace.PROMPT_FORMAT)
    stored = StoredAnswers(scorer.process, answers, digest)
    scorer.process = stored
    return scorer, stored, digest

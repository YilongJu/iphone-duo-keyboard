"""Types the replay documents in order through the keyboard's typing rules and the keyboard's
scorer with one reuse mode of the cache, and records every request, every correction and the
field texts. docs/kv-reuse-design.md defines the replay and the counts.

The typing rules are the Python copy of the keyboard in scripts/lm-rerank/rerank.py
(type_case, choose, language_model_prompt). scripts/lm-keyboard/README.md shows that this copy
builds the same requests as the keyboard's Swift code (LanguageModelPrompt.make and makeStock) in
14,626 of 14,626 corrections. Unlike the harness of scripts/lm-keyboard, this replay keeps no
table of earlier answers: each correction asks the scorer, as the keyboard does, in the order of
the keyboard. A correction asks for the typed prompt, and for the stock prompt of the apostrophe
step when the choice has a twin (RerankRule.choose in Shared/EnglishReranking.swift).

Outputs in --out:
    requests.tsv      every request in order, in the request format of lm_score.c
    requests.meta     per request: document, correction index, prompt kind
    corrections.jsonl per correction: document, index, readings, request numbers, choice
    outputs.jsonl     the field text of each document
    times.txt         the times of kv_replay, one line per request
    result.json       the counts of the documents

Usage, from the repository root, on Linux:
    python3 scripts/kv-reuse/replay.py --shim SHIM.so --program kv_replay --model MODEL.gguf \
        --mode prefix --slots 1 --everyday build/lm-domain/data/everyday --out OUT [--check TOLERANCE]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-keyboard"))
import harness_trace  # noqa: E402
import rerank  # noqa: E402

# The setting of the shipped file and the prompt format of the keyboard.
SETTING = harness_trace.TUNED
PROMPT_FORMAT = harness_trace.PROMPT_FORMAT
# Sentences of a stream per field of running text.
SENTENCES_PER_FIELD = 10
STREAM_CASES = ROOT / "scripts" / "typing-evaluation" / "cases" / "english-domain-stream.dev.jsonl"


def running_text(sentences: list[str]) -> str:
    """The sentences as one text of a field: each sentence gets a capital first letter, as the
    keyboard types it after the end of a sentence, and a period and a space after it unless it
    already ends with a mark that ends a sentence."""
    parts = []
    for sentence in sentences:
        text = sentence.strip()
        text = text[0].upper() + text[1:]
        parts.append(text if text[-1] in ".!?" else text + ".")
    return " ".join(parts)


def load_documents(everyday: Path) -> list[dict]:
    """The documents of the replay, in order. Each is {"id", "part", "case"}; a case has the
    fields that rerank.type_case reads."""
    documents = []
    for case in rerank.load_cases(rerank.CASE_FILES):
        documents.append({"id": case["id"], "part": "dev", "case": case})
    for case in rerank.load_cases([rerank.DOMAIN_CASES]):
        documents.append({"id": case["id"], "part": "work area dev", "case": case})
    everyday_cases = rerank.load_cases([everyday / "cases.stream.select.jsonl"])
    stream_cases = rerank.load_cases([STREAM_CASES])
    streams = [("everyday stream", everyday_cases),
               ("technical stream", [c for c in stream_cases if c["stream"] == "technical"]),
               ("written stream", [c for c in stream_cases if c["stream"] == "written"])]
    for part, cases in streams:
        if any(case["context"] for case in cases):
            raise SystemExit(f"a case of the {part} has a context")
        for start in range(0, len(cases), SENTENCES_PER_FIELD):
            group = cases[start:start + SENTENCES_PER_FIELD]
            text = running_text([case["typed"] for case in group])
            intended = running_text([case["intended"] for case in group])
            identifier = f"{part.split()[0]}-field-{start // SENTENCES_PER_FIELD:04d}"
            documents.append({"id": identifier, "part": part,
                              "case": {"id": identifier, "context": "", "typed": text, "intended": intended}})
    return documents


class Scorer:
    """kv_replay behind the two methods that rerank.choose calls. Every call sends one request."""

    def __init__(self, program: Path, model: Path, threads: int, mode: str, slots: int, check: str | None, out: Path):
        command = [str(program), str(model), str(threads), mode, str(slots), "17", "times", str(out / "times.txt")]
        if check is not None:
            command += ["check", check]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8")
        ready = self.process.stdout.readline()
        if not ready.startswith("ready"):
            raise SystemExit(f"kv_replay did not start: {ready!r} {self.process.stderr.read()}")
        self.requests = (out / "requests.tsv").open("w", encoding="utf-8")
        self.meta = (out / "requests.meta").open("w", encoding="utf-8")
        self.count = 0
        self.document = ""
        self.correction = -1
        # The request numbers of the current correction.
        self.asked: dict[str, int] = {}

    def ask(self, kind: str, lm_context: str, candidates: list[str]) -> list[tuple[float, float]]:
        line = "\t".join([lm_context, *candidates])
        if "\n" in line or line.count("\t") != len(candidates):
            raise SystemExit(f"a text holds a tab or a line break: {line!r}")
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()
        answer = self.process.stdout.readline()
        fields = answer.rstrip("\n").split("\t")
        if len(fields) != len(candidates):
            raise SystemExit(f"kv_replay answered {answer!r} to {line!r}: {self.process.stderr.read()}")
        self.requests.write(line + "\n")
        self.meta.write(f"{self.document}\t{self.correction}\t{kind}\n")
        self.asked[kind] = self.count
        self.count += 1
        return [tuple(float(value) for value in field.split(" ")) for field in fields]

    def reading_scores(self, context: str, readings: list[dict], typed: str) -> dict[str, tuple[float, float]]:
        opens_field = not context
        texts = [reading["text"] for reading in readings]
        values = self.ask("typed", rerank.language_model_prompt(context, typed, PROMPT_FORMAT),
                          [rerank.language_model_text(text, opens_field) for text in texts])
        return dict(zip(texts, values))

    def step_scores(self, context: str, texts: list[str], prompt: str) -> dict[str, tuple[float, float]]:
        if prompt != "stock":
            raise SystemExit(f"the keyboard's step reads the stock prompt, not {prompt!r}")
        opens_field = not context
        values = self.ask("stock", rerank.language_model_prompt(context, None, "stock"),
                          [rerank.language_model_text(text, opens_field) for text in texts])
        return dict(zip(texts, values))

    def close(self) -> str:
        self.process.stdin.close()
        report = self.process.stderr.read()
        code = self.process.wait()
        self.requests.close()
        self.meta.close()
        if code != 0:
            raise SystemExit(f"kv_replay ended with {code}: {report}")
        return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--threads", type=int, required=True)
    parser.add_argument("--mode", choices=("none", "prefix", "shift", "anchor"), required=True)
    parser.add_argument("--slots", type=int, choices=(1, 2), required=True)
    parser.add_argument("--check", help="tolerance of the check of the cache, a number or inf")
    parser.add_argument("--everyday", type=Path, required=True, help="the folder of cases.stream.select.jsonl")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--every", type=int, default=1, help="types every n-th document only, for a smoke test")
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)

    documents = load_documents(arguments.everyday)
    documents = documents[::arguments.every]
    engine = rerank.Engine(arguments.shim, rerank.LEXICON, rerank.SUPPLEMENT, use_supplement=True)
    capitals = rerank.PreferredCapitals(rerank.CAPITALS_TABLE)
    scorer = Scorer(arguments.program, arguments.model, arguments.threads, arguments.mode, arguments.slots,
                    arguments.check, arguments.out)
    corrections = (arguments.out / "corrections.jsonl").open("w", encoding="utf-8")
    outputs = {}
    bars = 0
    for document in documents:
        scorer.document = document["id"]
        scorer.correction = -1

        def chooser(readings, text_before, typed):
            nonlocal bars
            context = text_before.rstrip(" ")
            if len(readings) < 2:
                return rerank.engine_choice(readings, text_before)
            # The keyboard asks no question when the text holds a bar (LanguageModelPrompt.make).
            if "|" in context or "|" in typed:
                bars += 1
                return rerank.engine_choice(readings, text_before)
            scorer.correction += 1
            scorer.asked = {}
            choice = rerank.choose(readings, context, SETTING, scorer, typed)
            corrections.write(json.dumps({
                "document": document["id"], "index": scorer.correction, "context": context, "typed": typed,
                "readings": readings, "typed_request": scorer.asked["typed"], "stock_request": scorer.asked.get("stock"),
                "choice": choice}) + "\n")
            return choice

        outputs[document["id"]] = rerank.type_case(document["case"], engine, chooser, capitals, keep_capitals=True)
    corrections.close()
    report = scorer.close()
    with (arguments.out / "outputs.jsonl").open("w", encoding="utf-8") as file:
        for document in documents:
            file.write(json.dumps({"id": document["id"], "part": document["part"], "output": outputs[document["id"]]}) + "\n")

    existing = [d["case"] for d in documents if d["part"] == "dev"]
    domain = [d["case"] for d in documents if d["part"] == "work area dev"]
    result = {
        "mode": arguments.mode, "slots": arguments.slots, "check": arguments.check, "requests": scorer.count,
        "corrections_with_a_bar": bars,
        "documents": {part: sum(1 for d in documents if d["part"] == part) for part in dict.fromkeys(d["part"] for d in documents)},
        "dev": rerank.summarize(existing, outputs), "work_area": rerank.tally_by_group(domain, outputs),
        "kv_replay": report.strip(),
    }
    (arguments.out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"requests": scorer.count, "dev": result["dev"]["right"], "work_area": result["work_area"]["right"]}))


if __name__ == "__main__":
    main()

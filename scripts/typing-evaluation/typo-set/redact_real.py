"""Removes the texts of the real-data cases from a folder of outputs before a workflow uploads it.

The Aalto and CSCD-NS licences do not allow redistribution, and the artifacts of a public
repository are public. So no artifact may hold their sentences, their typed words or the outputs
of the keyboard on them. For each file of english-typos-aalto and pinyin-typos-cscd in the
folder, this script:

1. checks every correction of a trace (`NAME.HALF.trace.jsonl`) against the tuned rule on that
   run's own numbers, as compare_typos.py does for the generated cases, and writes the counts to
   `NAME.HALF.rule-check.json`. The script stops with exit code 1 when a choice is not the rule's
   choice.
2. replaces the trace with `NAME.HALF.trace-choices.jsonl`: the case id, the step, and the
   SHA-256 value of the choice.
3. replaces each file of outputs (`id` and `output` on each line) with the case id and the
   SHA-256 value of the output after the scorer's normalization (`normalized_output_sha256`).
4. deletes `requests-real.tsv`, the language-model requests of the real-data cases.

Then it reads every file of the folder that belongs to no generated case file, and stops with
exit code 1 when one holds the context, the typed text or the intended text of a real-data case,
so a new output file cannot carry the texts by mistake. The check reads an English text of 4
words or more, a Chinese text of 8 characters or more, and typed Pinyin of 20 letters or more. A shorter text, as "don't want to",
is in any English text. A text that a case file of scripts/typing-evaluation/cases also holds
is public there, and the check skips it. A line that names a real-data case id may
hold the id, the step and SHA-256 values only.

Usage:
    python3 scripts/typing-evaluation/typo-set/redact_real.py --folder DIR --cases DIR
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-keyboard"))
import compare  # noqa: E402
from score import normalize  # noqa: E402

REAL = {"english-typos-aalto": "english", "pinyin-typos-cscd": "pinyin"}
GENERATED_PREFIXES = ("english-typos.", "english-typos-capitals.", "pinyin-typos.")
REAL_ID_PREFIXES = ("enaalto-", "zhcscd-")
REDACTED_FIELDS = {"id", "step", "normalized_output_sha256", "choice_sha256"}
SHORTEST_CHECKED_WORDS = 4
SHORTEST_CHECKED_CHINESE = 8
SHORTEST_CHECKED_PINYIN_LETTERS = 20
PUBLIC_CASES = ROOT / "scripts" / "typing-evaluation" / "cases"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def real_name(path: Path) -> str | None:
    for name in REAL:
        if path.name.startswith(name + "."):
            return name
    return None


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True, help="the folder of the real-data case files")
    arguments = parser.parse_args()
    folder = arguments.folder
    mismatched = 0
    for path in sorted(folder.iterdir()):
        name = real_name(path)
        if name is None or not path.is_file():
            continue
        if path.name.endswith(".trace.jsonl"):
            entries = read_jsonl(path)
            mismatches = sum(1 for e in entries if e["result"] == "scores" and compare.recorded_choice(e) != e["choice"])
            mismatched += mismatches
            stem = path.name[:-len(".trace.jsonl")]
            (folder / f"{stem}.rule-check.json").write_text(
                json.dumps({"corrections": len(entries), "rule_mismatches": mismatches}, indent=1) + "\n", encoding="utf-8")
            write_jsonl(folder / f"{stem}.trace-choices.jsonl",
                        [{"id": e["id"], "step": e["step"], "choice_sha256": sha256(e["choice"])} for e in entries])
            path.unlink()
        elif path.name.endswith(".jsonl") and not path.name.endswith(".trace-choices.jsonl"):
            rows = read_jsonl(path)
            if rows and "output" not in rows[0]:
                raise SystemExit(f"{path} is no file of outputs")
            write_jsonl(path, [{"id": r["id"], "normalized_output_sha256": sha256(normalize(REAL[name], r["output"]))}
                               for r in rows])
    real_requests = folder / "requests-real.tsv"
    if real_requests.exists():
        real_requests.unlink()

    public = "".join(path.read_text(encoding="utf-8") for path in sorted(PUBLIC_CASES.glob("*.jsonl")))
    texts = set()
    for name in REAL:
        for path in arguments.cases.glob(f"{name}.*.jsonl"):
            for case in read_jsonl(path):
                for field in ("context", "typed", "intended"):
                    text = case[field]
                    if REAL[name] == "english":
                        long_enough = len(text.split()) >= SHORTEST_CHECKED_WORDS
                    elif field == "typed":
                        long_enough = len(text) >= SHORTEST_CHECKED_PINYIN_LETTERS
                    else:
                        long_enough = len(text) >= SHORTEST_CHECKED_CHINESE
                    if long_enough and text not in public and json.dumps(text)[1:-1] not in public:
                        texts.add(text)
                        # JSON can write a text with \u escapes.
                        texts.add(json.dumps(case[field])[1:-1])
    if not texts:
        raise SystemExit(f"no real-data case file in {arguments.cases}")
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        if path.name.startswith(GENERATED_PREFIXES):
            continue
        content = path.read_bytes().decode("utf-8", errors="replace")
        # A row of a real-data case may hold its id, its step and SHA-256 values only.
        for line in content.splitlines():
            if any(f'"{prefix}' in line for prefix in REAL_ID_PREFIXES):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    raise SystemExit(f"{path} names a real-data case outside a row of JSON")
                if not isinstance(row, dict) or set(row) - REDACTED_FIELDS:
                    raise SystemExit(f"{path} holds a real-data case with fields {sorted(set(row) - REDACTED_FIELDS)}")
        found = next((text for text in texts if text in content), None)
        if found is not None:
            raise SystemExit(f"{path} holds the text of a real-data case")
    print(f"{folder}: real-data texts removed, {len(texts)} texts checked")
    if mismatched:
        raise SystemExit(f"{mismatched} recorded choices of the real-data traces are not the rule's choice")


if __name__ == "__main__":
    main()

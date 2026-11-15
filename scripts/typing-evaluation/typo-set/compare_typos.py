"""Compares two runs of the typo set case by case, as scripts/lm-keyboard/compare.py compares
the other dev cases: a folder of run_typos.py (the Linux or macOS harness) and a folder of
Tests/TypingEvaluationTests.swift (the keyboard's own code).

For each English file of the typo set and for each run kind (engine only, with the model) the
script counts the cases whose outputs differ after the scorer's normalization. It matches the
corrections that went to the model by case and place, counts those with the same choice, and
checks that each run's recorded choice is the tuned rule's choice on that run's own numbers.

The real-data files hold no texts in a workflow artifact (redact_real.py): their outputs are
SHA-256 values of the normalized outputs, their traces hold the SHA-256 value of each choice,
and the rule check of their traces comes from the `rule-check.json` files that redact_real.py
wrote on the machine of the run. The comparison of SHA-256 values gives the same counts as a
comparison of the texts.

The Pinyin outputs of the keyboard (`PinyinEngine.candidates`, which adds its own dictionary
reading) and of the C engine are compared too, as a report only, because the two engines read
other dictionaries.

--strict stops with exit code 1 when an English output differs or a recorded choice is not the
rule's choice. --strict-engine-only does the same for the outputs of the engine alone only, for
two machines where llama.cpp computes other last digits.

Usage:
    python3 scripts/typing-evaluation/typo-set/compare_typos.py --reference DIR --reference-name NAME \
        --other DIR --other-name NAME --half dev --out DIR [--strict | --strict-engine-only]
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

FILES = ["english-typos", "english-typos-capitals", "english-typos-aalto"]
PINYIN_FILES = ["pinyin-typos", "pinyin-typos-cscd"]
REAL = {"english-typos-aalto", "pinyin-typos-cscd"}
KINDS = {"engine only": ".engine-only.jsonl", "with the model": ".jsonl"}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def outputs(path: Path, task: str) -> dict[str, str]:
    """The SHA-256 value of each case's normalized output, from a file of outputs or a file that
    redact_real.py wrote."""
    result = {}
    for row in compare.read_jsonl(path):
        if row["id"] in result:
            raise SystemExit(f"{row['id']} appears twice in {path}")
        result[row["id"]] = row["normalized_output_sha256"] if "output" not in row else sha256(normalize(task, row["output"]))
    return result


def choices(folder: Path, name: str, half: str, label: str) -> tuple[dict, int]:
    """The SHA-256 value of each choice by (case, step), and the count of choices that are not
    the rule's choice."""
    # A real-data trace is in its full form inside the job that made it, and redacted after
    # redact_real.py. The full form gives the same SHA-256 values.
    if name in REAL and not (folder / f"{name}.{half}.trace.jsonl").exists():
        entries = compare.read_jsonl(folder / f"{name}.{half}.trace-choices.jsonl")
        check = json.loads((folder / f"{name}.{half}.rule-check.json").read_text(encoding="utf-8"))
        if check["corrections"] != len(entries):
            raise SystemExit(f"{folder}: the rule check of {name} counts other corrections than its trace")
        keyed = compare.keyed(entries, label)
        return {key: e["choice_sha256"] for key, e in keyed.items()}, check["rule_mismatches"]
    keyed = compare.keyed(compare.read_jsonl(folder / f"{name}.{half}.trace.jsonl"), label)
    mismatches = sum(1 for e in keyed.values() if e["result"] == "scores" and compare.recorded_choice(e) != e["choice"])
    return {key: sha256(e["choice"]) for key, e in keyed.items()}, mismatches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--reference-name", required=True)
    parser.add_argument("--other", type=Path, required=True)
    parser.add_argument("--other-name", required=True)
    parser.add_argument("--half", choices=["dev", "test"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    strictness = parser.add_mutually_exclusive_group()
    strictness.add_argument("--strict", action="store_true")
    strictness.add_argument("--strict-engine-only", action="store_true")
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)
    half = arguments.half
    failed = False
    differences = {"cases": [], "choices": [], "pinyin cases": []}
    lines = [f"# Typo set: {arguments.other_name} against {arguments.reference_name}, {half} half", "",
             "Table 1. English cases whose outputs differ after normalization, and corrections that went to the model.", "",
             "| File | Run | Cases | Outputs differ | Corrections in both runs | Same choice | Only in one run | Rule mismatches |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name in FILES:
        traces, mismatches = {}, 0
        for label, folder in ((arguments.reference_name, arguments.reference), (arguments.other_name, arguments.other)):
            traces[label], count = choices(folder, name, half, label)
            mismatches += count
        a, b = traces[arguments.reference_name], traces[arguments.other_name]
        shared = set(a) & set(b)
        same_choice = sum(1 for key in shared if a[key] == b[key])
        differences["choices"] += [{"file": name, "id": key[0], "step": key[1]} for key in sorted(shared) if a[key] != b[key]]
        for kind, suffix in KINDS.items():
            ref = outputs(arguments.reference / f"{name}.{half}{suffix}", "english")
            oth = outputs(arguments.other / f"{name}.{half}{suffix}", "english")
            if set(ref) != set(oth):
                raise SystemExit(f"{name} {kind}: the two runs hold other cases")
            differ = [case_id for case_id in ref if ref[case_id] != oth[case_id]]
            differences["cases"] += [{"file": name, "run": kind, "id": case_id} for case_id in differ]
            if arguments.strict or (arguments.strict_engine_only and kind == "engine only"):
                failed |= bool(differ)
            trace_cells = (f"{len(shared)} | {same_choice} | {len(set(a) ^ set(b))} | {mismatches}"
                           if kind == "with the model" else "- | - | - | -")
            lines.append(f"| {name} | {kind} | {len(ref)} | {len(differ)} | {trace_cells} |")
        if arguments.strict:
            failed |= mismatches > 0
    lines += ["", "Table 2. Pinyin cases whose outputs differ. Report only: the keyboard adds its own dictionary reading.", "",
              "| File | Cases | Outputs differ |", "| --- | --- | --- |"]
    for name in PINYIN_FILES:
        # The harness writes the C engine's Pinyin outputs as engine-only files, and the keyboard
        # writes its own as plain output files.
        sides = []
        for folder in (arguments.reference, arguments.other):
            for suffix in (".engine-only.jsonl", ".jsonl"):
                path = folder / f"{name}.{half}{suffix}"
                if path.exists():
                    sides.append(outputs(path, "pinyin"))
                    break
            else:
                raise SystemExit(f"{folder} holds no Pinyin outputs of {name}")
        ref, oth = sides
        if set(ref) != set(oth):
            raise SystemExit(f"{name}: the two runs hold other cases")
        differ = [case_id for case_id in ref if ref[case_id] != oth[case_id]]
        differences["pinyin cases"] += [{"file": name, "id": case_id} for case_id in differ]
        lines.append(f"| {name} | {len(ref)} | {len(differ)} |")
    text = "\n".join(lines) + "\n"
    (arguments.out / "report.md").write_text(text, encoding="utf-8")
    (arguments.out / "differences.json").write_text(json.dumps(differences, indent=1), encoding="utf-8")
    print(text)
    if failed:
        print("At least one check failed. differences.json gives each difference by case id.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

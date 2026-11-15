"""Compares two runs of the English typo set case by case, as scripts/lm-keyboard/compare.py
compares the other dev cases: a folder of run_typos.py with the model (the Linux or macOS
harness) and a folder of Tests/TypingEvaluationTests.swift (the keyboard's own code).

For each English file of the typo set and for each run kind (engine only, with the model) the
script counts the cases whose outputs differ after the scorer's normalization. It matches the
corrections that went to the model by case and place, counts those with the same choice, and
checks that each run's recorded choice is the tuned rule's choice on that run's own numbers.

With --strict the script stops with exit code 1 when an output differs or a recorded choice is
not the rule's choice. The workflow gives --strict to the comparison of the keyboard with the
harness on the same machine, as compare.py does.

Usage:
    python3 scripts/typing-evaluation/typo-set/compare_typos.py --reference DIR --reference-name NAME \
        --other DIR --other-name NAME --half dev --out DIR [--strict]
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-keyboard"))
import compare  # noqa: E402
from score import normalize  # noqa: E402

FILES = ["english-typos", "english-typos-aalto"]
KINDS = {"engine only": ".engine-only.jsonl", "with the model": ".jsonl"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--reference-name", required=True)
    parser.add_argument("--other", type=Path, required=True)
    parser.add_argument("--other-name", required=True)
    parser.add_argument("--half", choices=["dev", "test"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)
    half = arguments.half
    failed = False
    differences = {"cases": [], "rule mismatches": [], "choices": []}
    lines = [f"# Typo set: {arguments.other_name} against {arguments.reference_name}, {half} half", "",
             "Table 1. Cases whose outputs differ after normalization, and corrections that went to the model.", "",
             "| File | Run | Cases | Outputs differ | Corrections in both runs | Same choice | Only in one run | Rule mismatches |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name in FILES:
        traces = {}
        for label, folder in ((arguments.reference_name, arguments.reference), (arguments.other_name, arguments.other)):
            traces[label] = compare.keyed(compare.read_jsonl(folder / f"{name}.{half}.trace.jsonl"), label)
        mismatches = 0
        for label, trace in traces.items():
            for key, entry in trace.items():
                if entry["result"] != "scores":
                    continue
                rule = compare.recorded_choice(entry)
                if rule != entry["choice"]:
                    mismatches += 1
                    differences["rule mismatches"].append({"run": label, "file": name, "id": key[0], "step": key[1],
                                                           "choice": entry["choice"], "rule": rule})
        a, b = traces[arguments.reference_name], traces[arguments.other_name]
        shared = set(a) & set(b)
        same_choice = sum(1 for key in shared if a[key]["choice"] == b[key]["choice"])
        for key in sorted(shared):
            if a[key]["choice"] != b[key]["choice"]:
                differences["choices"].append({"file": name, "id": key[0], "step": key[1],
                                               arguments.reference_name: a[key]["choice"], arguments.other_name: b[key]["choice"]})
        for kind, suffix in KINDS.items():
            ref = compare.predictions([arguments.reference / f"{name}.{half}{suffix}"])
            oth = compare.predictions([arguments.other / f"{name}.{half}{suffix}"])
            if set(ref) != set(oth):
                raise SystemExit(f"{name} {kind}: the two runs hold other cases")
            differ = [case_id for case_id in ref if normalize("english", ref[case_id]) != normalize("english", oth[case_id])]
            differences["cases"] += [{"file": name, "run": kind, "id": case_id, arguments.reference_name: ref[case_id],
                                      arguments.other_name: oth[case_id]} for case_id in differ]
            failed |= bool(differ)
            trace_cells = (f"{len(shared)} | {same_choice} | {len(set(a) ^ set(b))} | {mismatches}"
                           if kind == "with the model" else "- | - | - | -")
            lines.append(f"| {name} | {kind} | {len(ref)} | {len(differ)} | {trace_cells} |")
        failed |= mismatches > 0
    text = "\n".join(lines) + "\n"
    (arguments.out / "report.md").write_text(text, encoding="utf-8")
    (arguments.out / "differences.json").write_text(json.dumps(differences, indent=1), encoding="utf-8")
    print(text)
    if failed and arguments.strict:
        print("At least one check failed. differences.json gives each difference.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

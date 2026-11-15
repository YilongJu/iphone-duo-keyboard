"""Checks case by case that a workflow run gives the same outputs as a reference run, for every
output file that both runs hold. The typo set adds new reports to the workflows "Typing
evaluation" and "Language model in the keyboard". This check shows that the existing outputs
stay as they are.

The two folders hold the downloaded artifacts of the two runs, one folder per artifact
(`gh run download RUN_ID -D FOLDER`). For each file that both folders hold:
- a file of outputs (`*.jsonl` with `id` and `output` on each line): the outputs of each case,
- a trace (`*.trace.jsonl` and `trace.*.jsonl`): each correction without its time in milliseconds,
- a summary (`*.summary.json`): the whole file,
- any other file, as the check of the scorer (`scorer-check.txt`): every byte.
Files that hold times, memory or machine names are not compared, and the report names them: logs,
`runner.txt`, `*.reranker.txt`, `result.json`, `language-model-test-simulator.txt`, and the
`report.md` and `differences.json` of scripts/lm-keyboard/compare.py, which repeat the keyboard's
time and memory of each run and the milliseconds of each correction.

The script stops with exit code 1 when a compared file differs, or when a file of the reference
is missing from the other run. `--allow-differ PATTERN` names files (by their path in the
folder, with `*` for any text) whose differences the report counts but which do not stop the
script, as the files of the x86 harness: llama.cpp computes other last digits on another
processor.

Usage:
    python3 scripts/typing-evaluation/typo-set/check_unchanged.py --reference DIR --other DIR --out REPORT.md \
        [--allow-differ PATTERN ...]
"""
import argparse
import fnmatch
import json
from pathlib import Path

NOT_COMPARED = {"runner.txt", "result.json", "language-model-test-simulator.txt", "report.md", "differences.json"}


def outputs(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            result[row["id"]] = row["output"]
    return result


def trace(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            row.pop("milliseconds", None)
            rows.append(row)
    return rows


def compare_file(a: Path, b: Path) -> tuple[str, str]:
    name = a.name
    if name in NOT_COMPARED or name.endswith((".log", ".reranker.txt")):
        return "not compared", "holds times or machine names"
    if name.endswith(".trace.jsonl") or name.startswith("trace."):
        ta, tb = trace(a), trace(b)
        differ = sum(1 for x, y in zip(ta, tb) if x != y) + abs(len(ta) - len(tb))
        return ("same" if differ == 0 else "differs"), f"{len(ta)} corrections, {differ} differ"
    if name.endswith(".jsonl"):
        oa, ob = outputs(a), outputs(b)
        if set(oa) != set(ob):
            return "differs", f"other cases: {len(set(oa) ^ set(ob))} ids in one run only"
        differ = sum(1 for key in oa if oa[key] != ob[key])
        return ("same" if differ == 0 else "differs"), f"{len(oa)} cases, {differ} outputs differ"
    if name.endswith(".summary.json"):
        same = json.loads(a.read_text(encoding="utf-8")) == json.loads(b.read_text(encoding="utf-8"))
        return ("same" if same else "differs"), "whole file"
    same = a.read_bytes() == b.read_bytes()
    return ("same" if same else "differs"), f"{a.stat().st_size} bytes"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--other", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-differ", action="append", default=[])
    arguments = parser.parse_args()
    ref = {p.relative_to(arguments.reference).as_posix(): p for p in arguments.reference.rglob("*") if p.is_file()}
    oth = {p.relative_to(arguments.other).as_posix(): p for p in arguments.other.rglob("*") if p.is_file()}
    lines = [f"Reference {arguments.reference.name}, other {arguments.other.name}.", "",
             "| File | Result | Detail |", "| --- | --- | --- |"]
    counts = {"same": 0, "differs": 0, "differs, allowed": 0, "not compared": 0}
    for key in sorted(set(ref) & set(oth)):
        result, detail = compare_file(ref[key], oth[key])
        if result == "differs" and any(fnmatch.fnmatch(key, pattern) for pattern in arguments.allow_differ):
            result = "differs, allowed"
        counts[result] += 1
        lines.append(f"| {key} | {result} | {detail} |")
    missing = sorted(set(ref) - set(oth))
    lines += ["", f"Files in both runs: same {counts['same']}, differ {counts['differs']}, "
              f"differ where allowed {counts['differs, allowed']}, not compared {counts['not compared']}.",
              f"Files only in the reference: {missing or 'none'}.",
              f"Files only in the other run: {len(set(oth) - set(ref))}."]
    text = "\n".join(lines) + "\n"
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(text, encoding="utf-8")
    print(text)
    if counts["differs"] or missing:
        raise SystemExit(f"{counts['differs']} files differ, and {len(missing)} files of the reference are missing")


if __name__ == "__main__":
    main()

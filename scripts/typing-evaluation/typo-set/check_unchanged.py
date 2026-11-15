"""Checks case by case that a workflow run gives the same outputs as a reference run, for every
output file that both runs hold. The typo set adds new reports to the workflows "Typing
evaluation" and "Language model in the keyboard". This check shows that the existing outputs
stay as they are.

The two folders hold the downloaded artifacts of the two runs, one folder per artifact
(`gh run download RUN_ID -D FOLDER`). For each file that both folders hold:
- a file of outputs (`*.jsonl` with `id` and `output` on each line): the outputs of each case,
- a trace (`*.trace.jsonl`): each correction without its time in milliseconds,
- a summary (`*.summary.json`): the whole file,
- a list of requests or answers (`requests.tsv`, `*.answers`): every byte.
Files that hold times or machine names (logs, `runner.txt`, `*.reranker.txt`, `result.json`,
`report.md`, `differences.json`, `scorer-check.txt`) are not compared, and the report names them.

The script stops with exit code 1 when a compared file differs.

Usage:
    python3 scripts/typing-evaluation/typo-set/check_unchanged.py --reference DIR --other DIR --out REPORT.md
"""
import argparse
import json
from pathlib import Path

NOT_COMPARED = {"runner.txt", "result.json", "report.md", "differences.json", "scorer-check.txt"}


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
    if name.endswith(".trace.jsonl"):
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
    arguments = parser.parse_args()
    ref = {p.relative_to(arguments.reference).as_posix(): p for p in arguments.reference.rglob("*") if p.is_file()}
    oth = {p.relative_to(arguments.other).as_posix(): p for p in arguments.other.rglob("*") if p.is_file()}
    lines = [f"Reference {arguments.reference.name}, other {arguments.other.name}.", "",
             "| File | Result | Detail |", "| --- | --- | --- |"]
    counts = {"same": 0, "differs": 0, "not compared": 0}
    for key in sorted(set(ref) & set(oth)):
        result, detail = compare_file(ref[key], oth[key])
        counts[result] += 1
        lines.append(f"| {key} | {result} | {detail} |")
    lines += ["", f"Files in both runs: same {counts['same']}, differ {counts['differs']}, not compared {counts['not compared']}.",
              f"Files only in the reference: {sorted(set(ref) - set(oth)) or 'none'}.",
              f"Files only in the other run: {len(set(oth) - set(ref))}."]
    text = "\n".join(lines) + "\n"
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(text, encoding="utf-8")
    print(text)
    if counts["differs"]:
        raise SystemExit(f"{counts['differs']} files differ")


if __name__ == "__main__":
    main()

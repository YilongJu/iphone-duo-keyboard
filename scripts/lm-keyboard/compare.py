"""Compares the keyboard's own code on the macOS simulator with the Linux harness of
scripts/lm-rerank, on the dev half only: the right cases per group, the output of every case,
and every correction that went to the language model.

Inputs:
    --harness DIR   the outputs of harness_trace.py, and scorer-check.txt of the workflow
    --keyboard DIR  the outputs of Tests/TypingEvaluationTests.swift with TYPING_HALVES=dev
Outputs in --out:
    report.md          the tables, also written to standard output
    differences.json   every case and every correction that differs, with both sides' numbers

The script stops with exit code 1 when the outputs of any case differ after the scorer's
normalization (letter case and a curly apostrophe), so a workflow run turns red.

Usage, from the repository root:
    python3 scripts/lm-keyboard/compare.py --harness build/lm-keyboard/harness \
        --keyboard build/lm-keyboard/keyboard --out build/lm-keyboard/compare
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import rerank  # noqa: E402
from score import normalize  # noqa: E402

TUNED = {"weight": 1.0, "margin_from_typed": 24.0, "margin_to_typed": 0.0, "margin_other": 2.0, "space_after": True}
GROUPS = ["clean", "letter_slips", "space_slips", "symbol_slips", "clean_symbols"]
TASKS = ["english", "english-symbols"]


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def predictions(paths: list[Path]) -> dict[str, str]:
    result = {}
    for path in paths:
        for row in read_jsonl(path):
            if row["id"] in result:
                raise SystemExit(f"{row['id']} appears twice in {paths}")
            result[row["id"]] = row["output"]
    return result


def as_float(value) -> float:
    # The keyboard writes an infinite number as the text "inf" or "-inf", which float() reads.
    return float(value)


def decision(entry: dict) -> dict:
    """The tuned rule on one side's numbers: the combined scores, the winner, and the slack, the
    distance of the deciding difference from its threshold."""
    readings = entry["readings"]
    combined = [r["engine_score"] + TUNED["weight"] * (as_float(r["log_probability"]) + as_float(r["space_after"]))
                for r in readings]
    chosen = next(i for i, r in enumerate(readings) if r["chosen"])
    best = 0
    for index in range(1, len(readings)):
        if combined[index] > combined[best]:
            best = index
    if best == chosen:
        others = [c for i, c in enumerate(combined) if i != chosen]
        # The engine's choice leads; the slack is its lead over the next reading.
        return {"winner": readings[chosen]["text"], "slack": combined[chosen] - max(others), "kind": "engine choice leads"}
    if readings[chosen]["as_typed"]:
        margin = TUNED["margin_from_typed"]
    elif readings[best]["as_typed"]:
        margin = TUNED["margin_to_typed"]
    else:
        margin = TUNED["margin_other"]
    lead = combined[best] - combined[chosen]
    winner = readings[best]["text"] if lead >= margin else readings[chosen]["text"]
    return {"winner": winner, "slack": lead - margin, "kind": "margin"}


def summary_row(summary: dict) -> list[str]:
    return [f"{summary['groups'][g]['right']}/{summary['groups'][g]['cases']}" for g in GROUPS] + [
        f"{summary['right']}/{summary['cases']}"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--keyboard", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)

    # Only the dev half. A test-half file in the keyboard folder stops the script unread.
    test_files = sorted(p.name for p in arguments.keyboard.iterdir() if ".test." in p.name)
    if test_files:
        raise SystemExit(f"the keyboard folder holds test-half files, which this script does not read: {test_files}")
    cases = rerank.load_cases(rerank.CASE_FILES)
    if any(case["split"] != "dev" for case in cases):
        raise SystemExit("a case outside the dev half")
    by_id = {case["id"]: case for case in cases}

    runs = {
        "harness control": predictions([arguments.harness / "control.dev.jsonl"]),
        "keyboard, engine only": predictions([arguments.keyboard / f"{t}.dev.engine-only.jsonl" for t in TASKS]),
        "harness re-ranked": predictions([arguments.harness / "reranked.dev.jsonl"]),
        "keyboard with the model": predictions([arguments.keyboard / f"{t}.dev.jsonl" for t in TASKS]),
    }
    for name, values in runs.items():
        if set(values) != set(by_id):
            raise SystemExit(f"{name} does not hold exactly the {len(by_id)} dev cases")
    summaries = {name: rerank.summarize(cases, values) for name, values in runs.items()}

    lines = ["# Keyboard code against the Linux harness on the dev half", ""]
    lines += ["Table 1. Right dev cases per group.", "",
              "| Run | " + " | ".join(GROUPS) + " | all dev cases |",
              "| --- |" + " --- |" * (len(GROUPS) + 1)]
    for name, summary in summaries.items():
        lines.append(f"| {name} | " + " | ".join(summary_row(summary)) + " |")
    lines.append("")

    differences = {"cases": [], "corrections": []}
    failed = False
    lines += ["Table 2. Cases whose outputs differ between the two sides.", "",
              "| Pair | differ after normalization | differ in letter case only |", "| --- | --- | --- |"]
    for harness_name, keyboard_name in [("harness control", "keyboard, engine only"),
                                        ("harness re-ranked", "keyboard with the model")]:
        normalized, case_only = [], 0
        for case_id in by_id:
            a, b = runs[harness_name][case_id], runs[keyboard_name][case_id]
            if normalize("english", a) != normalize("english", b):
                normalized.append(case_id)
                differences["cases"].append({"pair": f"{harness_name} / {keyboard_name}", "id": case_id,
                                             "harness": a, "keyboard": b, "intended": by_id[case_id]["intended"]})
            elif a != b:
                case_only += 1
        failed |= bool(normalized)
        lines.append(f"| {harness_name} / {keyboard_name} | {len(normalized)} | {case_only} |")
    lines.append("")

    # Correction by correction.
    harness_trace = {(e["id"], e["step"]): e for e in read_jsonl(arguments.harness / "trace.dev.jsonl")}
    keyboard_trace = {}
    for task in TASKS:
        for entry in read_jsonl(arguments.keyboard / f"{task}.dev.trace.jsonl"):
            keyboard_trace[(entry["id"], entry["step"])] = entry
    shared = sorted(set(harness_trace) & set(keyboard_trace))
    counts = {"harness corrections": len(harness_trace), "keyboard corrections": len(keyboard_trace),
              "on both sides": len(shared), "same context": 0, "same readings in the same order": 0,
              "same candidates": 0, "same choice": 0, "keyboard results other than scores": 0}
    widest = {"engine score": 0.0, "log probability": 0.0, "space after": 0.0, "combined": 0.0}
    gaps = []
    for key in shared:
        h, k = harness_trace[key], keyboard_trace[key]
        if k["result"] != "scores":
            counts["keyboard results other than scores"] += 1
            continue
        counts["same context"] += h["context"] == k["context"]
        same_order = [r["text"] for r in h["readings"]] == [r["text"] for r in k["readings"]]
        counts["same readings in the same order"] += same_order
        counts["same candidates"] += sorted(r["candidate"] for r in h["readings"]) == sorted(
            r["candidate"] for r in k["readings"])
        counts["same choice"] += h["choice"] == k["choice"]
        keyboard_by_text = {r["text"]: r for r in k["readings"]}
        for r in h["readings"]:
            other = keyboard_by_text.get(r["text"])
            if other is None:
                continue
            gap_engine = abs(r["engine_score"] - other["engine_score"])
            gap_lp = abs(as_float(r["log_probability"]) - as_float(other["log_probability"]))
            gap_space = abs(as_float(r["space_after"]) - as_float(other["space_after"]))
            widest["engine score"] = max(widest["engine score"], gap_engine)
            widest["log probability"] = max(widest["log probability"], gap_lp)
            widest["space after"] = max(widest["space after"], gap_space)
            widest["combined"] = max(widest["combined"], gap_engine + gap_lp + gap_space)
            gaps.append(gap_lp)
        if h["choice"] != k["choice"] or h["context"] != k["context"] or not same_order:
            differences["corrections"].append({
                "id": key[0], "step": key[1], "harness": h, "keyboard": k,
                "harness decision": decision(h), "keyboard decision": decision(k)})
    only_harness = sorted(set(harness_trace) - set(keyboard_trace))
    only_keyboard = sorted(set(keyboard_trace) - set(harness_trace))
    counts["only in the harness"] = len(only_harness)
    counts["only in the keyboard"] = len(only_keyboard)
    differences["only in the harness"] = [list(k) for k in only_harness]
    differences["only in the keyboard"] = [list(k) for k in only_keyboard]

    lines += ["Table 3. Corrections that went to the model, matched by case and by their place in the case.", "",
              "| Count | Value |", "| --- | --- |"]
    lines += [f"| {name} | {value} |" for name, value in counts.items()]
    lines.append("")
    gaps.sort()
    lines += ["Table 4. Widest difference of a number between the two sides, over the readings of the matched "
              "corrections, in natural-log units. The harness reads the model's numbers with 5 decimals and the "
              "engine's with 6.", "", "| Number | Widest difference |", "| --- | --- |"]
    lines += [f"| {name} | {value:.6f} |" for name, value in widest.items()]
    if gaps:
        lines.append(f"| log probability, median | {gaps[len(gaps) // 2]:.6f} |")
        lines.append(f"| log probability, 99th percentile | {gaps[min(len(gaps) - 1, int(len(gaps) * 0.99))]:.6f} |")
    lines.append("")

    # Decisions of the harness that a difference of the widest size could turn.
    slacks = sorted(abs(decision(e)["slack"]) for e in harness_trace.values())
    near = sum(1 for s in slacks if s <= 2 * widest["combined"])
    lines += [f"Harness decisions whose slack is at most twice the widest combined difference "
              f"({2 * widest['combined']:.6f}): {near} of {len(slacks)}. Smallest slacks: "
              + ", ".join(f"{s:.6f}" for s in slacks[:5]) + ".", ""]

    if differences["corrections"]:
        lines += ["Table 5. Corrections whose context, readings or choice differ.", "",
                  "| Case | Step | Harness choice | Keyboard choice | Harness slack | Keyboard slack |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for row in differences["corrections"][:50]:
            lines.append(f"| {row['id']} | {row['step']} | {row['harness']['choice']} | {row['keyboard']['choice']} | "
                         f"{row['harness decision']['slack']:.6f} | {row['keyboard decision']['slack']:.6f} |")
        lines.append("")

    scorer_check = arguments.harness / "scorer-check.txt"
    if scorer_check.exists():
        lines += ["The keyboard's scorer against lm_score on the same Linux runner and the same requests:", ""]
        lines += ["    " + line for line in scorer_check.read_text(encoding="utf-8").splitlines()]
        lines.append("")
    for task in TASKS:
        report = arguments.keyboard / f"{task}.dev.reranker.txt"
        if report.exists():
            lines += [f"The keyboard's model in the simulator after {task} dev:", ""]
            lines += ["    " + line for line in report.read_text(encoding="utf-8").splitlines()]
            lines.append("")

    text = "\n".join(lines) + "\n"
    (arguments.out / "report.md").write_text(text, encoding="utf-8")
    (arguments.out / "differences.json").write_text(json.dumps(differences, indent=1), encoding="utf-8")
    print(text)
    if failed:
        print("The outputs differ in at least one case. differences.json lists each one.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

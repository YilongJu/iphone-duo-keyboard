"""Compares two runs of the dev cases with the tuned re-ranking rule: the right cases per group,
the output of every case, and every correction that went to the language model.

A run is either a folder of harness_trace.py (the Linux harness of scripts/lm-rerank) or a folder
of Tests/TypingEvaluationTests.swift with TYPING_HALVES=dev (the keyboard's own code). The script
reads the dev half only, and it stops unread when a folder holds a test-half file.

Inputs:
    --reference DIR, --reference-name NAME   the run to compare against
    --other DIR, --other-name NAME           the run to compare
    --published                              also require the reference to give the pinned numbers of
                                             PUBLISHED below
Outputs in --out:
    report.md          the tables, also written to standard output
    differences.json   every case and every correction that differs, with both runs' numbers

The script stops with exit code 1, so a workflow run turns red, when any of these holds: the
outputs of a case differ after the scorer's normalization (letter case and a curly apostrophe),
the reference does not give the published numbers (with --published), a trace holds a correction
twice, or a run's recorded choice is not the choice of the tuned rule on that run's own numbers.

Usage, from the repository root:
    python3 scripts/lm-keyboard/compare.py --reference build/lm-keyboard/harness --reference-name "x86 harness" \
        --other build/lm-keyboard/keyboard --other-name keyboard --published --out build/lm-keyboard/compare
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import rerank  # noqa: E402
from score import normalize  # noqa: E402

# The setting of the shipped file (harness_trace.py, KeyboardLanguageModel.rule,
# scripts/lm-domain/candidate.json).
TUNED = {"weight": 1.5, "margin_from_typed": 1.0, "margin_to_typed": 4.0, "margin_other": 2.0}
# The same setting with the apostrophe step, for rerank.choose.
SETTING = rerank.Setting(weight=1.5, margin_from_typed=1, margin_to_typed=4, margin_other=2, space_after=1,
                         margin_apostrophe=0.5, apostrophe_scope="next", apostrophe_score="slips",
                         apostrophe_prompt="stock")


class RecordedScores:
    """The model's numbers of one recorded correction, behind the method rerank.choose calls."""

    def __init__(self, entry: dict):
        self.scores = {r["text"]: (float(r["log_probability"]), float(r["space_after"])) for r in entry["readings"]}

        self.step = {r["text"]: (float(r["step_log_probability"]), float(r["step_space_after"]))
                     for r in entry["readings"] if r.get("step_log_probability") is not None}

    def reading_scores(self, context, readings, typed):
        return self.scores

    def step_scores(self, context, texts, prompt):
        missing = [t for t in texts if t not in self.step]
        if missing:
            raise SystemExit(f"the trace holds no step score for {missing}")
        return {t: self.step[t] for t in texts}


def recorded_choice(entry: dict) -> str:
    """The choice of rerank.choose, apostrophe step included, on one run's recorded numbers."""
    readings = [{"text": r["text"], "score": r["engine_score"], "slips": r["slip_cost"], "as_typed": r["as_typed"],
                 "chosen": r["chosen"]} for r in entry["readings"]]
    return rerank.choose(readings, "", SETTING, RecordedScores(entry), None)
GROUPS = ["clean", "letter_slips", "space_slips", "symbol_slips", "clean_symbols"]
# The x86 harness numbers of the shipped configuration: the SmolLM2 fine-tune dom-s100-seed1 in
# the typed format at the setting above, with the apostrophe step of
# docs/apostrophe-words-design.md and the work area "AI and software" of
# docs/domain-pack-design.md on. scripts/lm-keyboard/README.md names the run. Right cases per
# group, then all dev cases of english.dev.jsonl and english-symbols.dev.jsonl.
# The numbers with the model come from the ubuntu-24.04 runner of that run, an AMD EPYC 9V74
# with AVX-512. llama.cpp computes other last digits on another processor family, and the
# counts with the model can then differ by a few cases.
PUBLISHED = {"engine only": [961, 1943, 1299, 1132, 427, 6079], "with the model": [957, 2053, 1388, 1164, 429, 6539]}
TASKS = ["english", "english-symbols", "english-domain"]


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


def keyed(entries: list[dict], name: str) -> dict:
    result = {}
    for entry in entries:
        key = (entry["id"], entry["step"])
        if key in result:
            raise SystemExit(f"the trace of {name} holds {key} twice")
        result[key] = entry
    return result


def load_run(folder: Path, name: str) -> dict:
    test_files = sorted(p.name for p in folder.iterdir() if ".test." in p.name)
    if test_files:
        raise SystemExit(f"{folder} holds test-half files, which this script does not read: {test_files}")
    if (folder / "reranked.dev.jsonl").exists():
        return {"name": name, "engine only": predictions([folder / "control.dev.jsonl"]),
                "with the model": predictions([folder / "reranked.dev.jsonl"]),
                "trace": keyed(read_jsonl(folder / "trace.dev.jsonl"), name), "folder": folder}
    return {"name": name,
            "engine only": predictions([folder / f"{t}.dev.engine-only.jsonl" for t in TASKS]),
            "with the model": predictions([folder / f"{t}.dev.jsonl" for t in TASKS]),
            "trace": keyed([e for t in TASKS for e in read_jsonl(folder / f"{t}.dev.trace.jsonl")], name),
            "folder": folder}


def decision(entry: dict) -> dict:
    """The tuned rule on one run's numbers. `distance` is the smallest change of one combined
    score that turns the decision: the lead of the first maximum over the next reading, or the
    distance of the deciding lead from its margin."""
    readings = entry["readings"]
    combined = [r["engine_score"] + TUNED["weight"] * (float(r["log_probability"]) + float(r["space_after"]))
                for r in readings]
    chosen = next(i for i, r in enumerate(readings) if r["chosen"])
    best = 0
    for index in range(1, len(readings)):
        if combined[index] > combined[best]:
            best = index
    gap = combined[best] - max(c for i, c in enumerate(combined) if i != best)
    if best == chosen:
        return {"winner": readings[chosen]["text"], "distance": gap}
    if readings[chosen]["as_typed"]:
        margin = TUNED["margin_from_typed"]
    elif readings[best]["as_typed"]:
        margin = TUNED["margin_to_typed"]
    else:
        margin = TUNED["margin_other"]
    lead = combined[best] - combined[chosen]
    winner = readings[best]["text"] if lead >= margin else readings[chosen]["text"]
    return {"winner": winner, "distance": min(abs(lead - margin), gap)}


def summary_numbers(summary: dict) -> list[int]:
    return [summary["groups"][g]["right"] for g in GROUPS] + [summary["right"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--reference-name", required=True)
    parser.add_argument("--other", type=Path, required=True)
    parser.add_argument("--other-name", required=True)
    parser.add_argument("--published", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)

    # The published numbers count the cases of english.dev.jsonl and english-symbols.dev.jsonl.
    # The cases of the work area have their own table, and the case-by-case check holds all.
    cases = rerank.load_cases(rerank.CASE_FILES)
    domain = rerank.load_cases([rerank.DOMAIN_CASES])
    if any(case["split"] != "dev" for case in cases + domain):
        raise SystemExit("a case outside the dev half")
    by_id = {case["id"]: case for case in cases + domain}
    reference = load_run(arguments.reference, arguments.reference_name)
    other = load_run(arguments.other, arguments.other_name)
    for run in (reference, other):
        for kind in ("engine only", "with the model"):
            if set(run[kind]) != set(by_id):
                raise SystemExit(f"{run['name']}, {kind}, does not hold exactly the {len(by_id)} dev cases")

    failed = False
    differences = {"cases": [], "corrections": [], "rule mismatches": []}
    lines = [f"# {other['name']} against {reference['name']} on the dev half", ""]
    lines += ["Table 1. Right dev cases per group.", "", "| Run | " + " | ".join(GROUPS) + " | all dev cases |",
              "| --- |" + " --- |" * (len(GROUPS) + 1)]
    numbers = {}
    for run in (reference, other):
        for kind in ("engine only", "with the model"):
            summary = rerank.summarize(cases, run[kind])
            numbers[(run["name"], kind)] = summary_numbers(summary)
            cells = [f"{summary['groups'][g]['right']}/{summary['groups'][g]['cases']}" for g in GROUPS]
            lines.append(f"| {run['name']}, {kind} | " + " | ".join(cells) + f" | {summary['right']}/{summary['cases']} |")
    lines.append("")
    for kind, expected in PUBLISHED.items():
        got = numbers[(reference["name"], kind)]
        same = got == expected
        if arguments.published:
            failed |= not same
        lines.append(f"{reference['name']}, {kind}: {'the same as' if same else 'different from'} the published "
                     f"numbers {expected} (this run {got}).")
    lines.append("")

    domain_groups = sorted({case["group"] for case in domain})
    lines += ["Table 1b. Right dev cases of the work area per group. The group capitals counts the capitals too.", "",
              "| Run | " + " | ".join(domain_groups) + " | all |", "| --- |" + " --- |" * (len(domain_groups) + 1)]
    for run in (reference, other):
        for kind in ("engine only", "with the model"):
            tally = rerank.tally_by_group(domain, run[kind])
            cells = [f"{tally['groups'][g][0]}/{tally['groups'][g][1]}" for g in domain_groups]
            lines.append(f"| {run['name']}, {kind} | " + " | ".join(cells) + f" | {tally['right']}/{tally['cases']} |")
    lines.append("")

    lines += ["Table 2. Cases whose outputs differ between the two runs. A case of the work area that is about "
              "capitals differs when its capitals differ.", "",
              "| Run | differ after normalization | differ in letter case only |", "| --- | --- | --- |"]
    for kind in ("engine only", "with the model"):
        normalized, case_only = 0, 0
        for case_id in by_id:
            a, b = reference[kind][case_id], other[kind][case_id]
            if by_id[case_id].get("scoring") == "case":
                a, b = a.strip(), b.strip()
                if a != b:
                    normalized += 1
                    differences["cases"].append({"run": kind, "id": case_id, reference["name"]: a, other["name"]: b,
                                                 "intended": by_id[case_id]["intended"]})
            elif normalize("english", a) != normalize("english", b):
                normalized += 1
                differences["cases"].append({"run": kind, "id": case_id, reference["name"]: a, other["name"]: b,
                                             "intended": by_id[case_id]["intended"]})
            elif a != b:
                case_only += 1
        failed |= normalized > 0
        lines.append(f"| {kind} | {normalized} | {case_only} |")
    lines.append("")

    # Each run's recorded choice must be the tuned rule's choice on that run's own numbers.
    for run in (reference, other):
        for key, entry in run["trace"].items():
            if entry["result"] != "scores":
                continue
            rule = recorded_choice(entry)
            if rule != entry["choice"]:
                differences["rule mismatches"].append({"run": run["name"], "id": key[0], "step": key[1],
                                                       "choice": entry["choice"], "rule": rule})
    failed |= bool(differences["rule mismatches"])

    a_trace, b_trace = reference["trace"], other["trace"]
    shared = sorted(set(a_trace) & set(b_trace))
    counts = {f"corrections of {reference['name']}": len(a_trace), f"corrections of {other['name']}": len(b_trace),
              "in both runs": len(shared), "results other than scores": 0, "same text before, ignoring letter case": 0,
              "same context": 0, "same readings in the same order, with the same marks": 0, "same candidates": 0,
              "same choice": 0, "recorded choices that differ from the rule on the same run's numbers":
                  len(differences["rule mismatches"])}
    widest = {"engine score": 0.0, "log probability": 0.0, "space after": 0.0}
    gaps = []
    flips = []
    for key in shared:
        a, b = a_trace[key], b_trace[key]
        if a["result"] != "scores" or b["result"] != "scores":
            counts["results other than scores"] += 1
            continue
        same_before = a["text_before"].lower() == b["text_before"].lower()
        counts["same text before, ignoring letter case"] += same_before
        counts["same context"] += a["context"] == b["context"]
        marks = lambda entry: [(r["text"], r["as_typed"], r["chosen"]) for r in entry["readings"]]  # noqa: E731
        same_readings = marks(a) == marks(b)
        counts["same readings in the same order, with the same marks"] += same_readings
        same_candidates = [r["candidate"] for r in a["readings"]] == [r["candidate"] for r in b["readings"]]
        counts["same candidates"] += same_candidates
        counts["same choice"] += a["choice"] == b["choice"]
        by_text = {r["text"]: r for r in b["readings"]}
        for r in a["readings"]:
            o = by_text.get(r["text"])
            if o is None:
                continue
            widest["engine score"] = max(widest["engine score"], abs(r["engine_score"] - o["engine_score"]))
            gap = abs(float(r["log_probability"]) - float(o["log_probability"]))
            widest["log probability"] = max(widest["log probability"], gap)
            widest["space after"] = max(widest["space after"], abs(float(r["space_after"]) - float(o["space_after"])))
            gaps.append(gap)
        if a["choice"] != b["choice"] or a["context"] != b["context"] or not same_readings or not same_candidates \
                or not same_before:
            entry = {"id": key[0], "step": key[1], "same readings": same_readings, reference["name"]: a,
                     other["name"]: b, f"decision of {reference['name']}": decision(a),
                     f"decision of {other['name']}": decision(b)}
            differences["corrections"].append(entry)
            if a["choice"] != b["choice"]:
                flips.append(entry)
    counts[f"only in {reference['name']}"] = len(set(a_trace) - set(b_trace))
    counts[f"only in {other['name']}"] = len(set(b_trace) - set(a_trace))

    lines += ["Table 3. Corrections that went to the model, matched by case and by their place in the case.", "",
              "| Count | Value |", "| --- | --- |"]
    lines += [f"| {name} | {value} |" for name, value in counts.items()]
    lines.append("")
    gaps.sort()
    lines += ["Table 4. Difference of a number between the two runs, over the readings of the matched corrections, "
              "in natural-log units. The harness reads the model's numbers with 5 decimals and the engine's with 6.",
              "", "| Number | Value |", "| --- | --- |"]
    lines += [f"| {name}, widest | {value:.6f} |" for name, value in widest.items()]
    if gaps:
        lines.append(f"| log probability, median | {gaps[len(gaps) // 2]:.6f} |")
        lines.append(f"| log probability, 99th percentile | {gaps[min(len(gaps) - 1, int(len(gaps) * 0.99))]:.6f} |")
    lines.append("")
    distances = sorted(decision(e)["distance"] for e in a_trace.values() if e["result"] == "scores")
    for limit in (1e-5, 0.01, 0.1, 0.5):
        lines.append(f"Decisions of {reference['name']} that a change of {limit:g} in one combined score can turn: "
                     f"{sum(1 for d in distances if d <= limit)} of {len(distances)}.")
    lines.append("")

    if flips:
        lines += ["Table 5. Corrections whose choice differs, with the distance of each run's decision from its "
                  "turning point.", "",
                  f"| Case | Step | Same readings | {reference['name']} | {other['name']} | distance, {reference['name']} "
                  f"| distance, {other['name']} |", "| --- | --- | --- | --- | --- | --- | --- |"]
        a_name, b_name = reference["name"], other["name"]
        for row in flips:
            a_distance = row["decision of " + a_name]["distance"]
            b_distance = row["decision of " + b_name]["distance"]
            lines.append(f"| {row['id']} | {row['step']} | {row['same readings']} | {row[a_name]['choice']} | "
                         f"{row[b_name]['choice']} | {a_distance:.4f} | {b_distance:.4f} |")
        lines.append("")

    for run in (reference, other):
        check = run["folder"] / "scorer-check.txt"
        if check.exists():
            lines += [f"The keyboard's scorer against lm_score on the runner of {run['name']}, same requests:", ""]
            lines += ["    " + line for line in check.read_text(encoding="utf-8").splitlines()]
            lines.append("")
        for task in TASKS:
            report = run["folder"] / f"{task}.dev.reranker.txt"
            if report.exists():
                lines += [f"The model of {run['name']} after {task} dev:", ""]
                lines += ["    " + line for line in report.read_text(encoding="utf-8").splitlines()]
                lines.append("")

    text = "\n".join(lines) + "\n"
    (arguments.out / "report.md").write_text(text, encoding="utf-8")
    (arguments.out / "differences.json").write_text(json.dumps(differences, indent=1), encoding="utf-8")
    print(text)
    if failed:
        print("At least one check failed. report.md and differences.json give each difference.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

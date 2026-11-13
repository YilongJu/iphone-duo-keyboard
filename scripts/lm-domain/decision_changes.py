"""Counts the corrections where the Q4_K_M file of an arm takes another reading than its float32
reference, at one setting with the apostrophe step on.

The script types selection sets through the keyboard rules with the Q4_K_M file, as the phone
runs it. At each distinct correction with more than one reading it also asks the reference for
its choice from the same readings. The reference is the F32 GGUF of the arm scored by the copy of
lm_score with a 32-bit key and value cache and without flash attention. That reading is within
0.0003 nats of PyTorch float32 for every file (scripts/lm-domain/reports/select-tables.md).

For each correction the script keeps four choices: of the Q4_K_M file and of the reference, with
the apostrophe step and without it. A correction counts as changed when the two files differ.

A run takes some sets (--sets), so several runs can work at the same time. Each run needs its
own copy of the answers of the Q4_K_M file, because a run adds the answers that the copy lacks.
`--merge` adds the counts of the runs.

Usage, from the repository root, on Linux:
    LD_LIBRARY_PATH=$HOME/lmft/llama/lib python3 scripts/lm-domain/decision_changes.py --shim SHIM --lm LM_SCORE \
        --model ARM.Q4_K_M.gguf --q4-answers COPY_OF/answers.jsonl --reference-lm LM_SCORE_KV32 --reference-model ARM.f32.gguf \
        --setting 1.5 1 4 2 1 --lead 0.5 --sets dev published_dev --data build/lm-domain/data --out build/lm-domain/decisions/ARM/part-1
    python3 scripts/lm-domain/decision_changes.py --merge build/lm-domain/decisions/ARM
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-domain"))
import harness  # noqa: E402
import rerank  # noqa: E402

SETS = ("dev", "published_dev", "stream_select", "github_select", "domain_dev", "domain_stream_dev", "apostrophe_word", "apostrophe_next_word")
# The six sets of the parity study (trace_decisions.py), and the two sets of the apostrophe words.
GROUPS = {"six selection sets": SETS[:6], "apostrophe words": SETS[6:]}


def merge(folder: Path) -> None:
    rows = {}
    for path in sorted(folder.glob("*/corrections.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as file:
            for line in file:
                row = json.loads(line)
                rows.setdefault((row["context"], row["typed"], tuple(row["readings"])), row)
    report = {"runs": len(list(folder.glob("*/corrections.jsonl.gz"))), "groups": {}}
    for name, members in {**GROUPS, "all eight sets": SETS}.items():
        part = [row for row in rows.values() if row["set"] in members]
        report["groups"][name] = {
            "corrections": len(part),
            "changed_with_the_apostrophe_step": sum(1 for row in part if row["q4_step"] != row["reference_step"]),
            "changed_without_the_apostrophe_step": sum(1 for row in part if row["q4_plain"] != row["reference_plain"]),
            "changed_by_the_step_alone": sum(1 for row in part if row["q4_step"] != row["reference_step"] and row["q4_plain"] == row["reference_plain"]),
            "corrections_where_the_step_changes_the_q4_choice": sum(1 for row in part if row["q4_step"] != row["q4_plain"])}
    (folder / "decision-changes.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--merge", type=Path)
    parser.add_argument("--shim", type=Path)
    parser.add_argument("--lm", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--q4-answers", type=Path)
    parser.add_argument("--reference-lm", type=Path)
    parser.add_argument("--reference-model", type=Path)
    parser.add_argument("--setting", type=float, nargs=5, metavar=("WEIGHT", "FROM_TYPED", "TO_TYPED", "OTHER", "SPACE_AFTER"))
    parser.add_argument("--lead", type=float)
    parser.add_argument("--sets", nargs="+", choices=SETS)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()
    if arguments.merge is not None:
        merge(arguments.merge)
        return
    values = dict(zip(harness.GRID_FIELDS, arguments.setting))
    values["space_after"] = int(values["space_after"])
    with_step = rerank.Setting(**values, **dict(harness.STEP, margin_apostrophe=arguments.lead))
    without_step = rerank.Setting(**values)
    sets = harness.load_sets(arguments.data, "select")
    typist = harness.Typist(arguments.shim, readings_file=arguments.data / "engine-readings.pickle")
    arguments.out.mkdir(parents=True, exist_ok=True)
    q4, q4_stored, _ = harness.open_model(arguments.lm, arguments.model, arguments.threads, arguments.q4_answers)
    reference, reference_stored, _ = harness.open_model(arguments.reference_lm, arguments.reference_model, arguments.threads,
                                                        arguments.out / "answers-reference.jsonl")
    seen: dict[tuple, dict] = {}

    def chooser(readings, text_before, typed=None):
        context = text_before.rstrip(" ")
        choice = rerank.choose(readings, context, with_step, q4, typed)
        if len(readings) > 1:
            key = (context, typed, tuple(r["text"] for r in readings))
            if key not in seen:
                seen[key] = {"set": name, "context": context, "typed": typed, "readings": list(key[2]), "q4_step": choice,
                             "q4_plain": rerank.choose(readings, context, without_step, q4, typed),
                             "reference_step": rerank.choose(readings, context, with_step, reference, typed),
                             "reference_plain": rerank.choose(readings, context, without_step, reference, typed)}
        return choice

    for name in arguments.sets:
        typist.run(sets[name]["cases"], chooser)
        print(name, "typed,", len(seen), "corrections so far", flush=True)
    q4.close()
    reference.close()
    with gzip.open(arguments.out / "corrections.jsonl.gz", "wt", encoding="utf-8") as file:
        for row in seen.values():
            file.write(json.dumps(row) + "\n")
    print(json.dumps({"corrections": len(seen), "new_answers_of_the_q4_file": q4_stored.asked,
                      "new_answers_of_the_reference": reference_stored.asked}))


if __name__ == "__main__":
    main()

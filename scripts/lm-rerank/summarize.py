"""Builds the results table of the re-ranking measurement from the downloaded run artifacts.

Usage: python3 scripts/lm-rerank/summarize.py ARTIFACTS_FOLDER > table.md

The folder holds one subfolder per run: engine-check/ (result.json of the control without a
model) and one rerank-NAME/ per model with result.json, probe-NAME.txt and probe-baseline.txt.

Phone estimates scale the measurement on the iPhone (keyboard process, 2 threads, distilgpt2
Q3_K_M) by the ratio of each model to distilgpt2 Q3_K_M on the same Linux runner, 2 threads.
"""
import json
import re
import sys
from pathlib import Path

PHONE_PER_TOKEN_MS = 1.71
PHONE_CANDIDATES_MS = 13.6 + 9.8
PHONE_EXTRA_MB = 26.5
FLAG_LATENCY_MS = 50.0
FLAG_MEMORY_MB = 100.0
GROUPS = ["clean", "letter_slips", "space_slips", "symbol_slips", "clean_symbols"]


def probe_numbers(text: str) -> dict:
    """Per-token mean, context plus one-batch candidate time, at 2 threads, and the growth of
    anonymous memory from before the load to the highest later reading."""
    numbers = {}
    per_token = re.findall(r"^per token   2 threads: mean ([\d.]+) ms", text, re.M)
    candidates = re.findall(r"^candidates  2 threads: context ([\d.]+) ms, then 8 candidates of (\d+) tokens: "
                            r"[\d.]+ ms one by one, ([\d.]+) ms in one batch", text, re.M)
    anon = [float(v) for v in re.findall(r"^memory      .*: Linux, anonymous ([\d.]+) MB", text, re.M)]
    if per_token:
        numbers["per_token_ms"] = sum(map(float, per_token)) / len(per_token)
    if candidates:
        numbers["candidates_ms"] = sum(float(c) + float(b) for c, _, b in candidates) / len(candidates)
        numbers["candidate_tokens"] = int(candidates[0][1])
    if len(anon) >= 2:
        numbers["anon_growth_mb"] = max(anon[1:]) - anon[0]
    model = re.search(r"^model       (\S+), ([\d.]+) MB", text, re.M)
    if model:
        numbers["file_mb"] = float(model.group(2))
    failed = re.search(r"^(load        failed.*)$", text, re.M)
    if failed:
        numbers["load_failed"] = failed.group(1).strip()
    return numbers


def cell(entry: dict) -> str:
    return f"{entry['right']}/{entry['cases']} ({entry['accuracy']:.4f})"


def main():
    folder = Path(sys.argv[1])
    check = json.loads((folder / "engine-check" / "result.json").read_text())
    control = check["control"]
    without = check["without_model"]["tuned"]["summary"]
    oracle = check["oracle"]
    print("Table 1. Dev scores of the control (engine choice, Linux harness), the margins tuned without a model, "
          "each re-ranked model, and the oracle over the same reading lists.\n")
    print("| Run | " + " | ".join(GROUPS) + " | all dev cases |")
    print("| --- |" + " --- |" * (len(GROUPS) + 1))
    for label, entry in (("control", control), ("margins without a model", without)):
        print(f"| {label} | " + " | ".join(cell(entry["groups"][g]) for g in GROUPS) + f" | {entry['right']}/{entry['cases']} |")
    rows = []
    for run in sorted(folder.glob("rerank-*")):
        name = run.name[len("rerank-"):]
        probe_files = [p for p in run.glob("probe-*.txt") if p.name != "probe-baseline.txt"]
        probe = probe_numbers(probe_files[0].read_text()) if probe_files else {}
        base = probe_numbers((run / "probe-baseline.txt").read_text()) if (run / "probe-baseline.txt").exists() else {}
        if "load_failed" in probe and (run / "load-error.txt").exists():
            reasons = [line for line in (run / "load-error.txt").read_text().splitlines() if "error loading model" in line]
            if reasons:
                probe["load_failed"] = "does not load: " + reasons[0].split("error loading model: ")[-1].strip()
        result_path = run / "result.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else None
        rows.append((name, probe, base, result))
        if result is None or result.get("tuned") is None:
            reason = probe.get("load_failed", "no result")
            print(f"| {name} | " + " | ".join("" for _ in GROUPS) + f" | {reason} |")
            continue
        own_control = result["control"]
        if own_control["right"] != control["right"]:
            print(f"| {name} control differs from the engine-check control: {own_control['right']} |")
        tuned = result["tuned"]["summary"]
        print(f"| {name} | " + " | ".join(cell(tuned["groups"][g]) for g in GROUPS) + f" | {tuned['right']}/{tuned['cases']} |")
    print("| oracle over the 8 readings | " + " | ".join(cell(oracle["groups"][g]) for g in GROUPS)
          + f" | {oracle['right']}/{oracle['cases']} |")

    print("\nTable 2. Tuned setting and the two-fold check inside the dev half: tuned on one fold (clean rule on that "
          "fold only), gain in right cases over the control read on the other fold, and the change in right clean "
          "cases on the other fold.\n")
    print("| Run | weight | margin from typed | margin to typed | margin other | space after | gain on dev | "
          "fold 0 to 1 | fold 1 to 0 | clean change, 0 to 1 / 1 to 0 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    entries = [("margins without a model", check["without_model"], control)]
    entries += [(name, result, result["control"]) for name, probe, base, result in rows
                if result is not None and result.get("tuned") is not None]
    for name, tuned_result, own_control in entries:
        s = tuned_result["tuned"]["setting"]
        folds = tuned_result["fold_check"]
        gain = tuned_result["tuned"]["summary"]["right"] - own_control["right"]
        print(f"| {name} | {s['weight']} | {s['margin_from_typed']} | {s['margin_to_typed']} | {s['margin_other']} | "
              f"{s['space_after']} | {gain:+d} | {folds[0]['gain_on_other_fold']:+d} | {folds[1]['gain_on_other_fold']:+d} | "
              f"{folds[0]['clean_change_on_other_fold']:+d} / {folds[1]['clean_change_on_other_fold']:+d} |")

    print("\nTable 3. Size, speed on the Linux runner (2 threads, the model and distilgpt2 Q3_K_M on the same runner) "
          "and the phone estimates. Estimate A scales the phone's 8-candidate time (23.4 ms) by the per-token ratio, "
          "estimate B by the ratio of the 8-candidate times. The flags use the larger estimate.\n")
    print("| Model | file MB | per token ms, model / baseline | per-token ratio | phone per token ms | "
          "phone 8 candidates ms, A | phone 8 candidates ms, B | anon growth MB, model / baseline | phone extra MB | flags |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, probe, base, result in rows:
        if "per_token_ms" not in probe or "per_token_ms" not in base:
            print(f"| {name} | {probe.get('file_mb', '')} | {probe.get('load_failed', 'not measured')} | | | | | | | |")
            continue
        ratio = probe["per_token_ms"] / base["per_token_ms"]
        estimate_a = PHONE_CANDIDATES_MS * ratio
        estimate_b = PHONE_CANDIDATES_MS * probe["candidates_ms"] / base["candidates_ms"]
        phone_memory = PHONE_EXTRA_MB + probe["anon_growth_mb"] - base["anon_growth_mb"]
        flags = []
        if max(estimate_a, estimate_b) > FLAG_LATENCY_MS:
            flags.append("latency over 50 ms")
        if phone_memory > FLAG_MEMORY_MB:
            flags.append("memory over 100 MB")
        print(f"| {name} | {probe['file_mb']:.1f} | {probe['per_token_ms']:.2f} / {base['per_token_ms']:.2f} | {ratio:.2f} | "
              f"{PHONE_PER_TOKEN_MS * ratio:.2f} | {estimate_a:.1f} | {estimate_b:.1f} | "
              f"{probe['anon_growth_mb']:.1f} / {base['anon_growth_mb']:.1f} | {phone_memory:.1f} | {', '.join(flags) or 'none'} |")


if __name__ == "__main__":
    main()

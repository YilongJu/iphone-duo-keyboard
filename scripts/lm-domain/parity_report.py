"""Reports the size, the cause and the effect of the parity differences of every arm.

For each arm with a parity folder (build/lm-domain/parity/ARM/{everyday,domain}) the script
compares four score sets of the first 500 parity lists, reading by reading:
    torch-f32         PyTorch with the float32 weights (parity_study.py, on the GPU)
    torch-rounded16   PyTorch with every weight rounded to a 16-bit float (parity_study.py)
    lm_score f16      lm_score on the f16 GGUF (the file that check_parity.py reads)
    lm_score f32      lm_score on an F32 GGUF of the same model (jobs/parity-f32.sh)
A difference of a reading is the larger of its two differences: the log probability of its
tokens, and the log probability of a space after it. For each pair of score sets the script
gives the largest difference, the 99.9th percentile, the mean and the count over 0.05 nats. It
relates the difference between PyTorch float32 and lm_score f16 to the size of the score, to
the tokens of the context and to the tokens of the reading.

It writes parity-f32.json beside each parity.json, with the same fields from the F32 file, so
summarize3.py can apply the parity condition to either file.

For an arm with build/lm-domain/parity-study/ARM (trace_decisions.py and parity_study.py), it
counts the corrections of the selection sets where the shipped rule, without the apostrophe
step, takes another reading with the float32 scores of PyTorch than with the scores of the
Q4_K_M file.

Usage, from the repository root:
    python3 scripts/lm-domain/parity_report.py --parity build/lm-domain/parity --study build/lm-domain/parity-study \
        --out build/lm-domain/summary/parity-report.json
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import rerank  # noqa: E402

LIMIT = 0.05
SHIPPED = rerank.Setting(weight=1.0, margin_from_typed=0, margin_to_typed=4, margin_other=2, space_after=1)


def read_torch(path: Path) -> list[list[list[float]]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def read_lm(path: Path, lists: int) -> list[list[list[float]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].startswith("ready"):
        raise SystemExit(f"{path} does not start with the ready line of lm_score")
    rows = [[[float(v) for v in field.split(" ")] for field in line.split("\t")] for line in lines[1:]]
    if len(rows) < lists:
        raise SystemExit(f"{path} holds {len(rows)} lists, fewer than {lists}")
    return rows[:lists]


def differences(first, second) -> list[float]:
    return [max(abs(a[0] - b[0]), abs(a[1] - b[1])) for x, y in zip(first, second) for a, b in zip(x, y)]


def stats(values: list[float]) -> dict:
    ordered = sorted(values)
    return {"readings": len(values), "largest": round(ordered[-1], 4), "percentile_99_9": round(ordered[int(0.999 * (len(ordered) - 1))], 4),
            "mean": round(sum(values) / len(values), 5), "over_the_limit": sum(1 for value in values if value > LIMIT)}


def by_bins(values: list[float], keys: list[float], edges: list[float], unit: str) -> dict:
    found = {}
    for low, high in zip(edges, edges[1:]):
        chosen = [value for value, key in zip(values, keys) if low <= key < high]
        if chosen:
            found[f"{low:g} to {high:g} {unit}"] = {"readings": len(chosen), "mean": round(sum(chosen) / len(chosen), 5),
                                                    "largest": round(max(chosen), 4), "over_the_limit": sum(1 for v in chosen if v > LIMIT)}
    return found


class Scores:
    """Gives rerank.choose the scores of one correction."""

    def __init__(self, texts: list[str], scores: list[list[float]]):
        self.scores = {text: tuple(pair) for text, pair in zip(texts, scores)}

    def reading_scores(self, context, readings, typed):
        return self.scores


def decisions(folder: Path) -> dict | None:
    if not (folder / "torch-scores.jsonl.gz").exists():
        return None
    with gzip.open(folder / "corrections.jsonl.gz", "rt", encoding="utf-8") as file:
        corrections = [json.loads(line) for line in file]
    with gzip.open(folder / "torch-scores.jsonl.gz", "rt", encoding="utf-8") as file:
        torch_scores = [json.loads(line) for line in file]
    if len(corrections) != len(torch_scores):
        raise SystemExit(f"{folder}: {len(corrections)} corrections and {len(torch_scores)} score rows")
    per_set: dict[str, list[int]] = {}
    gaps = []
    for correction, torch_row in zip(corrections, torch_scores):
        readings = [{"text": r[0], "score": r[1], "slips": r[2], "as_typed": bool(r[3]), "chosen": bool(r[4])} for r in correction["readings"]]
        texts = [r["text"] for r in readings]
        with_q4 = rerank.choose(readings, correction["context"], SHIPPED, Scores(texts, correction["q4"]), correction["typed"])
        with_torch = rerank.choose(readings, correction["context"], SHIPPED, Scores(texts, torch_row), correction["typed"])
        entry = per_set.setdefault(correction["set"], [0, 0])
        entry[0] += int(with_q4 != with_torch)
        entry[1] += 1
        gaps += [max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a, b in zip(correction["q4"], torch_row)]
    return {"corrections": len(corrections), "other_choice": sum(entry[0] for entry in per_set.values()),
            "per_set": {name: {"other_choice": entry[0], "corrections": entry[1]} for name, entry in per_set.items()},
            "q4_against_torch_f32": stats(gaps)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parity", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    report = {}
    for folder in sorted(path for path in arguments.parity.iterdir() if path.is_dir()):
        arm = {}
        for lists in ("everyday", "domain"):
            here = folder / lists
            if not (here / "torch-f32.jsonl").exists() or not (here / "llama-scores-f32.txt").exists():
                continue
            torch32 = read_torch(here / "torch-f32.jsonl")
            rounded = read_torch(here / "torch-rounded16.jsonl")
            cpu = read_torch(here / "hf-scores.jsonl")
            f16 = read_lm(here / "llama-scores.txt", len(torch32))
            f32 = read_lm(here / "llama-scores-f32.txt", len(torch32))
            counts = read_torch(here / "token-counts.jsonl")
            main_gap = differences(torch32, f16)
            score_size = [-pair[0] for row in torch32 for pair in row]
            context_tokens = [float(row["context_tokens"]) for row in counts for _ in row["reading_tokens"]]
            reading_tokens = [float(tokens) for row in counts for tokens in row["reading_tokens"]]
            entry = {
                "torch_f32_cpu_against_lm_score_f16 (check_parity.py)": stats(differences(cpu, f16)),
                "torch_f32_against_lm_score_f16": stats(main_gap),
                "torch_f32_against_torch_rounded16": stats(differences(torch32, rounded)),
                "torch_rounded16_against_lm_score_f16": stats(differences(rounded, f16)),
                "torch_f32_against_lm_score_f32": stats(differences(torch32, f32)),
                "torch_f32_cpu_against_lm_score_f32": stats(differences(cpu, f32)),
                "torch_f32_cpu_against_torch_f32_gpu": stats(differences(cpu, torch32)),
                "by_size_of_the_score": by_bins(main_gap, score_size, [0, 5, 10, 20, 40, 1000], "nats"),
                "by_tokens_of_the_context": by_bins(main_gap, context_tokens, [0, 10, 20, 40, 98], "tokens"),
                "by_tokens_of_the_reading": by_bins(main_gap, reading_tokens, [1, 2, 3, 4, 6, 33], "tokens"),
            }
            arm[lists] = entry
            earlier = json.loads((here / "parity.json").read_text(encoding="utf-8"))
            gap = differences(cpu, f32)
            pairs = [(abs(a[0] - b[0]), abs(a[1] - b[1])) for x, y in zip(cpu, f32) for a, b in zip(x, y)]
            (here / "parity-f32.json").write_text(json.dumps({
                "token_mismatches": earlier["token_mismatches"], "score_readings": len(gap),
                "largest_log_probability_difference": max(pair[0] for pair in pairs),
                "largest_space_after_difference": max(pair[1] for pair in pairs), "score_limit": LIMIT,
                "scores_of": "PyTorch float32 on the processor against lm_score on an F32 GGUF"}, indent=1), encoding="utf-8")
        found = decisions(arguments.study / folder.name)
        if found is not None:
            arm["decisions_on_the_selection_sets"] = found
        if arm:
            report[folder.name] = arm
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("| Arm | lists | PyTorch f32 against lm_score f16: largest, 99.9th, over 0.05 | PyTorch f32 against PyTorch rounded to 16 bits | "
          "PyTorch rounded against lm_score f16 | PyTorch f32 against lm_score F32 |")
    print("| --- | --- | --- | --- | --- | --- |")

    def cell(entry: dict) -> str:
        return f"{entry['largest']}, {entry['percentile_99_9']}, {entry['over_the_limit']}"

    for name, arm in report.items():
        for lists in ("everyday", "domain"):
            if lists in arm:
                e = arm[lists]
                print(f"| `{name}` | {lists} | {cell(e['torch_f32_cpu_against_lm_score_f16 (check_parity.py)'])} | {cell(e['torch_f32_against_torch_rounded16'])} "
                      f"| {cell(e['torch_rounded16_against_lm_score_f16'])} | {cell(e['torch_f32_cpu_against_lm_score_f32'])} |")
    for name, arm in report.items():
        if "decisions_on_the_selection_sets" in arm:
            d = arm["decisions_on_the_selection_sets"]
            print(name, "decisions:", d["other_choice"], "of", d["corrections"], json.dumps(d["q4_against_torch_f32"]))


if __name__ == "__main__":
    main()

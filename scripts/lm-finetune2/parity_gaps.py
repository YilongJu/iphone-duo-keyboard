"""Looks into the score differences between PyTorch and lm_score that check_parity.py reports.

For one arm the script reads the parity folder of check_parity.py (2,000 lists of the round 1
tuning split, with PyTorch float32 scores for the first 500) and
- lists the readings with the largest difference between PyTorch and lm_score on the f16 file,
  with their tokens and their scores, also on the Q4_K_M file;
- relates the difference to the size of the score, the tokens of the context and of the reading;
- counts the decisions that a score error could change: at the arm's setting, the lists where
  the lead of the reading that the re-ranker takes lies within a given distance of the margin.

Usage, on Linux, from the repository root:
    python3 scripts/lm-finetune2/parity_gaps.py --parity build/lm-finetune2/parity/NAME --lm ~/lmft/bin/lm_score \
        --f16 ~/lmft2/models/NAME.f16.gguf --quantized ~/lmft2/models/NAME.Q4_K_M.gguf \
        --lists ROUND1/build/lm-finetune/data/lists.tune.jsonl.gz --setting 1.0,0,4,2,1
"""
import argparse
import gzip
import json
import random
import statistics
import subprocess
from pathlib import Path

TOKEN_LISTS = 2000
SCORE_LISTS = 500
WINDOWS = (0.05, 0.1, 0.25, 0.5, 1.0)


def lm_scores(program: Path, model: Path, requests: list[str], cache: Path) -> list[list[tuple[float, float]]]:
    if not cache.exists():
        answer = subprocess.run(["nice", "-n", "19", str(program), str(model), "2"], input="\n".join(requests) + "\n",
                                capture_output=True, text=True, check=True)
        cache.write_text(answer.stdout, encoding="utf-8")
    lines = cache.read_text(encoding="utf-8").splitlines()
    if not lines[0].startswith("ready") or len(lines) - 1 != len(requests):
        raise SystemExit(f"{cache} does not hold one line per request")
    return [[tuple(float(v) for v in field.split(" ")) for field in line.split("\t")] for line in lines[1:]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parity", type=Path, required=True)
    parser.add_argument("--lm", type=Path, required=True)
    parser.add_argument("--f16", type=Path, required=True)
    parser.add_argument("--quantized", type=Path, required=True)
    parser.add_argument("--lists", type=Path, required=True)
    parser.add_argument("--setting", required=True, help="weight,from_typed,to_typed,other,space_after")
    arguments = parser.parse_args()

    with gzip.open(arguments.lists, "rt", encoding="utf-8") as file:
        lists = [json.loads(line) for line in file]
    random.Random(20261110).shuffle(lists)
    lists = lists[:TOKEN_LISTS]
    requests = (arguments.parity / "requests.tsv").read_text(encoding="utf-8").splitlines()
    tokens = [json.loads(line) for line in (arguments.parity / "hf-tokens.jsonl").read_text(encoding="utf-8").splitlines()]
    torch_scores = [json.loads(line) for line in (arguments.parity / "hf-scores.jsonl").read_text(encoding="utf-8").splitlines()]
    if len(requests) != TOKEN_LISTS or len(torch_scores) != SCORE_LISTS:
        raise SystemExit("the parity folder does not hold 2,000 requests and 500 scored lists")
    f16 = lm_scores(arguments.lm, arguments.f16, requests[:SCORE_LISTS], arguments.parity / "gaps-f16.txt")
    quantized = lm_scores(arguments.lm, arguments.quantized, requests, arguments.parity / "gaps-quantized.txt")

    rows = []
    for index in range(SCORE_LISTS):
        fields = requests[index].split("\t")
        for k, reading in enumerate(fields[1:]):
            rows.append({"list": index, "context": fields[0], "reading": reading, "context_tokens": len(tokens[index]["prefix"]),
                         "reading_tokens": len(tokens[index]["readings"][k]), "category": lists[index]["category"],
                         "torch": torch_scores[index][k][0], "f16": f16[index][k][0], "quantized": quantized[index][k][0],
                         "gap": abs(torch_scores[index][k][0] - f16[index][k][0]),
                         "quantized_gap": abs(quantized[index][k][0] - f16[index][k][0]),
                         "target": k == lists[index]["target"]})
    rows.sort(key=lambda row: -row["gap"])
    report = {"readings": len(rows), "largest_gap": rows[0]["gap"], "mean_gap": statistics.mean(r["gap"] for r in rows),
              "readings_over_0.05": sum(r["gap"] > 0.05 for r in rows), "readings_over_0.03": sum(r["gap"] > 0.03 for r in rows),
              "mean_quantized_gap": statistics.mean(r["quantized_gap"] for r in rows),
              "largest_quantized_gap": max(r["quantized_gap"] for r in rows)}
    # The relative difference: gap over the size of the score.
    report["mean_gap_by_score"] = {}
    for low, high in ((0, 5), (5, 10), (10, 20), (20, 40), (40, 1000)):
        members = [r["gap"] for r in rows if low <= -r["torch"] < high]
        if members:
            report["mean_gap_by_score"][f"{low} to {high} nats"] = {"readings": len(members), "mean": round(statistics.mean(members), 4),
                                                                    "largest": round(max(members), 4)}
    report["mean_gap_by_reading_tokens"] = {}
    for count in sorted({min(r["reading_tokens"], 6) for r in rows}):
        members = [r["gap"] for r in rows if min(r["reading_tokens"], 6) == count]
        report["mean_gap_by_reading_tokens"][f"{count}{'+' if count == 6 else ''} tokens"] = {
            "readings": len(members), "mean": round(statistics.mean(members), 4), "largest": round(max(members), 4)}
    report["top_gaps_are_targets"] = sum(r["target"] for r in rows[:20])
    report["top"] = [{key: (round(r[key], 4) if isinstance(r[key], float) else r[key]) for key in
                      ("gap", "torch", "f16", "quantized", "context", "reading", "context_tokens", "reading_tokens", "category", "target")}
                     for r in rows[:8]]

    # Decisions near the margin, on the 2,000 lists, with the scores of the quantized file.
    weight, from_typed, to_typed, other, space_after = (float(v) for v in arguments.setting.split(","))
    near = {window: 0 for window in WINDOWS}
    changes, decided = 0, 0
    for index, item in enumerate(lists):
        readings = item["readings"]
        if len(readings) < 2:
            continue
        decided += 1
        combined = [reading[1] + weight * (score[0] + (score[1] if space_after else 0.0)) for reading, score in zip(readings, quantized[index])]
        chosen = next(k for k, reading in enumerate(readings) if reading[4] == 1)
        best = max(range(len(readings)), key=lambda k: combined[k])
        if best == chosen:
            # The engine's choice stays. A score error matters when a rival comes within its margin.
            leads = []
            for k in range(len(readings)):
                if k == chosen:
                    continue
                margin = from_typed if readings[chosen][3] == 1 else (to_typed if readings[k][3] == 1 else other)
                leads.append(margin - (combined[k] - combined[chosen]))
            distance = min(leads)
        else:
            margin = from_typed if readings[chosen][3] == 1 else (to_typed if readings[best][3] == 1 else other)
            distance = abs(combined[best] - combined[chosen] - margin)
            ranked = sorted(combined, reverse=True)
            distance = min(distance, ranked[0] - ranked[1])
            if combined[best] - combined[chosen] >= margin:
                changes += 1
        for window in WINDOWS:
            near[window] += distance < window
    report["decisions"] = {"lists": decided, "re_ranker_changes_the_engine_choice": changes,
                           "within_nats_of_a_flip": {str(window): count for window, count in near.items()}}
    (arguments.parity / "gaps.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()

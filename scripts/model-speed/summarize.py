"""Summarizes runs of speed_cli (scripts/model-speed/speed_cli.c) and of the Core ML check.

Usage: python3 summarize.py [--reference NAME=ANSWERS ...] OUT_PREFIX ...
  OUT_PREFIX   the OUT of a run: OUT.summary, OUT.times and OUT.answers
  --reference  the answers of llama.cpp on the same model at Q8_0, for the agreement of each run
               whose model name starts with NAME

Prints one JSON object per run with:
  request_ms, candidate_ms, window_ms   mean, median, 95th percentile and worst, over the requests
                                        after the first
  first_request_ms, load_ms, memory     from OUT.summary
  agreement                             the share of requests whose top candidate equals the top
                                        candidate of the reference. The top candidate is the one
                                        with the highest log probability plus space-after term.
"""

import argparse
import json
import math
import pathlib


def percentile(values, share):
    ordered = sorted(values)
    # The nearest rank, as RerankStatistics.percentileMilliseconds of the keyboard.
    rank = max(1, math.ceil(share * len(ordered)))
    return ordered[rank - 1]


def stats(values):
    return {
        "mean": round(sum(values) / len(values), 2),
        "median": round(percentile(values, 0.5), 2),
        "p95": round(percentile(values, 0.95), 2),
        "worst": round(max(values), 2),
    }


def read_answers(path):
    answers = []
    for line in pathlib.Path(path).read_text().splitlines():
        pairs = [field.split(" ") for field in line.split("\t")]
        answers.append([float(lp) + float(sa) for lp, sa in pairs])
    return answers


def top(scores):
    return max(range(len(scores)), key=lambda index: scores[index])


def agreement(answers, reference):
    if len(answers) != len(reference):
        raise SystemExit(f"{len(answers)} answers against {len(reference)} of the reference")
    same = sum(1 for mine, theirs in zip(answers, reference) if top(mine) == top(theirs))
    return round(same / len(answers), 4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument("runs", nargs="+")
    arguments = parser.parse_args()
    references = {}
    for item in arguments.reference:
        name, path = item.split("=", 1)
        references[name] = read_answers(path)
    for run in arguments.runs:
        summary = {}
        for line in pathlib.Path(run + ".summary").read_text().splitlines():
            key, _, value = line.partition(" ")
            summary[key] = value
        rows = [line.split() for line in pathlib.Path(run + ".times").read_text().splitlines()]
        later = rows[1:]
        result = {
            "run": pathlib.Path(run).name,
            "requests": len(rows),
            "load_ms": round(float(summary["load_ms"]), 1),
            "first_request_ms": round(float(summary["first_request_ms"]), 1),
            "request_ms": stats([float(row[4]) for row in later]),
            "candidate_ms": stats([float(row[3]) for row in later]),
            "window_ms": stats([float(row[2]) for row in later]),
            "memory": {key: summary[key] for key in summary if key.startswith("memory")},
            "reuse_share": round(int(summary["window_tokens_reused"]) / int(summary["window_tokens"]), 3),
            "tokens_read": int(summary["tokens_read"]),
        }
        answers = read_answers(run + ".answers")
        for name, reference in references.items():
            if pathlib.Path(run).name.startswith(name):
                result["agreement_with_q8_0"] = agreement(answers, reference)
        print(json.dumps(result))


if __name__ == "__main__":
    main()

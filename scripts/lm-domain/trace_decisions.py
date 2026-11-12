"""Writes every correction that one scored arm makes on the selection sets, for the parity study.

The script types the selection sets again at the shipped setting, with the stored answers of
lm_score for the arm's Q4_K_M file, and writes each distinct correction with more than one
reading: the text before the span, the typed span, the readings with their engine numbers, and
the two scores of the Q4_K_M file per reading. parity_study.py adds the float32 scores of
PyTorch, and parity_report.py counts the corrections where the two give another choice.

Usage, from the repository root, on Linux:
    LD_LIBRARY_PATH=$HOME/lmft/llama/lib python3 scripts/lm-domain/trace_decisions.py --shim SHIM --lm LM_SCORE \
        --model MODEL.gguf --result build/lm-domain/results/ARM --data build/lm-domain/data \
        --out build/lm-domain/parity-study/ARM
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

SETS = ("dev", "published_dev", "stream_select", "github_select", "domain_dev", "domain_stream_dev")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    sets = harness.load_sets(arguments.data, "select")
    typist = harness.Typist(arguments.shim, readings_file=arguments.data / "engine-readings.pickle")
    scorer, stored, _ = harness.open_model(arguments.lm, arguments.model, 1, arguments.result / "answers.jsonl")
    setting = harness.setting_of(harness.SHIPPED.__dict__)
    seen: dict[tuple, dict] = {}

    def chooser(readings, text_before, typed=None):
        context = text_before.rstrip(" ")
        choice = rerank.choose(readings, context, setting, scorer, typed)
        if len(readings) > 1:
            key = (context, typed, tuple(r["text"] for r in readings))
            if key not in seen:
                scores = scorer.reading_scores(context, readings, typed)
                seen[key] = {"set": name, "context": context, "typed": typed,
                             "readings": [[r["text"], r["score"], r["slips"], int(r["as_typed"]), int(r["chosen"])] for r in readings],
                             "q4": [list(scores[r["text"]]) for r in readings]}
        return choice

    for name in SETS:
        typist.run(sets[name]["cases"], chooser)
    scorer.close()
    arguments.out.mkdir(parents=True, exist_ok=True)
    with gzip.open(arguments.out / "corrections.jsonl.gz", "wt", encoding="utf-8") as file:
        for row in seen.values():
            file.write(json.dumps(row) + "\n")
    print(json.dumps({"corrections": len(seen), "new_answers_of_lm_score": stored.asked}))


if __name__ == "__main__":
    main()

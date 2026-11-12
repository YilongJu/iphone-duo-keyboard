"""Writes the cases that one scored model gets wrong, with the readings of each correction.

For an arm that score_model.py scored, the script types again every wrong case of the chosen
sets at one setting rule, and records each correction: the text before the span, the typed
span, every reading with its engine score and the model's two scores, and the choice. The
answers of lm_score come from the arm's file of stored answers. `intended_in_list` says whether
the perfect chooser gets the case right, so a machine can set the label engine_recall of
scripts/lm-domain/label-rule.md.

Usage, from the repository root, on Linux:
    LD_LIBRARY_PATH=$HOME/lmft/llama/lib python3 scripts/lm-domain/dump_errors.py --shim SHIM --lm LM_SCORE \
        --model MODEL.gguf --result build/lm-domain/results/ship --rule shipped --data build/lm-domain/data \
        --sets dev github_select --out build/lm-domain/audit/ship-errors.jsonl
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-domain"))
import harness  # noqa: E402
import rerank  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--rule", required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--sets", nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    result = json.loads((arguments.result / "result.json").read_text(encoding="utf-8"))
    setting = harness.setting_of(result["tuning"]["rules"][arguments.rule]["setting"])
    sets = harness.load_sets(arguments.data, "evaluation")
    typist = harness.Typist(arguments.shim, readings_file=arguments.data / "engine-readings.pickle")
    scorer, stored, digest = harness.open_model(arguments.lm, arguments.model, 2, arguments.result / "answers.jsonl")
    if digest != result["model_sha256"]:
        raise SystemExit("the model file is not the file of the result")
    perfect = {}
    with (arguments.result / "outputs.perfect.jsonl").open(encoding="utf-8") as file:
        for line in file:
            row = json.loads(line)
            perfect[(row["set"], row["id"])] = row["output"]
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with arguments.out.open("w", encoding="utf-8", newline="\n") as file:
        for name in arguments.sets:
            wrong = 0
            for case in sets[name]["cases"]:
                corrections = []

                def chooser(readings, text_before, typed=None):
                    context = text_before.rstrip(" ")
                    choice = rerank.choose(readings, context, setting, scorer, typed)
                    scores = scorer.reading_scores(context, readings, typed) if len(readings) > 1 else {}
                    corrections.append({"text_before": text_before, "typed_span": typed, "choice": choice,
                                        "readings": [{"text": r["text"], "engine": r["score"], "slips": r["slips"],
                                                      "as_typed": r["as_typed"], "engine_choice": r["chosen"],
                                                      "model": list(scores[r["text"]]) if scores else None} for r in readings]})
                    return choice

                shown = typist.type(case, chooser)
                if harness.is_right(case, shown):
                    continue
                wrong += 1
                file.write(json.dumps({"set": name, "id": case["id"], "category": case["category"], "context": case["context"],
                                       "typed": case["typed"], "intended": case["intended"], "shown": shown,
                                       "intended_in_list": harness.is_right(case, perfect[(name, case["id"])]),
                                       "corrections": corrections}) + "\n")
            counts[name] = wrong
    scorer.close()
    print(json.dumps({"wrong_cases": counts, "new_answers_of_lm_score": stored.asked}))


if __name__ == "__main__":
    main()

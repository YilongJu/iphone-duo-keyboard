"""Scores one arm beyond its evaluate.py run, for the interpolation part of the design.

evaluate.py of the fine-tune has already picked the arm's setting on the tuning split and scored
dev at that setting. This script loads the model scores that run saved (lm-scores.jsonl), so a
request the run already made costs nothing, and adds three things.

1. Stopping cases: cases.stop.jsonl typed through the keyboard rules at the arm's tuned setting,
   and by the control. The design chooses the interpolation coefficient from these counts.
2. Common setting (--common-setting): dev and the published misspellings at one setting that
   every coefficient of a base shares, the tuned setting of the fine-tune. It separates the
   change of the weights from the change of the setting.
3. Calibration-only candidates (--weight-candidates): the tuning grid again, then for each
   re-ranker weight of the grid the best setting that keeps the clean groups of the tuning split.
   Each candidate is scored on the stopping cases, dev and the published misspellings. The design
   applies the coefficient's selection rule to these candidates of the fine-tune, so the fine-tune
   gets the same extra search on the stopping cases as the interpolation gets.

Usage, on Linux, with the fine-tune worktree as FINETUNE:
    python3 eval_extra.py --finetune FINETUNE --shim libduo_shim.so --lm lm_score --model MODEL.gguf \
        --threads 2 --run RESULTS/NAME --out OUT [--common-setting '{"weight": ...}'] [--weight-candidates]
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--finetune", type=Path, required=True)
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--threads", type=int, required=True)
    parser.add_argument("--run", type=Path, required=True, help="the output folder of evaluate.py for this arm")
    parser.add_argument("--common-setting", help="a setting as JSON, shared by every coefficient of a base")
    parser.add_argument("--weight-candidates", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    sys.path.insert(0, str(arguments.finetune / "scripts" / "lm-rerank"))
    sys.path.insert(0, str(arguments.finetune / "scripts" / "lm-finetune"))
    import evaluate
    import rerank

    result = json.loads((arguments.run / "result.json").read_text(encoding="utf-8"))
    if result["model"] != arguments.model.name:
        raise SystemExit(f"result.json is of {result['model']}, not of {arguments.model.name}")
    data = arguments.finetune / "build" / "lm-finetune" / "data"
    sets = {"stop": rerank.load_cases([data / "cases.stop.jsonl"]), "dev": rerank.load_cases(rerank.CASE_FILES),
            "published_dev": rerank.load_cases([evaluate.PUBLISHED_DEV])}
    for name, split in (("stop", "stop"), ("dev", "dev"), ("published_dev", "dev")):
        if any(case["split"] != split for case in sets[name]):
            raise SystemExit(f"a case outside the {split} split in {name}")
    engine = rerank.Engine(arguments.shim, rerank.LEXICON)
    scorer = rerank.LanguageModel(arguments.lm, arguments.model, arguments.threads, result["no_context"],
                                  result["prompt_format"])
    for line in (arguments.run / "lm-scores.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        context, candidates, opens_field, typed = entry["key"]
        scorer.cache[(context, tuple(candidates), opens_field, typed)] = {c: tuple(v) for c, v in entry["scores"].items()}
    cached = len(scorer.cache)
    arguments.out.mkdir(parents=True, exist_ok=True)

    summary = {"name": result["name"], "model": result["model"], "cases": {name: len(cases) for name, cases in sets.items()},
               "control": {}}
    for name, cases in sets.items():
        predictions = rerank.run(cases, engine, rerank.engine_choice)
        evaluate.write_predictions(arguments.out / f"control.{name}.jsonl", predictions)
        summary["control"][name] = rerank.summarize(cases, predictions)

    tuned_setting = result["tuning"]["setting"]
    summary["tuned"] = evaluate.score_at(tuned_setting, {"stop": sets["stop"]}, engine, scorer, arguments.out, "tuned")
    print("tuned", json.dumps({"setting": tuned_setting, "stop": summary["tuned"]["stop"]["right"]}), flush=True)

    if arguments.common_setting:
        common = json.loads(arguments.common_setting)
        summary["common"] = evaluate.score_at(common, sets, engine, scorer, arguments.out, "common")
        print("common", json.dumps({"setting": common, **{n: summary["common"][n]["right"] for n in sets}}), flush=True)

    if arguments.weight_candidates:
        tune_cases = rerank.load_cases([data / "cases.tune.jsonl"])
        tune_control = rerank.summarize(tune_cases, rerank.run(tune_cases, engine, rerank.engine_choice))
        rows = evaluate.grid(tune_cases, engine, scorer, "tune grid")
        whole = rerank.tune(rows, tune_control)["tuned"]
        if whole["setting"] != tuned_setting:
            raise SystemExit(f"the grid gives {whole['setting']}, and evaluate.py gave {tuned_setting}")
        summary["weight_candidates"] = []
        for weight in rerank.GRID["weight"]:
            allowed = [row for row in rows if row["setting"]["weight"] == weight and rerank.keeps_clean(row["summary"], tune_control)]
            if not allowed:
                summary["weight_candidates"].append({"weight": weight, "setting": None})
                continue
            best = max(allowed, key=lambda row: row["summary"]["right"])
            entry = evaluate.score_at(best["setting"], sets, engine, scorer, arguments.out, f"weight-{weight}")
            entry["weight"] = weight
            entry["tune"] = best["summary"]
            summary["weight_candidates"].append(entry)
            print("weight candidate", json.dumps({"setting": best["setting"], "tune": best["summary"]["right"],
                                                  **{n: entry[n]["right"] for n in sets}}), flush=True)

    summary["lm_cached_requests"] = cached
    summary["lm_new_requests"] = scorer.requests
    scorer.close()
    (arguments.out / "extra.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

"""Scores one arm of the fine-tune comparison on the tuning split and the dev half.

The arm's setting (weight, margins, space-after switch) comes from the grid of
scripts/lm-rerank/rerank.py on the tuning split, with the clean rule of rerank.py. Dev then
scores the arm at that setting: the generated dev cases (english.dev.jsonl and
english-symbols.dev.jsonl) and, apart, the published misspellings of the dev half. The
within-dev check repeats the grid on dev and the two-fold check of rerank.py. The test half is
never read here (read_test.py reads it once).

Each case is typed through the keyboard rules of rerank.py with the arm's own choices, so a
choice at one correction changes the readings of the next.

An arm is one of:
- a language model (--lm and --model), in the stock or the typed format (--prompt-format);
- the linear listwise chooser of linear_features.py (--features);
- the margins alone (neither).

Usage, from the repository root, on Linux:
    python3 scripts/lm-finetune/evaluate.py --shim build/lm-rerank/libduo_shim.so \
        --lm build/lm-rerank/lm_score --model MODEL.gguf --prompt-format typed --threads 4 \
        --data build/lm-finetune/data --name NAME --out build/lm-finetune/results/NAME
"""
import argparse
import itertools
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune"))
import rerank  # noqa: E402
from features import FeatureScorer  # noqa: E402

PUBLISHED_DEV = ROOT / "build" / "typing-evaluation" / "external" / "english.dev.jsonl"
# The setting of scripts/lm-rerank/README.md, tuned on dev for distilgpt2 Q3_K_M.
PUBLISHED_SETTING = {"weight": 1.0, "margin_from_typed": 24, "margin_to_typed": 0, "margin_other": 2, "space_after": 1}


def settings_of(scorer) -> list[rerank.Setting]:
    if scorer is None:
        return [rerank.Setting(0.0, *values, 0) for values in itertools.product(
            rerank.GRID["margin_from_typed"], rerank.GRID["margin_to_typed"], rerank.GRID["margin_other"])]
    return [rerank.Setting(*values) for values in itertools.product(*rerank.GRID.values())]


def grid(cases, engine, scorer, label: str) -> list[dict]:
    rows = []
    started = time.monotonic()
    settings = settings_of(scorer)
    for index, setting in enumerate(settings):
        predictions = rerank.run(cases, engine, rerank.setting_chooser(setting, scorer))
        rows.append({"setting": setting.__dict__, "summary": rerank.summarize(cases, predictions)})
        if index % 200 == 0:
            print(f"{label}: setting {index + 1} of {len(settings)}, {time.monotonic() - started:.0f} s", flush=True)
    return rows


def write_predictions(path: Path, predictions: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for case_id, output in predictions.items():
            file.write(json.dumps({"id": case_id, "output": output}) + "\n")


def score_at(setting: dict, cases_by_set: dict, engine, scorer, out: Path, label: str) -> dict:
    chooser = rerank.setting_chooser(rerank.Setting(**setting), scorer)
    result = {"setting": setting}
    for name, cases in cases_by_set.items():
        predictions = rerank.run(cases, engine, chooser)
        write_predictions(out / f"{label}.{name}.jsonl", predictions)
        result[name] = rerank.summarize(cases, predictions)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--prompt-format", choices=rerank.PROMPT_FORMATS)
    parser.add_argument("--no-context", action="store_true")
    parser.add_argument("--features", type=Path, help="the weights file of linear_features.py")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--fixed-setting", action="store_true",
                        help="score dev at the published setting too, before any tuning (for the conversion check)")
    parser.add_argument("--skip-dev-grid", action="store_true")
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.lm is None) != (arguments.model is None):
        raise SystemExit("--lm and --model go together")
    if arguments.model is not None and arguments.prompt_format is None:
        raise SystemExit("a model arm needs --prompt-format")
    if arguments.model is not None and arguments.features is not None:
        raise SystemExit("an arm has a model or features, not both")

    tune_cases = rerank.load_cases([arguments.data / "cases.tune.jsonl"])
    dev_cases = rerank.load_cases(rerank.CASE_FILES)
    if not PUBLISHED_DEV.exists():
        raise SystemExit(f"{PUBLISHED_DEV} is missing: run scripts/typing-evaluation/build_external_english_cases.py")
    published_cases = rerank.load_cases([PUBLISHED_DEV])
    for cases, split in ((tune_cases, "tune"), (dev_cases, "dev"), (published_cases, "dev")):
        if any(case["split"] != split for case in cases):
            raise SystemExit(f"a case outside the {split} split")
    engine = rerank.Engine(arguments.shim, rerank.LEXICON)
    arguments.out.mkdir(parents=True, exist_ok=True)

    scorer = None
    if arguments.model is not None:
        scorer = rerank.LanguageModel(arguments.lm, arguments.model, arguments.threads, arguments.no_context,
                                      arguments.prompt_format)
    elif arguments.features is not None:
        scorer = FeatureScorer(json.loads(arguments.features.read_text(encoding="utf-8")))

    result = {"name": arguments.name, "model": arguments.model and arguments.model.name,
              "prompt_format": arguments.prompt_format, "no_context": arguments.no_context,
              "features": arguments.features and str(arguments.features),
              "cases": {"tune": len(tune_cases), "dev": len(dev_cases), "published_dev": len(published_cases)}}
    sets = {"dev": dev_cases, "published_dev": published_cases}
    started = time.monotonic()

    controls = {}
    for name, cases in (("tune", tune_cases), *sets.items()):
        predictions = rerank.run(cases, engine, rerank.engine_choice)
        write_predictions(arguments.out / f"control.{name}.jsonl", predictions)
        controls[name] = rerank.summarize(cases, predictions)
        target = {case["id"]: (case["context"] + " " if case["context"] else "") + case["intended"].strip().lower() + " "
                  for case in cases}
        oracle = {case["id"]: rerank.type_case(case, engine, rerank.oracle_chooser(target[case["id"]])) for case in cases}
        controls[f"oracle_{name}"] = rerank.summarize(cases, oracle)
    result["control"] = controls
    print("control", json.dumps({name: entry["right"] for name, entry in controls.items()}), flush=True)

    if arguments.fixed_setting:
        result["published_setting"] = score_at(PUBLISHED_SETTING, sets, engine, scorer, arguments.out, "published-setting")
        print("published setting", json.dumps({n: result["published_setting"][n]["right"] for n in sets}), flush=True)

    tune_rows = grid(tune_cases, engine, scorer, "tune grid")
    tuned = rerank.tune(tune_rows, controls["tune"])
    if tuned["tuned"] is None:
        raise SystemExit("no setting keeps the clean groups of the tuning split")
    result["tuning"] = {"settings_tried": tuned["settings_tried"], "settings_keeping_clean": tuned["settings_keeping_clean"],
                        "setting": tuned["tuned"]["setting"], "tune": tuned["tuned"]["summary"]}
    result["tuned"] = score_at(tuned["tuned"]["setting"], sets, engine, scorer, arguments.out, "tuned")
    print("tuned", json.dumps({"setting": tuned["tuned"]["setting"], "tune": tuned["tuned"]["summary"]["right"],
                               **{n: result["tuned"][n]["right"] for n in sets}}), flush=True)

    if not arguments.skip_dev_grid:
        dev_rows = grid(dev_cases, engine, scorer, "dev grid")
        within = rerank.tune(dev_rows, controls["dev"])
        result["within_dev"] = {"setting": within["tuned"]["setting"], "dev": within["tuned"]["summary"],
                                "fold_check": within["fold_check"]}
        print("within dev", json.dumps({"setting": within["tuned"]["setting"], "right": within["tuned"]["summary"]["right"],
                                        "fold_check": within["fold_check"]}), flush=True)

    result["seconds"] = round(time.monotonic() - started, 1)
    if isinstance(scorer, rerank.LanguageModel):
        result["lm_ready"] = scorer.ready
        result["lm_requests"] = scorer.requests
        result["lm_seconds"] = round(scorer.seconds, 1)
        with (arguments.out / "lm-scores.jsonl").open("w", encoding="utf-8") as file:
            for key, scores in scorer.cache.items():
                file.write(json.dumps({"key": list(key), "scores": scores}) + "\n")
        result["lm_report"] = scorer.close()
        print(result["lm_report"], flush=True)
    (arguments.out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

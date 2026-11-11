"""Chooses the setting of one arm on the tuning sets of round 2, then scores the arm on the selection sets.

Tuning sets: the tuning split of round 1 (cases.tune.jsonl, generated cases) and the clean running
text of the tune bucket (cases.stream.tune.jsonl). The grid is the grid of scripts/lm-rerank/rerank.py.
A setting is allowed when it
- keeps as many right cases as the control in the groups clean and clean symbols (the rule of round 1), and
- changes at most as many words of the clean running text as the control (new in round 2).
The allowed setting with the most right generated tuning cases is the arm's setting. The result
also names the setting of the round 1 rule alone, with its count of changed words.

Selection sets, scored at the chosen setting and at every --also setting: the generated dev half,
the published misspellings of the dev half, the clean running text of the select bucket and the
GitHub typos of the select half. The held-out set is never read here (read_holdout.py reads it once).

Usage, from the repository root, on Linux:
    python3 scripts/lm-finetune2/evaluate2.py --shim SHIM --lm LM_SCORE --model MODEL.gguf --prompt-format typed \
        --round1 ROUND1_WORKTREE --data build/lm-finetune2/data --name NAME --out OUT
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune2"))
import evaluate as r1_evaluate  # noqa: E402
import metrics2  # noqa: E402
import rerank  # noqa: E402
from features import FeatureScorer  # noqa: E402


def allowed(summary: dict, control: dict) -> dict:
    groups = all(summary["generated"]["groups"][g]["right"] >= control["generated"]["groups"][g]["right"]
                 for g in ("clean", "clean_symbols"))
    stream = summary["stream"]["stream"]["changed_words"] <= control["stream"]["stream"]["changed_words"]
    return {"round1_rule": groups, "round2_rule": groups and stream}


def run_sets(sets: dict, engine, chooser) -> tuple[dict, dict]:
    predictions = {name: rerank.run(cases, engine, chooser) for name, cases in sets.items()}
    return predictions, {name: metrics2.summarize(sets[name], predictions[name]) for name in sets}


def parse_setting(text: str) -> tuple[str, dict]:
    name, values = text.split("=")
    weight, from_typed, to_typed, other, space_after = values.split(",")
    return name, {"weight": float(weight), "margin_from_typed": float(from_typed), "margin_to_typed": float(to_typed),
                  "margin_other": float(other), "space_after": int(space_after)}


def load_sets(round1: Path, data: Path) -> tuple[dict, dict]:
    tune_sets = {"generated": rerank.load_cases([round1 / "build" / "lm-finetune" / "data" / "cases.tune.jsonl"]),
                 "stream": rerank.load_cases([data / "cases.stream.tune.jsonl"])}
    select_sets = {"dev": rerank.load_cases(rerank.CASE_FILES),
                   "published_dev": rerank.load_cases([round1 / "build" / "typing-evaluation" / "external" / "english.dev.jsonl"]),
                   "stream": rerank.load_cases([data / "cases.stream.select.jsonl"]),
                   "github": rerank.load_cases([data / "cases.github.select.jsonl"])}
    for sets, splits in ((tune_sets, {"tune"}), (select_sets, {"dev", "select"})):
        for cases in sets.values():
            if any(case["split"] not in splits for case in cases):
                raise SystemExit(f"a case outside {splits}")
    return tune_sets, select_sets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--prompt-format", choices=rerank.PROMPT_FORMATS)
    parser.add_argument("--features", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--round1", type=Path, required=True, help="the worktree of round 1, read only")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--also", action="append", default=[], help="NAME=weight,from_typed,to_typed,other,space_after")
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.lm is None) != (arguments.model is None):
        raise SystemExit("--lm and --model go together")
    if arguments.model is not None and arguments.prompt_format is None:
        raise SystemExit("a model arm needs --prompt-format")
    if (arguments.out / "result.json").exists():
        raise SystemExit(f"{arguments.out} already holds a result")

    tune_sets, select_sets = load_sets(arguments.round1, arguments.data)
    engine = rerank.Engine(arguments.shim, rerank.LEXICON)
    arguments.out.mkdir(parents=True, exist_ok=True)
    scorer = None
    if arguments.model is not None:
        scorer = rerank.LanguageModel(arguments.lm, arguments.model, arguments.threads, False, arguments.prompt_format)
    elif arguments.features is not None:
        scorer = FeatureScorer(json.loads(arguments.features.read_text(encoding="utf-8")))
    result = {"name": arguments.name, "model": arguments.model and arguments.model.name, "prompt_format": arguments.prompt_format,
              "features": arguments.features and arguments.features.name}
    started = time.monotonic()

    _, tune_control = run_sets(tune_sets, engine, rerank.engine_choice)
    select_predictions, select_control = run_sets(select_sets, engine, rerank.engine_choice)
    result["control"] = {"tune": tune_control, "select": select_control}
    for name, predictions in select_predictions.items():
        r1_evaluate.write_predictions(arguments.out / f"control.{name}.jsonl", predictions)

    rows = []
    settings = r1_evaluate.settings_of(scorer)
    for index, setting in enumerate(settings):
        _, summary = run_sets(tune_sets, engine, rerank.setting_chooser(setting, scorer))
        rows.append({"setting": setting.__dict__, "right": summary["generated"]["right"],
                     "groups": {g: e["right"] for g, e in summary["generated"]["groups"].items()},
                     "changed_words": summary["stream"]["stream"]["changed_words"], **allowed(summary, tune_control)})
        if index % 200 == 0:
            print(f"tune grid: setting {index + 1} of {len(settings)}, {time.monotonic() - started:.0f} s", flush=True)
    with (arguments.out / "grid.jsonl").open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row) + "\n")
    chosen = {}
    for rule in ("round1_rule", "round2_rule"):
        passing = [row for row in rows if row[rule]]
        if not passing:
            raise SystemExit(f"no setting passes the {rule}")
        chosen[rule] = max(passing, key=lambda row: row["right"])
    result["tuning"] = {"settings_tried": len(rows), "settings_allowed": sum(row["round2_rule"] for row in rows),
                        "setting": chosen["round2_rule"]["setting"], "tune": chosen["round2_rule"],
                        "round1_rule": chosen["round1_rule"]}
    print("tuned", json.dumps(result["tuning"]), flush=True)

    result["select"] = {}
    for label, setting in [("tuned", chosen["round2_rule"]["setting"]), *[parse_setting(text) for text in arguments.also]]:
        predictions, summary = run_sets(select_sets, engine, rerank.setting_chooser(rerank.Setting(**setting), scorer))
        for name, rows_of_set in predictions.items():
            r1_evaluate.write_predictions(arguments.out / f"{label}.{name}.jsonl", rows_of_set)
        _, tune_summary = run_sets(tune_sets, engine, rerank.setting_chooser(rerank.Setting(**setting), scorer))
        result["select"][label] = {"setting": setting, "sets": summary, "tune": tune_summary}
        print(label, json.dumps({"setting": setting, **{name: entry["right"] for name, entry in summary.items()},
                                 "stream_changed_words": summary["stream"]["stream"]["changed_words"]}), flush=True)

    result["seconds"] = round(time.monotonic() - started, 1)
    if isinstance(scorer, rerank.LanguageModel):
        result.update({"lm_ready": scorer.ready, "lm_requests": scorer.requests, "lm_seconds": round(scorer.seconds, 1)})
        result["lm_report"] = scorer.close()[-400:]
    (arguments.out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

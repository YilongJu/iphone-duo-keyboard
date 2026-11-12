"""Scores one model file on every evaluation set of the domain round, with the work area on.

One command does four things for a GGUF file:
1. It types every evaluation set with the engine alone and with a perfect chooser. The perfect
   chooser takes the intended reading whenever the engine lists it, so its count is the ceiling
   of any re-ranker on that set.
2. It scores the 2,160 settings of the grid on the tuning sets, and chooses one setting per rule
   of select_setting.py: the shipped setting, the control rule, and the two ceilings on changed
   correct words.
3. It types every evaluation set with the model at each chosen setting.
4. It writes, per set, the right cases, the ceiling and the share of the gap that the model
   closes: (model - engine alone) / (perfect chooser - engine alone). For clean running text
   the perfect chooser changes 0 words, so the share is 1 - model changed / engine changed.

The evaluation sets (harness.load_sets): the generated dev half, the apostrophe words, the
published dev misspellings, the clean running text of the select bucket, the GitHub typos of the
select half, the dev half and the test half of the domain cases, and their clean running text.
The tuning sets: the generated tuning cases of round 1 and the clean running text of the tune
bucket. A held-out set is never read here.

Without --model the script writes the engine alone and the perfect chooser only.
The script keeps every answer of lm_score in OUT/answers.jsonl and every grid row in
OUT/grid.jsonl, so a run that stops goes on from these files when it starts again.

Usage, from the repository root, on Linux:
    LD_LIBRARY_PATH=$HOME/lmft/llama/lib python3 scripts/lm-domain/score_model.py \
        --shim $HOME/lmdom/bin/libduo_shim.so --lm $HOME/lmdom/bin/lm_score --model MODEL.gguf \
        --data build/lm-domain/data --name NAME --out build/lm-domain/results/NAME
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-domain"))
import harness  # noqa: E402
import select_setting  # noqa: E402
import rerank  # noqa: E402

DOMAIN_SETS = ("domain_dev", "domain_stream_dev", "domain_test", "domain_stream_test")


def run_sets(sets: dict, typist: harness.Typist, chooser, perfect: bool = False) -> tuple[dict, dict]:
    outputs, summaries = {}, {}
    for name, entry in sets.items():
        outputs[name] = typist.run_perfect(entry["cases"]) if perfect else typist.run(entry["cases"], chooser)
        summaries[name] = harness.summarize(entry["kind"], entry["cases"], outputs[name])
    return outputs, summaries


def write_outputs(path: Path, outputs: dict) -> None:
    with path.open("w", encoding="utf-8") as file:
        for name, values in outputs.items():
            for case_id, output in values.items():
                file.write(json.dumps({"set": name, "id": case_id, "output": output}) + "\n")


def gap_closed(model: dict, engine: dict, perfect: dict) -> dict:
    """The share of the gap between the engine alone and the perfect chooser that the model
    closes, for a set and for each of its groups. None when the gap is 0."""
    def share(got: int, low: int, high: int) -> float | None:
        return None if high == low else round((got - low) / (high - low), 4)

    if "changed_words" in model:
        result = {"all": None if engine["changed_words"] == 0 else round(1 - model["changed_words"] / engine["changed_words"], 4)}
        for name, entry in model["streams"].items():
            low = engine["streams"][name]["changed_words"]
            result[name] = None if low == 0 else round(1 - entry["changed_words"] / low, 4)
        return result
    result = {"all": share(model["right"], engine["right"], perfect["right"])}
    for name, (right, _) in model.get("groups", model["categories"]).items():
        table = "groups" if "groups" in model else "categories"
        result[name] = share(right, engine[table][name][0], perfect[table][name][0])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.lm is None) != (arguments.model is None):
        raise SystemExit("--lm and --model go together")
    if (arguments.out / "result.json").exists():
        raise SystemExit(f"{arguments.out} already holds a result")
    arguments.out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    def note(text: str) -> None:
        print(f"{time.monotonic() - started:7.0f} s  {text}", flush=True)

    tune_sets = harness.load_sets(arguments.data, "tune")
    evaluation_sets = harness.load_sets(arguments.data, "evaluation")
    readings_file = arguments.data / "engine-readings.pickle"
    typist = harness.Typist(arguments.shim, readings_file=readings_file)
    result = {"name": arguments.name, "model": arguments.model and arguments.model.name,
              "sets": {name: {"kind": entry["kind"], "cases": len(entry["cases"])}
                       for name, entry in {**tune_sets, **evaluation_sets}.items()}}

    # ---- The engine alone and the perfect chooser ----
    _, tune_engine = run_sets(tune_sets, typist, rerank.engine_choice)
    engine_outputs, engine = run_sets(evaluation_sets, typist, rerank.engine_choice)
    perfect_outputs, perfect = run_sets(evaluation_sets, typist, None, perfect=True)
    write_outputs(arguments.out / "outputs.engine.jsonl", engine_outputs)
    write_outputs(arguments.out / "outputs.perfect.jsonl", perfect_outputs)
    result["engine"] = {"tune": tune_engine, "evaluation": engine}
    result["perfect"] = {"evaluation": perfect}
    typist.save_readings()
    note("engine alone and perfect chooser: " + json.dumps({name: [engine[name].get("changed_words", engine[name]["right"]),
                                                                  perfect[name].get("changed_words", perfect[name]["right"])]
                                                             for name in evaluation_sets}))
    if arguments.model is None:
        (arguments.out / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        return

    scorer, stored, digest = harness.open_model(arguments.lm, arguments.model, arguments.threads, arguments.out / "answers.jsonl")
    result.update({"model_sha256": digest, "lm_ready": scorer.ready, "answers_stored_before": stored.loaded})
    note(f"model {arguments.model.name} {digest[:12]}, {stored.loaded} stored answers")

    # ---- The grid on the tuning sets ----
    grid_path = arguments.out / "grid.jsonl"
    rows = []
    if grid_path.exists():
        rows = [json.loads(line) for line in grid_path.read_text(encoding="utf-8").splitlines() if line.endswith("}")]
    settings = harness.grid_settings()
    for index, row in enumerate(rows):
        if not select_setting.same_setting(row["setting"], settings[index]):
            raise SystemExit(f"{grid_path} does not follow the grid at row {index}")
    with grid_path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row) + "\n")
        for index in range(len(rows), len(settings)):
            _, summary = run_sets(tune_sets, typist, rerank.setting_chooser(harness.setting_of(settings[index]), scorer))
            row = {"setting": settings[index], "right": summary["tune_generated"]["right"],
                   "groups": {name: value[0] for name, value in summary["tune_generated"]["groups"].items()},
                   "changed_words": summary["tune_stream"]["changed_words"]}
            rows.append(row)
            file.write(json.dumps(row) + "\n")
            file.flush()
            if index % 200 == 0:
                note(f"tune grid: setting {index + 1} of {len(settings)}, {stored.asked} new answers of lm_score")
    words = tune_engine["tune_stream"]["words"]
    control = {"clean": tune_engine["tune_generated"]["groups"]["clean"][0],
               "clean_symbols": tune_engine["tune_generated"]["groups"]["clean_symbols"][0],
               "changed_words": tune_engine["tune_stream"]["changed_words"]}
    chosen = select_setting.select(rows, words, control)
    result["tuning"] = {"words": words, "control": control, "settings_tried": len(rows),
                        "rules": {rule: {"allowed": entry["allowed"], "limit_changed_words": entry.get("limit_changed_words"),
                                         "setting": entry["row"] and entry["row"]["setting"],
                                         "tune_right": entry["row"] and entry["row"]["right"],
                                         "tune_groups": entry["row"] and entry["row"]["groups"],
                                         "tune_changed_words": entry["row"] and entry["row"]["changed_words"]}
                                  for rule, entry in chosen.items()},
                        "frontier": select_setting.frontier(rows)}
    note("settings: " + json.dumps({rule: [entry["setting"], entry["tune_right"], entry["tune_changed_words"]]
                                    for rule, entry in result["tuning"]["rules"].items()}))

    # ---- Every evaluation set at each chosen setting ----
    result["evaluation"] = {}
    done: list[tuple[dict, str]] = []
    for rule, entry in result["tuning"]["rules"].items():
        setting = entry["setting"]
        if setting is None:
            result["evaluation"][rule] = None
            continue
        earlier = next((name for values, name in done if select_setting.same_setting(values, setting)), None)
        if earlier is not None:
            result["evaluation"][rule] = {"same_setting_as": earlier}
            continue
        outputs, summaries = run_sets(evaluation_sets, typist, rerank.setting_chooser(harness.setting_of(setting), scorer))
        write_outputs(arguments.out / f"outputs.{rule}.jsonl", outputs)
        result["evaluation"][rule] = {"setting": setting, "sets": summaries,
                                      "gap_closed": {name: gap_closed(summaries[name], engine[name], perfect[name])
                                                     for name in evaluation_sets}}
        done.append((setting, rule))
        note(f"{rule}: " + json.dumps({name: summaries[name].get("changed_words", summaries[name]["right"]) for name in evaluation_sets}))

    # ---- The domain sets without the protection of a typed new word, at the shipped setting ----
    typist.save_readings()
    free = harness.Typist(arguments.shim, protect_new_words=False, readings_file=readings_file)
    domain_sets = {name: evaluation_sets[name] for name in DOMAIN_SETS}
    shipped = harness.setting_of(result["tuning"]["rules"]["shipped"]["setting"])
    outputs, summaries = run_sets(domain_sets, free, rerank.setting_chooser(shipped, scorer))
    _, free_perfect = run_sets(domain_sets, free, None, perfect=True)
    write_outputs(arguments.out / "outputs.shipped-unprotected.jsonl", outputs)
    result["unprotected"] = {"shipped": summaries, "perfect": free_perfect}
    note("shipped setting without the protection: " + json.dumps({name: summaries[name].get("changed_words", summaries[name]["right"])
                                                                  for name in domain_sets}))

    result.update({"seconds": round(time.monotonic() - started, 1), "lm_requests": scorer.requests,
                   "lm_answers_new": stored.asked, "lm_seconds": round(scorer.seconds, 1)})
    result["lm_report"] = scorer.close()[-400:]
    (arguments.out / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    note("done")


if __name__ == "__main__":
    main()

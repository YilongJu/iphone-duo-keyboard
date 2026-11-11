"""Reads the test half once, for the arms and the settings that test-plan.json fixes.

The plan is committed before the read, and the script refuses to write into a folder that holds
a result, so the test half gives one number per arm. Each arm types every test case through the
keyboard rules of scripts/lm-rerank/rerank.py at its fixed setting: the generated test cases
(english.test.jsonl and english-symbols.test.jsonl) and, apart, the published misspellings of the
test half.

Usage, from the repository root, on Linux:
    python3 scripts/lm-finetune/read_test.py --plan scripts/lm-finetune/test-plan.json \
        --shim build/lm-rerank/libduo_shim.so --lm build/lm-rerank/lm_score --models DIR \
        --out build/lm-finetune/results/test
"""
import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune"))
import rerank  # noqa: E402
from features import FeatureScorer  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
TEST_FILES = [CASES / "english.test.jsonl", CASES / "english-symbols.test.jsonl"]
PUBLISHED_TEST = ROOT / "build" / "typing-evaluation" / "external" / "english.test.jsonl"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True, help="the folder that holds the model files the plan names")
    parser.add_argument("--threads", type=int, default=2, help="threads of each lm_score")
    parser.add_argument("--workers", type=int, default=2, help="arms read at the same time")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.out / "result.json").exists():
        raise SystemExit(f"{arguments.out} already holds the test read")

    plan = json.loads(arguments.plan.read_text(encoding="utf-8"))
    for arm in plan["arms"]:
        for key in ("model", "features"):
            if arm.get(key) is not None and not (arguments.models / arm[key]).exists():
                raise SystemExit(f"the file {arm[key]} of {arm['name']} is missing")
    for cases in load_sets().values():
        if any(case["split"] != "test" for case in cases):
            raise SystemExit("a case outside the test half")
    arguments.out.mkdir(parents=True, exist_ok=True)
    result = {"plan": plan, "cases": {name: len(cases) for name, cases in load_sets().items()}, "arms": {}}
    started = time.monotonic()
    jobs = [(arm, arguments) for arm in plan["arms"]]
    # Each arm runs in its own process with its own engine and scorer.
    with ProcessPoolExecutor(arguments.workers) as pool:
        for name, entry in pool.map(read_arm, jobs):
            result["arms"][name] = entry
            print(name, json.dumps({key: entry[key]["right"] for key in ("test", "published_test")}), flush=True)
    result["seconds"] = round(time.monotonic() - started, 1)
    (arguments.out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


def load_sets() -> dict[str, list[dict]]:
    return {"test": rerank.load_cases(TEST_FILES), "published_test": rerank.load_cases([PUBLISHED_TEST])}


def read_arm(job) -> tuple[str, dict]:
    arm, arguments = job
    engine = rerank.Engine(arguments.shim, rerank.LEXICON)
    if arm["setting"] is None:
        chooser, scorer = rerank.engine_choice, None
    else:
        scorer = None
        if arm["model"] is not None:
            scorer = rerank.LanguageModel(arguments.lm, arguments.models / arm["model"], arguments.threads,
                                          arm["no_context"], arm["prompt_format"])
        elif arm.get("features") is not None:
            scorer = FeatureScorer(json.loads((arguments.models / arm["features"]).read_text(encoding="utf-8")))
        chooser = rerank.setting_chooser(rerank.Setting(**arm["setting"]), scorer)
    entry = {}
    for name, cases in load_sets().items():
        predictions = rerank.run(cases, engine, chooser)
        with (arguments.out / f"{arm['name']}.{name}.jsonl").open("w", encoding="utf-8") as file:
            for case_id, output in predictions.items():
                file.write(json.dumps({"id": case_id, "output": output}) + "\n")
        entry[name] = rerank.summarize(cases, predictions)
    if isinstance(scorer, rerank.LanguageModel):
        entry["lm_report"] = scorer.close()
    return arm["name"], entry


if __name__ == "__main__":
    main()

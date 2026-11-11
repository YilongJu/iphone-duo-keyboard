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
# The dev files, for a dry run of this script before the one read of the test half.
DEV_FILES = [CASES / "english.dev.jsonl", CASES / "english-symbols.dev.jsonl"]
PUBLISHED_DEV = ROOT / "build" / "typing-evaluation" / "external" / "english.dev.jsonl"
HALF = "test"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True, help="the folder that holds the model files the plan names")
    parser.add_argument("--threads", type=int, default=2, help="threads of each lm_score")
    parser.add_argument("--workers", type=int, default=2, help="arms read at the same time")
    parser.add_argument("--dry-run-on-dev", action="store_true", help="read the dev half instead, to check this script")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.out / "result.json").exists():
        raise SystemExit(f"{arguments.out} already holds the test read")
    global HALF
    HALF = "dev" if arguments.dry_run_on_dev else "test"

    plan = json.loads(arguments.plan.read_text(encoding="utf-8"))
    for arm in plan["arms"]:
        for key in ("model", "features"):
            if arm.get(key) is not None and not (arguments.models / arm[key]).exists():
                raise SystemExit(f"the file {arm[key]} of {arm['name']} is missing")
    for cases in load_sets().values():
        if any(case["split"] != HALF for case in cases):
            raise SystemExit(f"a case outside the {HALF} half")
    arguments.out.mkdir(parents=True, exist_ok=True)
    result = {"plan": plan, "cases": {name: len(cases) for name, cases in load_sets().items()}, "arms": {}}
    started = time.monotonic()
    # The arms that share a model file run in one process, so their settings share the model's
    # scores. Each group has its own engine and scorer.
    groups: dict[tuple, list[dict]] = {}
    for arm in plan["arms"]:
        groups.setdefault((arm["model"], arm.get("features"), arm["prompt_format"], arm["no_context"]), []).append(arm)
    jobs = [(arms, arguments) for arms in groups.values()]
    with ProcessPoolExecutor(arguments.workers) as pool:
        for entries in pool.map(read_group, jobs):
            for name, entry in entries:
                result["arms"][name] = entry
                print(name, json.dumps({key: entry[key]["right"] for key in ("test", "published_test")}), flush=True)
    result["arms"] = {arm["name"]: result["arms"][arm["name"]] for arm in plan["arms"]}
    result["seconds"] = round(time.monotonic() - started, 1)
    (arguments.out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


def load_sets() -> dict[str, list[dict]]:
    """The generated cases and the published misspellings of the half, under the names "test"
    and "published_test" also in a dry run on dev."""
    if HALF == "dev":
        return {"test": rerank.load_cases(DEV_FILES), "published_test": rerank.load_cases([PUBLISHED_DEV])}
    return {"test": rerank.load_cases(TEST_FILES), "published_test": rerank.load_cases([PUBLISHED_TEST])}


def read_group(job) -> list[tuple[str, dict]]:
    arms, arguments = job
    global HALF
    HALF = "dev" if arguments.dry_run_on_dev else "test"
    engine = rerank.Engine(arguments.shim, rerank.LEXICON)
    first = arms[0]
    scorer = None
    if first["model"] is not None:
        scorer = rerank.LanguageModel(arguments.lm, arguments.models / first["model"], arguments.threads,
                                      first["no_context"], first["prompt_format"])
    elif first.get("features") is not None:
        scorer = FeatureScorer(json.loads((arguments.models / first["features"]).read_text(encoding="utf-8")))
    sets = load_sets()
    entries = []
    for arm in arms:
        if arm["setting"] is None:
            chooser = rerank.engine_choice
        else:
            chooser = rerank.setting_chooser(rerank.Setting(**arm["setting"]), scorer)
        entry = {}
        for name, cases in sets.items():
            predictions = rerank.run(cases, engine, chooser)
            with (arguments.out / f"{arm['name']}.{name}.jsonl").open("w", encoding="utf-8") as file:
                for case_id, output in predictions.items():
                    file.write(json.dumps({"id": case_id, "output": output}) + "\n")
            entry[name] = rerank.summarize(cases, predictions)
        entries.append((arm["name"], entry))
    if isinstance(scorer, rerank.LanguageModel):
        report = scorer.close()
        for _, entry in entries:
            entry["lm_report"] = report
    return entries


if __name__ == "__main__":
    main()

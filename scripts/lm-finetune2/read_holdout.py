"""Reads the held-out set of round 2 once, for the arms and the settings that holdout-plan.json fixes.

The plan is committed before the read, and the script refuses to write into a folder that holds a
result. Each arm types every case through the keyboard rules of scripts/lm-rerank/rerank.py at its
fixed setting. The four held-out sets:
- generated: 24 categories from fresh Tatoeba sentences (cases.generated.holdout.jsonl),
- stream: clean running text (cases.stream.holdout.jsonl),
- github: real typos from the GitHub Typo Corpus (cases.github.holdout.jsonl),
- mitton: the Birkbeck and Holbrook pairs that round 1 did not sample (cases.mitton-remainder.holdout.jsonl).

Arms that share a model file run in one process. Each set gets its own scorer process, so the
result holds the tokens and the time of the model per set.

Usage, from the repository root, on Linux:
    python3 scripts/lm-finetune2/read_holdout.py --plan scripts/lm-finetune2/holdout-plan.json \
        --shim SHIM --lm LM_SCORE --models DIR --models DIR2 --data build/lm-finetune2/data --out OUT
"""
import argparse
import json
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune2"))
import metrics2  # noqa: E402
import rerank  # noqa: E402
from features import FeatureScorer  # noqa: E402

HOLDOUT_FILES = {"generated": "cases.generated.holdout.jsonl", "stream": "cases.stream.holdout.jsonl",
                 "github": "cases.github.holdout.jsonl", "mitton": "cases.mitton-remainder.holdout.jsonl"}
# The selection sets with the same shapes, for a dry run of this script before the one read.
DRY_RUN_FILES = {"stream": "cases.stream.select.jsonl", "github": "cases.github.select.jsonl"}


def load_sets(data: Path, dry_run: bool) -> dict[str, list[dict]]:
    files = DRY_RUN_FILES if dry_run else HOLDOUT_FILES
    sets = {name: rerank.load_cases([data / file]) for name, file in files.items()}
    wanted = "select" if dry_run else "holdout"
    for cases in sets.values():
        if any(case["split"] != wanted for case in cases):
            raise SystemExit(f"a case outside the {wanted} split")
    return sets


def find(folders: list[Path], name: str) -> Path:
    matches = [folder / name for folder in folders if (folder / name).exists()]
    if len(matches) != 1:
        raise SystemExit(f"the file {name} is in {len(matches)} of the model folders")
    return matches[0]


def read_group(job) -> list[tuple[str, dict]]:
    arms, arguments = job
    engine = rerank.Engine(arguments.shim, rerank.LEXICON)
    first = arms[0]
    sets = load_sets(arguments.data, arguments.dry_run_on_select)
    entries = {arm["name"]: {} for arm in arms}
    for name, cases in sets.items():
        scorer = None
        if first["model"] is not None:
            scorer = rerank.LanguageModel(arguments.lm, find(arguments.models, first["model"]), arguments.threads, False,
                                          first["prompt_format"])
        elif first.get("features") is not None:
            scorer = FeatureScorer(json.loads(find(arguments.models, first["features"]).read_text(encoding="utf-8")))
        for arm in arms:
            chooser = rerank.engine_choice if arm["setting"] is None else rerank.setting_chooser(rerank.Setting(**arm["setting"]), scorer)
            predictions = rerank.run(cases, engine, chooser)
            with (arguments.out / f"{arm['name']}.{name}.jsonl").open("w", encoding="utf-8") as file:
                for case_id, output in predictions.items():
                    file.write(json.dumps({"id": case_id, "output": output}) + "\n")
            entries[arm["name"]][name] = metrics2.summarize(cases, predictions)
        if isinstance(scorer, rerank.LanguageModel):
            requests, seconds = scorer.requests, scorer.seconds
            report = scorer.close()
            tokens = re.search(r"(\d+) tokens read, ([0-9.]+) ms", report)
            memory = re.search(r"highest RssAnon (-?\d+) kB", report)
            if tokens is None or memory is None:
                raise SystemExit(f"lm_score gave no report: {report[-300:]}")
            # The scorer serves every arm of the group, so its counts cover their requests together.
            for arm in arms:
                entries[arm["name"]][name]["model"] = {
                    "arms_sharing_the_scorer": len(arms), "requests": requests, "tokens_read": int(tokens.group(1)),
                    "model_ms": float(tokens.group(2)), "seconds_with_pipe": round(seconds, 1), "rss_anon_kb": int(memory.group(1))}
    return list(entries.items())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path, required=True)
    parser.add_argument("--models", type=Path, action="append", required=True, help="a folder of model files; give it once per folder")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=2, help="threads of each lm_score")
    parser.add_argument("--workers", type=int, default=2, help="model files read at the same time")
    parser.add_argument("--dry-run-on-select", action="store_true", help="read the selection sets instead, to check this script")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.out / "result.json").exists():
        raise SystemExit(f"{arguments.out} already holds the read")

    plan = json.loads(arguments.plan.read_text(encoding="utf-8"))
    names = [arm["name"] for arm in plan["arms"]]
    if len(set(names)) != len(names):
        raise SystemExit("the plan names an arm twice")
    for arm in plan["arms"]:
        for key in ("model", "features"):
            if arm.get(key) is not None:
                find(arguments.models, arm[key])
    sets = load_sets(arguments.data, arguments.dry_run_on_select)
    arguments.out.mkdir(parents=True, exist_ok=True)
    result = {"plan": plan, "dry_run_on_select": arguments.dry_run_on_select,
              "cases": {name: len(cases) for name, cases in sets.items()}, "arms": {}}
    started = time.monotonic()
    groups: dict[tuple, list[dict]] = {}
    for arm in plan["arms"]:
        groups.setdefault((arm["model"], arm.get("features"), arm["prompt_format"]), []).append(arm)
    jobs = [(arms, arguments) for arms in groups.values()]
    with ProcessPoolExecutor(arguments.workers) as pool:
        for entries in pool.map(read_group, jobs):
            for name, entry in entries:
                result["arms"][name] = entry
                print(name, json.dumps({key: value["right"] for key, value in entry.items()}), flush=True)
    result["arms"] = {name: result["arms"][name] for name in names}
    result["seconds"] = round(time.monotonic() - started, 1)
    (arguments.out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

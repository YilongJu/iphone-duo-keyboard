"""Reads the held-out set of round 2 once, for the arms and the settings that holdout-plan.json fixes.

The plan is committed before the read, and the script refuses to write into a folder that holds a
result. Each arm types every case through the keyboard rules of scripts/lm-rerank/rerank.py at its
fixed setting. The four held-out sets:
- generated: 24 categories from fresh Tatoeba sentences (cases.generated.holdout.jsonl),
- stream: clean running text (cases.stream.holdout.jsonl),
- github: real typos from the GitHub Typo Corpus (cases.github.holdout.jsonl),
- mitton: the Birkbeck and Holbrook pairs that round 1 did not use (cases.mitton-remainder.holdout.jsonl).

Arms that share a model file run in one process. Each set gets its own scorer process.

One file per arm and set holds the outputs (ARM.SET.jsonl). The script writes a file under a
temporary name and renames it when it is whole. While the read runs, the script prints file names
only. It counts right cases once, at the end, when every file is whole, and writes result.json.

--resume goes on with a read that stopped before result.json. It keeps every whole file and scores
only the others. A file is whole when it holds one line per case, with the ids of the set in
order. A file that fails this check is deleted and scored again from zero. The check does not
compare an output with an intended text. The plan, the settings and the cases stay as they were:
a typed case depends only on the model file, the setting and the case, so a file scored after a
stop equals the file that the first run would have written.

Usage, from the repository root, on Linux:
    python3 scripts/lm-finetune2/read_holdout.py --plan scripts/lm-finetune2/holdout-plan.json \
        --shim SHIM --lm LM_SCORE --models DIR --models DIR2 --data build/lm-finetune2/data --out OUT [--resume]
"""
import argparse
import datetime
import json
import os
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
READ_LOG = "read-log.jsonl"
MODEL_STATS = "model-stats.jsonl"


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def append_line(path: Path, row: dict) -> None:
    """One line in one write, so the lines of two processes do not mix."""
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(row) + "\n")


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


def read_outputs(path: Path, cases: list[dict]) -> dict[str, str] | None:
    """The outputs of a whole file, or None when the file is missing or not whole. A whole file
    holds one line per case, each with an id and an output, with the ids of the set in order.
    The function does not compare an output with an intended text."""
    if not path.exists():
        return None
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    except json.JSONDecodeError:
        return None
    if len(rows) != len(cases):
        return None
    for row, case in zip(rows, cases):
        if not isinstance(row, dict) or set(row) != {"id", "output"} or row["id"] != case["id"] or not isinstance(row["output"], str):
            return None
    return {row["id"]: row["output"] for row in rows}


def read_group(job) -> list[dict]:
    """Scores the files of one model file that are not whole yet. Returns the file events, without counts."""
    arms, arguments = job
    engine = rerank.Engine(arguments.shim, rerank.LEXICON)
    first = arms[0]
    sets = load_sets(arguments.data, arguments.dry_run_on_select)
    events = []
    for name, cases in sets.items():
        missing = []
        for arm in arms:
            path = arguments.out / f"{arm['name']}.{name}.jsonl"
            if read_outputs(path, cases) is not None:
                event = {"time": now(), "arm": arm["name"], "set": name, "event": "kept"}
            else:
                missing.append(arm)
                if path.exists():
                    path.unlink()
                    append_line(arguments.out / READ_LOG, {"time": now(), "arm": arm["name"], "set": name, "event": "deleted a file that was not whole"})
                continue
            events.append(event)
            append_line(arguments.out / READ_LOG, event)
        if not missing:
            continue
        scorer = None
        if first["model"] is not None:
            scorer = rerank.LanguageModel(arguments.lm, find(arguments.models, first["model"]), arguments.threads, False,
                                          first["prompt_format"])
        elif first.get("features") is not None:
            scorer = FeatureScorer(json.loads(find(arguments.models, first["features"]).read_text(encoding="utf-8")))
        for arm in missing:
            chooser = rerank.engine_choice if arm["setting"] is None else rerank.setting_chooser(rerank.Setting(**arm["setting"]), scorer)
            predictions = rerank.run(cases, engine, chooser)
            path = arguments.out / f"{arm['name']}.{name}.jsonl"
            temporary = arguments.out / f"{arm['name']}.{name}.part"
            with temporary.open("w", encoding="utf-8") as file:
                for case_id, output in predictions.items():
                    file.write(json.dumps({"id": case_id, "output": output}) + "\n")
            os.replace(temporary, path)
            event = {"time": now(), "arm": arm["name"], "set": name, "event": "scored"}
            events.append(event)
            append_line(arguments.out / READ_LOG, event)
        if isinstance(scorer, rerank.LanguageModel):
            requests, seconds = scorer.requests, scorer.seconds
            report = scorer.close()
            tokens = re.search(r"(\d+) tokens read, ([0-9.]+) ms", report)
            memory = re.search(r"highest RssAnon (-?\d+) kB", report)
            if tokens is None or memory is None:
                raise SystemExit(f"lm_score gave no report: {report[-300:]}")
            # The scorer serves every arm scored here, so its counts cover their requests together.
            append_line(arguments.out / MODEL_STATS, {
                "set": name, "arms": [arm["name"] for arm in missing], "requests": requests, "tokens_read": int(tokens.group(1)),
                "model_ms": float(tokens.group(2)), "seconds_with_pipe": round(seconds, 1), "rss_anon_kb": int(memory.group(1))})
    return events


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
    parser.add_argument("--resume", action="store_true", help="go on with a read that stopped: keep the whole files, score the others")
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
    found = sorted(path.name for path in arguments.out.glob("*.jsonl") if path.name not in (READ_LOG, MODEL_STATS))
    known = {f"{name}.{set_name}.jsonl" for name in names for set_name in sets}
    strangers = [name for name in found if name not in known]
    if strangers:
        raise SystemExit(f"{arguments.out} holds files that the plan does not name: {strangers[:5]}")
    if found and not arguments.resume:
        raise SystemExit(f"{arguments.out} holds {len(found)} files of a read that stopped: give --resume to go on with it")
    for path in arguments.out.glob("*.part"):
        path.unlink()
    whole = sum(read_outputs(arguments.out / f"{name}.{set_name}.jsonl", cases) is not None for name in names for set_name, cases in sets.items())
    append_line(arguments.out / READ_LOG, {"time": now(), "event": "start", "resume": arguments.resume, "files_in_the_folder": len(found),
                                           "whole_files": whole, "files_of_the_plan": len(known), "workers": arguments.workers,
                                           "threads": arguments.threads})
    print(f"{now()} start: {whole} of {len(known)} files are whole", flush=True)

    started = time.monotonic()
    groups: dict[tuple, list[dict]] = {}
    for arm in plan["arms"]:
        groups.setdefault((arm["model"], arm.get("features"), arm["prompt_format"]), []).append(arm)
    jobs = [(arms, arguments) for arms in groups.values()]
    with ProcessPoolExecutor(arguments.workers) as pool:
        for events in pool.map(read_group, jobs):
            for event in events:
                print(f"{event['time']} {event['arm']} {event['set']}: {event['event']}", flush=True)

    # Every file is whole now. The counts are made here, once.
    result = {"plan": plan, "dry_run_on_select": arguments.dry_run_on_select,
              "cases": {name: len(cases) for name, cases in sets.items()}, "arms": {}}
    for name in names:
        entry = {}
        for set_name, cases in sets.items():
            outputs = read_outputs(arguments.out / f"{name}.{set_name}.jsonl", cases)
            if outputs is None:
                raise SystemExit(f"the file of {name} on {set_name} is not whole after the read")
            entry[set_name] = metrics2.summarize(cases, outputs)
        result["arms"][name] = entry
    stats_path = arguments.out / MODEL_STATS
    if stats_path.exists():
        for line in stats_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            for name in row["arms"]:
                result["arms"][name][row["set"]]["model"] = {"arms_sharing_the_scorer": len(row["arms"]), **{
                    key: row[key] for key in ("requests", "tokens_read", "model_ms", "seconds_with_pipe", "rss_anon_kb")}}
    result["read_log"] = [json.loads(line) for line in (arguments.out / READ_LOG).read_text(encoding="utf-8").splitlines()]
    result["seconds_of_the_last_run"] = round(time.monotonic() - started, 1)
    (arguments.out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    append_line(arguments.out / READ_LOG, {"time": now(), "event": "end", "whole_files": len(known)})
    print(f"{now()} end: {len(known)} of {len(known)} files are whole, result.json is written", flush=True)


if __name__ == "__main__":
    main()

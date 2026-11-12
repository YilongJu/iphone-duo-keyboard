"""Reads the fresh held-out set once, for the arms and settings of a committed plan.

The plan (scripts/lm-domain/holdout-plan.json, written by make_holdout_plan.py and committed
before this script runs) names the six files of the set with their SHA-256 values, every arm
with its model file, its SHA-256 and its setting, the reference arm and the candidate. The
script checks every SHA-256 value, types the six files with the engine alone, with the perfect
chooser and with each arm, and applies the replacement rule of docs/lm-domain-design.md to the
candidate. It refuses a folder that already holds a result, so the set is read once.

A run that stops goes on from the stored answers of lm_score of each arm. The result file is
written at the end only.

Usage, from the repository root, on Linux:
    LD_LIBRARY_PATH=$HOME/lmft/llama/lib python3 scripts/lm-domain/read_fresh_holdout.py \
        --plan scripts/lm-domain/holdout-plan.json --shim SHIM --lm LM_SCORE --data build/lm-domain/data \
        --workers 6 --out build/lm-domain/holdout-read
"""
import argparse
import hashlib
import json
import math
import multiprocessing
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-domain"))
import harness  # noqa: E402
import rerank  # noqa: E402
import summarize3  # noqa: E402

FILES = {"generated": ("generated", "cases.generated.fresh.jsonl"), "stream": ("stream", "cases.stream.fresh.jsonl"),
         "github": ("listed", "cases.github.fresh.jsonl"), "birkbeck": ("listed", "cases.birkbeck.fresh.jsonl"),
         "domain": ("domain", "cases.domain.fresh.jsonl"), "domain_stream": ("stream", "cases.domain-stream.fresh.jsonl")}
BOOTSTRAP_DRAWS = 2000


def load_sets(folder: Path) -> dict:
    return {name: {"kind": kind, "cases": rerank.load_cases([folder / file])} for name, (kind, file) in FILES.items()}


def type_arm(job: dict) -> dict:
    """Types the six files for one arm, in a process of its own."""
    sets = load_sets(Path(job["folder"]))
    typist = harness.Typist(Path(job["shim"]), readings_file=Path(job["data"]) / "engine-readings.pickle")
    out = Path(job["out"])
    arm = job["arm"]
    scorer, stored, digest = harness.open_model(Path(job["lm"]), Path(arm["model"]).expanduser(), job["threads"],
                                                out / f"answers.{arm['name']}.jsonl")
    if digest != arm["model_sha256"]:
        raise SystemExit(f"{arm['name']}: the model file has the SHA-256 value {digest}, and the plan says {arm['model_sha256']}")
    chooser = rerank.setting_chooser(harness.setting_of(arm["setting"]), scorer)
    outputs = {name: typist.run(entry["cases"], chooser) for name, entry in sets.items()}
    scorer.close()
    typist.save_readings()
    return {"name": arm["name"], "outputs": outputs, "new_answers": stored.asked}


def sign_test(wins: int, losses: int) -> float:
    """The exact one-sided probability of `wins` or more among wins + losses fair draws."""
    total = wins + losses
    if total == 0:
        return 1.0
    return sum(math.comb(total, k) for k in range(wins, total + 1)) / 2 ** total


def interval(differences: list[float], seed: str) -> list[float]:
    """The 95 percent interval of the sum of per-unit differences, by resampling the units."""
    rng = random.Random(seed)
    count = len(differences)
    sums = sorted(sum(differences[rng.randrange(count)] for _ in range(count)) for _ in range(BOOTSTRAP_DRAWS))
    return [sums[int(0.025 * BOOTSTRAP_DRAWS)], sums[int(0.975 * BOOTSTRAP_DRAWS) - 1]]


def measures(sets: dict, outputs: dict, requested: set[str]) -> dict:
    """The counts of one arm that the replacement rule and the report use."""
    generated = harness.summarize("generated", sets["generated"]["cases"], outputs["generated"])
    streams = harness.summarize("stream", sets["stream"]["cases"], outputs["stream"])
    domain_streams = harness.summarize("stream", sets["domain_stream"]["cases"], outputs["domain_stream"])
    github = harness.summarize("listed", sets["github"]["cases"], outputs["github"])["categories"]
    birkbeck = harness.summarize("listed", sets["birkbeck"]["cases"], outputs["birkbeck"])
    domain = summarize3.domain_counts(sets["domain"]["cases"], outputs["domain"], requested, set())
    return {"generated_right": generated["right"], "generated_groups": {name: value[0] for name, value in generated["groups"].items()},
            "generated_categories": generated["categories"], "non_word_slips": generated["non_word_slips"],
            "everyday_stream": {name: entry["changed_words"] for name, entry in streams["streams"].items()},
            "everyday_stream_changed": streams["changed_words"], "everyday_stream_words": streams["words"],
            "github_misspelling": github["github_misspelling"], "github_real_word": github["github_real_word"],
            "birkbeck": [birkbeck["right"], birkbeck["cases"]], "domain": domain,
            "domain_stream": {name: entry["changed_words"] for name, entry in domain_streams["streams"].items()},
            "technical_written_changed": domain_streams["changed_words"], "technical_written_words": domain_streams["words"]}


def compare(sets: dict, arm: dict, ship: dict, engine: dict, outputs: dict, ship_outputs: dict, name: str) -> dict:
    """The seven conditions of the replacement rule for one arm against the reference, with the
    numbers behind each one."""
    documents: dict[str, list[int]] = {}
    for case in sets["domain_stream"]["cases"]:
        entry = documents.setdefault(case["source"], [0, 0])
        entry[0] += harness.changed_words(case, outputs["domain_stream"][case["id"]])
        entry[1] += harness.changed_words(case, ship_outputs["domain_stream"][case["id"]])
    wins = sum(1 for mine, theirs in documents.values() if mine < theirs)
    losses = sum(1 for mine, theirs in documents.values() if mine > theirs)
    p_value = sign_test(wins, losses)

    def right_difference(set_name: str, keep) -> list[float]:
        return [float(harness.is_right(case, outputs[set_name][case["id"]])) - float(harness.is_right(case, ship_outputs[set_name][case["id"]]))
                for case in sets[set_name]["cases"] if keep(case)]

    def changed_difference(set_name: str) -> list[float]:
        return [float(harness.changed_words(case, outputs[set_name][case["id"]]) - harness.changed_words(case, ship_outputs[set_name][case["id"]]))
                for case in sets[set_name]["cases"]]

    non_word = [category for group in harness.NON_WORD_SLIP_GROUPS for category in harness.GENERATED_GROUPS[group]]
    intervals = {
        "technical_written_changed_words": interval(changed_difference("domain_stream"), f"{name}-1"),
        "everyday_changed_words": interval(changed_difference("stream"), f"{name}-2"),
        "non_word_slips_right": interval(right_difference("generated", lambda case: case["category"] in non_word), f"{name}-4"),
        "github_misspelling_right": interval(right_difference("github", lambda case: case["category"] == "github_misspelling"), f"{name}-5a"),
        "birkbeck_right": interval(right_difference("birkbeck", lambda case: True), f"{name}-5b"),
        "real_word_slip_right": interval(right_difference("generated", lambda case: case["category"] == "real_word_slip"), f"{name}-6"),
        "domain_clean_right": interval(right_difference("domain", lambda case: case["typed"].lower() == case["intended"].lower()), f"{name}-7a"),
        "domain_slips_right": interval(right_difference("domain", lambda case: case["typed"].lower() != case["intended"].lower()
                                                        and case["category"] not in summarize3.PRICE_CATEGORIES), f"{name}-7b"),
    }
    groups, ship_groups = arm["generated_groups"], ship["generated_groups"]
    gain = ship_groups["real_word_slip"] - engine["generated_groups"]["real_word_slip"]
    real = arm["github_misspelling"][0] + arm["birkbeck"][0]
    ship_real = ship["github_misspelling"][0] + ship["birkbeck"][0]
    conditions = {
        "1 fewer changed technical and written words, over documents": arm["technical_written_changed"] < ship["technical_written_changed"] and p_value < 0.05,
        "2 everyday stream": arm["everyday_stream_changed"] <= ship["everyday_stream_changed"],
        "3 generated clean": groups["clean"] >= ship_groups["clean"] and groups["clean_symbols"] >= ship_groups["clean_symbols"],
        "4 non-word slips": arm["non_word_slips"][0] >= ship["non_word_slips"][0] - 0.005 * ship["non_word_slips"][1],
        "5 real misspellings": real >= ship_real
        and arm["github_misspelling"][0] >= ship["github_misspelling"][0] - 0.01 * ship["github_misspelling"][1]
        and arm["birkbeck"][0] >= ship["birkbeck"][0] - 0.01 * ship["birkbeck"][1],
        "6 real-word slips": groups["real_word_slip"] - engine["generated_groups"]["real_word_slip"] >= gain / 2,
        "7 domain cases": arm["domain"]["clean"][0] >= ship["domain"]["clean"][0]
        and arm["domain"]["slips"][0] >= ship["domain"]["slips"][0] - 0.005 * ship["domain"]["slips"][1],
    }
    return {"conditions": conditions, "passes": all(conditions.values()),
            "documents": {"all": len(documents), "fewer_changed_words": wins, "more_changed_words": losses, "p_one_sided": p_value},
            "intervals_of_the_difference_to_the_reference": intervals}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.out / "result.json").exists():
        raise SystemExit(f"{arguments.out} already holds a result: the fresh held-out set is read once")
    plan_text = arguments.plan.read_bytes()
    plan = json.loads(plan_text)
    folder = arguments.data / "fresh-holdout"
    for name, digest in plan["files"].items():
        found = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        if found != digest:
            raise SystemExit(f"{name} has the SHA-256 value {found}, and the plan says {digest}")
    if set(plan["files"]) != {file for _, file in FILES.values()}:
        raise SystemExit("the plan does not name the six files of the set")
    names = [arm["name"] for arm in plan["arms"]]
    if plan["reference"] not in names or (plan["candidate"] is not None and plan["candidate"] not in names):
        raise SystemExit("the plan names a reference or a candidate that is no arm of it")
    arguments.out.mkdir(parents=True, exist_ok=True)
    sets = load_sets(folder)
    requested = {line.split("\t")[0] for line in (ROOT / "scripts" / "domain-pack" / "pack" / "required-terms.tsv")
                 .read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")} - {"word"}
    typist = harness.Typist(arguments.shim, readings_file=arguments.data / "engine-readings.pickle")
    outputs = {"engine": {name: typist.run(entry["cases"], rerank.engine_choice) for name, entry in sets.items()},
               "perfect": {name: typist.run_perfect(entry["cases"]) for name, entry in sets.items()}}
    typist.save_readings()
    jobs = [{"arm": arm, "folder": str(folder), "shim": str(arguments.shim), "lm": str(arguments.lm), "data": str(arguments.data),
             "out": str(arguments.out), "threads": arguments.threads} for arm in plan["arms"]]
    with multiprocessing.Pool(arguments.workers) as pool:
        for answer in pool.imap_unordered(type_arm, jobs):
            outputs[answer["name"]] = answer["outputs"]
            print(f"{answer['name']}: typed, {answer['new_answers']} new answers of lm_score", flush=True)
    result = {"plan_sha256": hashlib.sha256(plan_text).hexdigest(), "reference": plan["reference"], "candidate": plan["candidate"],
              "sets": {name: len(entry["cases"]) for name, entry in sets.items()}, "arms": {}}
    for name, typed in outputs.items():
        with (arguments.out / f"outputs.{name}.jsonl").open("w", encoding="utf-8") as file:
            for set_name, values in typed.items():
                for case_id, output in values.items():
                    file.write(json.dumps({"set": set_name, "id": case_id, "output": output}) + "\n")
        result["arms"][name] = measures(sets, typed, requested)
    reference = plan["reference"]
    result["against_the_reference"] = {
        name: compare(sets, result["arms"][name], result["arms"][reference], result["arms"]["engine"], outputs[name], outputs[reference], name)
        for name in names if name != reference}
    candidate = plan["candidate"]
    result["decision"] = ("no candidate: the shipped file stays" if candidate is None else
                          f"the candidate {candidate} replaces the reference" if result["against_the_reference"][candidate]["passes"] else
                          f"the candidate {candidate} does not pass: the shipped file stays")
    (arguments.out / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(result["decision"])
    for name, entry in result["against_the_reference"].items():
        print(name, json.dumps(entry["conditions"]), json.dumps(entry["documents"]))


if __name__ == "__main__":
    main()

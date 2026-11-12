"""Writes holdout-plan.json: every arm, file, setting and SHA-256 of the one held-out read.

The round 1 arms keep the settings of scripts/lm-finetune/test-plan.json. Every SmolLM2 fine-tune
of round 2 takes the setting that evaluate2.py chose on the tuning sets, and the arms named with
--at-ship-setting get a second row at the setting of `ship`. The candidate comes from pick.json of
summarize2.py. The plan also holds the SHA-256 of each held-out file.

Usage, on Linux, from the repository root:
    python3 scripts/lm-finetune2/make_holdout_plan.py --round1-models ~/lmft/models --models ~/lmft2/models \
        --results ~/lmft2/results --pick PICK/pick.json --data build/lm-finetune2/data \
        --arm smollm2-lora-seed2 ... --at-ship-setting smollm2-lora-seed2 ... --out scripts/lm-finetune2/holdout-plan.json
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHIP_SETTING = {"weight": 1.0, "margin_from_typed": 0, "margin_to_typed": 4, "margin_other": 2, "space_after": 1}
SHIP_FILE = "smollm2-lora-seed1.Q4_K_M.gguf"
CALIBRATED_SHIP = "smollm2-lora-seed1-calibrated"
# The round 1 arms of the report, by their names in scripts/lm-finetune/test-plan.json.
ROUND1_ARMS = ["control", "stock-dev", "linear-features", "lora-seed1", "full-seed1", "smollm2-stock"]
HOLDOUT_FILES = ["cases.generated.holdout.jsonl", "cases.stream.holdout.jsonl", "cases.github.holdout.jsonl",
                 "cases.mitton-remainder.holdout.jsonl"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round1-models", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--pick", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--arm", action="append", default=[], help="a fine-tune of round 2, in the order of the report")
    parser.add_argument("--at-ship-setting", action="append", default=[], help="an arm that also gets a row at the setting of ship")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    described: dict[str, dict] = {}

    def file_facts(folder: Path, name: str) -> dict:
        if name not in described:
            path = folder / name
            described[name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
        return described[name]

    round1 = {arm["name"]: arm for arm in json.loads((ROOT / "scripts" / "lm-finetune" / "test-plan.json").read_text(encoding="utf-8"))["arms"]}
    arms = []
    for name in ROUND1_ARMS:
        source = round1[name]
        arm = {"name": name, "model": source["model"], "features": source.get("features"), "prompt_format": source["prompt_format"],
               "setting": source["setting"]}
        file = arm["model"] or arm["features"]
        if file is not None:
            arm.update(file_facts(arguments.round1_models, file))
        arms.append(arm)
    if round1["smollm2-lora-seed1"]["setting"] != SHIP_SETTING or round1["smollm2-lora-seed1"]["model"] != SHIP_FILE:
        raise SystemExit("the setting of ship differs from the round 1 plan")
    arms.append({"name": "ship", "model": SHIP_FILE, "features": None, "prompt_format": "typed", "setting": SHIP_SETTING,
                 **file_facts(arguments.round1_models, SHIP_FILE)})

    def tuned(name: str) -> dict:
        return json.loads((arguments.results / name / "result.json").read_text(encoding="utf-8"))["tuning"]["setting"]

    arms.append({"name": CALIBRATED_SHIP, "model": SHIP_FILE, "features": None, "prompt_format": "typed", "setting": tuned(CALIBRATED_SHIP),
                 **file_facts(arguments.round1_models, SHIP_FILE)})
    for name in arguments.arm:
        file = f"{name}.Q4_K_M.gguf"
        arms.append({"name": name, "model": file, "features": None, "prompt_format": "typed", "setting": tuned(name),
                     **file_facts(arguments.models, file)})
        if name in arguments.at_ship_setting:
            arms.append({"name": f"{name}-at-ship-setting", "model": file, "features": None, "prompt_format": "typed",
                         "setting": SHIP_SETTING, **file_facts(arguments.models, file)})
    unknown = [name for name in arguments.at_ship_setting if name not in arguments.arm]
    if unknown:
        raise SystemExit(f"--at-ship-setting names an arm outside --arm: {unknown}")

    pick = json.loads(arguments.pick.read_text(encoding="utf-8"))
    candidate = pick["candidate"].split(":")[0] if pick["candidate"] is not None else None
    if candidate is not None and candidate not in {arm["name"] for arm in arms}:
        raise SystemExit(f"the candidate {candidate} is not an arm of the plan")
    plan = {
        "note": "Every file, setting and SHA-256 below was fixed before the held-out set was read. The candidate comes from the "
                "pick on the selection sets (summarize2.py pick). The replacement rule of docs/lm-finetune2-design.md compares "
                "the candidate with ship.",
        "candidate": candidate, "calibrated_ship": CALIBRATED_SHIP, "qualified_on_the_selection_sets": pick["qualified"],
        "data_sha256": {name: sha256(arguments.data / name) for name in HOLDOUT_FILES},
        "arms": arms,
    }
    lines = ["{"]
    for key in ("note", "candidate", "calibrated_ship", "qualified_on_the_selection_sets", "data_sha256"):
        lines.append(f"  {json.dumps(key)}: {json.dumps(plan[key])},")
    lines.append('  "arms": [')
    lines.append(",\n".join("    " + json.dumps(arm) for arm in arms))
    lines += ["  ]", "}"]
    arguments.out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"candidate": candidate, "arms": [arm["name"] for arm in arms]}, indent=1))


if __name__ == "__main__":
    main()

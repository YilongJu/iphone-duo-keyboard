"""Writes the plan of the one read of the fresh held-out set: scripts/lm-domain/holdout-plan.json.

The plan names the six files of the set with their SHA-256 values, the reference arm `ship`,
the candidate of the pick (summary.json of summarize3.py), and the arms that the report shows
beside them. Each arm has its model file, the SHA-256 of that file and its setting. The plan is
committed before read_fresh_holdout.py runs, and the commit message holds its SHA-256.

The arms of the plan:
- `ship`: the shipped file at the shipped setting, the reference of the replacement rule.
- the candidate, when the pick names one.
- every arm of --also, as ARM@RULE, for the report only.

Usage, from the repository root, on Linux (the model files are read for their SHA-256):
    python3 scripts/lm-domain/make_holdout_plan.py --summary build/lm-domain/summary/summary.json \
        --data build/lm-domain/data --also ship@ceiling-0.3 mix-seed1@shipped
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-domain"))
import harness  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--queue", type=Path, default=ROOT / "scripts" / "lm-domain" / "eval-queue.json")
    parser.add_argument("--also", nargs="*", default=[])
    parser.add_argument("--out", type=Path, default=ROOT / "scripts" / "lm-domain" / "holdout-plan.json")
    arguments = parser.parse_args()
    summary = json.loads(arguments.summary.read_text(encoding="utf-8"))
    models = {arm["name"]: arm["model"] for arm in json.loads(arguments.queue.read_text(encoding="utf-8"))["arms"]}
    report = json.loads((arguments.data / "fresh-holdout" / "report.json").read_text(encoding="utf-8"))
    files = {}
    for name, entry in report["files"].items():
        digest = hashlib.sha256((arguments.data / "fresh-holdout" / name).read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise SystemExit(f"{name} does not have the SHA-256 value of its report")
        files[name] = digest

    def arm_of(name: str, rule: str, label: str) -> dict:
        entry = summary["arms"][name]
        metrics = entry["rules"][rule]
        if metrics is None:
            raise SystemExit(f"{name} has no setting for the rule {rule}")
        path = Path(models[name]).expanduser()
        digest = harness.sha256_of(path)
        if digest != entry["model_sha256"]:
            raise SystemExit(f"{path} is not the file that summarize3.py read for {name}")
        return {"name": label, "arm": name, "rule": rule, "model": models[name], "model_sha256": digest, "setting": metrics["setting"]}

    arms = [arm_of("ship", "shipped", "ship")]
    candidate = summary["pick"]["candidate"]
    candidate_label = None
    if candidate is not None:
        candidate_label = f"{candidate['arm']}@{candidate['rule']}"
        arms.append(arm_of(candidate["arm"], candidate["rule"], candidate_label))
    for text in arguments.also:
        name, rule = text.split("@")
        if text not in [arm["name"] for arm in arms]:
            arms.append(arm_of(name, rule, text))
    plan = {"rule": "docs/lm-domain-design.md, section \"Replacement rule on the fresh held-out set\"",
            "files": files, "reference": "ship", "candidate": candidate_label, "arms": arms,
            "pick": {"qualified_entries": [f"{entry['arm']}@{entry['rule']}" for entry in summary["pick"]["entries"] if entry["qualifies"]]}}
    text = json.dumps(plan, indent=1) + "\n"
    arguments.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {arguments.out}: candidate {candidate_label}, {len(arms)} arms, SHA-256 {hashlib.sha256(text.encode('utf-8')).hexdigest()}")


if __name__ == "__main__":
    main()

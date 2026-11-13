"""Steps of the workflow that types the dev cases with the candidate file of the domain round.

scripts/lm-domain/candidate.json names the candidate file: its release, its address, its SHA-256
value, its setting with the lead of the apostrophe step, and the counts of
scripts/lm-keyboard/harness_trace.py for it on the machine of the domain round.

fetch       downloads the file and stops unless it has the SHA-256 value of candidate.json
arguments   prints the setting as the arguments --setting and --lead of harness_trace.py
counts      compares the counts of a result.json of harness_trace.py with those of candidate.json,
            and stops at a difference. With --report-only it prints the differences and goes on.

Usage, from the repository root:
    python3 scripts/lm-domain/check_candidate_harness.py fetch --candidate scripts/lm-domain/candidate.json --out FILE.gguf
    python3 scripts/lm-domain/check_candidate_harness.py arguments --candidate scripts/lm-domain/candidate.json
    python3 scripts/lm-domain/check_candidate_harness.py counts --candidate scripts/lm-domain/candidate.json --result RESULT.json
"""
import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def counts_of(result: dict) -> dict:
    """The counts of a result.json of harness_trace.py that the check compares."""
    return {"right": result["reranked"]["right"], "cases": result["reranked"]["cases"],
            "groups": {name: [entry["right"], entry["cases"]] for name, entry in result["reranked"]["groups"].items()},
            "work_area_groups": {name: list(pair) for name, pair in result["domain_reranked"]["groups"].items()},
            "corrections_read_by_the_model": result["corrections_read_by_the_model"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["fetch", "arguments", "counts", "pin"])
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--report-only", action="store_true")
    arguments = parser.parse_args()
    candidate = json.loads(arguments.candidate.read_text(encoding="utf-8"))
    if arguments.step == "fetch":
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        request = urllib.request.Request(candidate["url"], headers={"User-Agent": "duo-keyboard-build/1.0", "Accept": "*/*"})
        with urllib.request.urlopen(request) as answer, arguments.out.open("wb") as file:
            for block in iter(lambda: answer.read(1 << 20), b""):
                digest.update(block)
                file.write(block)
        if digest.hexdigest() != candidate["sha256"]:
            arguments.out.unlink()
            raise SystemExit(f"{candidate['url']} has the SHA-256 value {digest.hexdigest()}, expected {candidate['sha256']}")
        print(f"fetched {arguments.out} ({arguments.out.stat().st_size} bytes)")
    elif arguments.step == "arguments":
        setting = candidate["setting"]
        print("--setting", setting["weight"], setting["margin_from_typed"], setting["margin_to_typed"], setting["margin_other"],
              setting["space_after"], "--lead", candidate["apostrophe_lead"])
    elif arguments.step == "pin":
        # Writes the counts of a local run into candidate.json.
        candidate["harness_counts"] = counts_of(json.loads(arguments.result.read_text(encoding="utf-8")))
        arguments.candidate.write_text(json.dumps(candidate, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps(candidate["harness_counts"]))
    else:
        result = json.loads(arguments.result.read_text(encoding="utf-8"))
        setting = {name: result["setting"][name] for name in candidate["setting"]}
        if setting != candidate["setting"] or result["setting"]["margin_apostrophe"] != candidate["apostrophe_lead"]:
            raise SystemExit(f"the run used the setting {result['setting']}, and candidate.json says {candidate['setting']}")
        found, expected = counts_of(result), candidate["harness_counts"]
        print("this run:  ", json.dumps(found))
        print("local run: ", json.dumps(expected))
        if found != expected:
            if not arguments.report_only:
                raise SystemExit("the counts of this run differ from the counts of the local run")
            print("the counts differ, and this job only reports them")
        else:
            print("the counts are the same")


if __name__ == "__main__":
    main()

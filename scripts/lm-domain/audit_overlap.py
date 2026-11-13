"""Marks the evaluation cases of the domain sets that share text with a training or tuning case.

The everyday parts of the domain cases come from Tatoeba, and so do the training and tuning
cases of rounds 1 and 2. The two were built apart. This script marks, in each domain set:

1. a case or stream sentence whose Tatoeba source is the source of a training, stopping or
   tuning case of round 1 or round 2, or whose sentence has the words of such a source;
2. a slip case whose typed and intended pair is the pair of a training or stopping case of any
   round, the domain training cases of this round included.

summarize3.py leaves the marked cases out of the domain counts of every arm, and shows them
alone in a second table. The script also counts, for the other selection sets, the slip cases
whose pair a training case holds. No rule uses those counts.

The script writes build/lm-domain/data/overlap.json: the marked ids per set, and the counts.

Usage, from the repository root:
    python3 scripts/lm-domain/audit_overlap.py --data build/lm-domain/data
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-domain"))
import harness  # noqa: E402


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    arguments = parser.parse_args()
    everyday = arguments.data / "everyday"
    fitted = [case for name in ("cases.train.jsonl", "cases.stop.jsonl", "cases2.train.jsonl", "cases2.stop.jsonl")
              for case in read_jsonl(everyday / name)]
    tuned = [case for name in ("cases.tune.jsonl", "cases.stream.tune.jsonl") for case in read_jsonl(everyday / name)]
    domain_fitted = [case for split in ("train", "stop") for case in read_jsonl(arguments.data / "domain" / f"cases.{split}.jsonl")]
    sources = {case["source"] for case in fitted + tuned if case["source"].startswith("tatoeba:")}
    texts = {case["sentence"] for case in fitted + tuned if "sentence" in case}
    pairs = {(case["typed"].lower(), case["intended"].lower()) for case in fitted + domain_fitted
             if case["typed"].lower() != case["intended"].lower()}

    sets = harness.load_sets(arguments.data, "evaluation")
    marked, counts = {}, {}
    for name in ("domain_dev", "domain_stream_dev", "domain_test", "domain_stream_test"):
        by_source, by_text, by_pair = set(), set(), set()
        for case in sets[name]["cases"]:
            if case["source"] in sources:
                by_source.add(case["id"])
            if sets[name]["kind"] == "stream" and case["typed"].lower() in texts:
                by_text.add(case["id"])
            pair = (case["typed"].lower(), case["intended"].lower())
            if pair[0] != pair[1] and pair in pairs:
                by_pair.add(case["id"])
        marked[name] = sorted(by_source | by_text | by_pair)
        counts[name] = {"cases": len(sets[name]["cases"]), "marked": len(marked[name]), "same_source": len(by_source),
                        "same_sentence_text": len(by_text), "same_typed_and_intended_pair": len(by_pair)}
    shown_only = {}
    for name in ("dev", "published_dev", "github_select"):
        slips = [case for case in sets[name]["cases"] if case["typed"].lower() != case["intended"].lower()]
        shown_only[name] = {"slip_cases": len(slips),
                            "pair_in_a_training_case": sum((case["typed"].lower(), case["intended"].lower()) in pairs for case in slips)}
    result = {"training_and_tuning_sources": len(sources), "training_pairs": len(pairs), "counts": counts,
              "other_selection_sets": shown_only, "marked": marked}
    (arguments.data / "overlap.json").write_text(json.dumps(result, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps({key: value for key, value in result.items() if key != "marked"}, indent=1))


if __name__ == "__main__":
    main()

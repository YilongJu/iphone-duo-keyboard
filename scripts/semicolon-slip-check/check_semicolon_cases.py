"""Types the semicolon cases through the keyboard's rules and scores them.

scripts/typing-evaluation/run_duo_engine.py gives the engine the whole typed text of a case at
once. On the phone the semicolon key ends a word, so the keyboard reads "don" at the semicolon
and "don;t" at the space. This script types every character of each case of
scripts/typing-evaluation/cases/english-semicolon.HALF.jsonl through the Linux copy of the
keyboard rules (scripts/lm-rerank/rerank.py). It reports the right texts per category for the
engine alone and, with --lm and --model, for the language model with the keyboard's rule.

Usage, from the repository root, on Linux, after scripts/lm-rerank/build_on_linux.sh:
    python3 scripts/semicolon-slip-check/check_semicolon_cases.py --shim "$PWD/build/lm-rerank/libduo_shim.so" \
        --half dev --out scripts/semicolon-slip-check/results.dev.json [--lm build/lm-rerank/lm_score --model MODEL.gguf]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import rerank  # noqa: E402

SHOWN_MISSES = 12


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--half", choices=["dev", "test"], required=True)
    parser.add_argument("--lm", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.lm is None) != (arguments.model is None):
        raise SystemExit("--lm and --model go together")

    cases = rerank.load_cases([rerank.CASES / f"english-semicolon.{arguments.half}.jsonl"])
    engine = rerank.Engine(arguments.shim, rerank.LEXICON, rerank.SUPPLEMENT)
    capitals = rerank.PreferredCapitals(rerank.CAPITALS_TABLE)
    choosers = {"engine alone": rerank.engine_choice}
    model = None
    if arguments.model is not None:
        model = rerank.LanguageModel(arguments.lm, arguments.model, 4, False, "typed")
        choosers["with the model"] = rerank.setting_chooser(rerank.KEYBOARD_RULE, model)

    result = {"half": arguments.half, "cases": len(cases), "runs": {}}
    for name, chooser in choosers.items():
        predictions = rerank.run(cases, engine, chooser, capitals, keep_capitals=True)
        summary = rerank.score("english", cases, predictions)
        counts = {category: [entry["right"], entry["cases"]] for category, entry in summary["categories"].items()}
        misses = [(case["typed"], predictions[case["id"]], case["intended"]) for case in cases
                  if rerank.normalize("english", predictions[case["id"]]) != rerank.normalize("english", case["intended"])]
        result["runs"][name] = {"right": counts, "misses": len(misses)}
        print(name, json.dumps(counts))
        for typed, shown, intended in misses[:SHOWN_MISSES]:
            print(f"    typed {typed!r}, shown {shown!r}, intended {intended!r}")
    if model is not None:
        model.close()
    arguments.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

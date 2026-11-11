"""Compares frequencies for the requested words of the pack (pack/required-terms.tsv).

A requested word has no corpus count, so build_pack.py gives it one fixed frequency,
REQUESTED_ZIPF. This script types the dev cases of the group `required` with the requested
words at each frequency of ZIPFS and every other word of the pack as it ships. The value to
take is the lowest one at which every case of the group is right, with the engine alone and
with the model, and one step above it for a margin.

Usage, from the repository root, on Linux:
    python3 scripts/domain-pack/requested_frequency.py --shim build/lm-rerank/libduo_shim.so \
        [--lm build/lm-rerank/lm_score --model Shared/smollm2-lora-typed-seed1.Q4_K_M.gguf] --out build/domain-pack/requested
"""
import argparse
import json
import math
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-keyboard"))
sys.path.insert(0, str(ROOT / "scripts" / "typing-engine"))
import harness_trace  # noqa: E402
import rerank  # noqa: E402
from lexicon_format import MODEL_MIXED, write_lexicon  # noqa: E402

ZIPFS = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.lm is None) != (arguments.model is None):
        raise SystemExit("--lm and --model go together")
    arguments.out.mkdir(parents=True, exist_ok=True)

    requested = {line.split("\t")[0] for line in (ROOT / "scripts/domain-pack/pack/required-terms.tsv").read_text(
        encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")}
    rows = [line.split("\t") for line in rerank.CAPITALS_TABLE.read_text(encoding="utf-8").splitlines()[1:]]
    if not requested <= {row[0] for row in rows}:
        raise SystemExit("the table of the pack does not hold every requested word")
    cases = [case for case in rerank.load_cases([rerank.DOMAIN_CASES]) if case["group"] == "required"]
    capitals = rerank.PreferredCapitals(rerank.CAPITALS_TABLE)
    model = None
    if arguments.model is not None:
        model = rerank.LanguageModel(arguments.lm, arguments.model, arguments.threads, no_context=False,
                                     prompt_format=harness_trace.PROMPT_FORMAT)

    result = {}
    for index, zipf in enumerate(ZIPFS):
        supplement = arguments.out / f"supplement-{zipf}.bin"
        words = [(word, word, ((zipf if word in requested else float(value)) - 9) * math.log(10), 0.0)
                 for word, value, *_ in sorted(rows)]
        write_lexicon(supplement, words, {}, MODEL_MIXED)
        # One shim holds one supplement, so each frequency gets its own copy of the shim.
        shim = arguments.out / f"libduo_shim_{index}.so"
        shutil.copyfile(arguments.shim, shim)
        engine = rerank.Engine(shim, rerank.LEXICON, supplement, use_supplement=True)
        choosers = {"engine": rerank.engine_choice}
        if model is not None:
            choosers["model"] = rerank.setting_chooser(harness_trace.TUNED, model)
        entry = {}
        for name, chooser in choosers.items():
            outputs = rerank.run(cases, engine, chooser, capitals, keep_capitals=True)
            tally = rerank.tally_by_group(cases, outputs)
            entry[name] = {"categories": tally["categories"], "right": tally["right"], "cases": tally["cases"],
                           "wrong": [{"id": c["id"], "typed": c["typed"], "intended": c["intended"], "output": outputs[c["id"]]}
                                     for c in cases if not rerank.case_is_right(c, outputs[c["id"]])]}
        result[str(zipf)] = entry
        print(zipf, json.dumps({name: f"{value['right']}/{value['cases']}" for name, value in entry.items()}), flush=True)
    if model is not None:
        model.close()
    (arguments.out / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")

    names = list(next(iter(result.values())))
    categories = list(next(iter(result.values()))[names[0]]["categories"])
    print()
    print("| Zipf of the requested words | " + " | ".join(f"{name}, {category}" for name in names for category in categories)
          + " | " + " | ".join(f"{name}, all" for name in names) + " |")
    print("| --- |" + " --- |" * (len(names) * (len(categories) + 1)))
    for zipf, entry in result.items():
        cells = [f"{entry[name]['categories'][category][0]}/{entry[name]['categories'][category][1]}"
                 for name in names for category in categories]
        cells += [f"{entry[name]['right']}/{entry[name]['cases']}" for name in names]
        print(f"| {zipf} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()

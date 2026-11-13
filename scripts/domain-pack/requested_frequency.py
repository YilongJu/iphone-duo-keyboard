"""Compares frequencies for the requested words of the pack (pack/required-terms.tsv).

A requested word has no corpus count, so build_pack.py gives it one fixed frequency,
REQUESTED_ZIPF, or the frequency that required-terms.tsv names for the word. This script types
dev cases with the requested words at each frequency of a grid and every other word of the
pack as it ships.

Without --word, the script moves every requested word that uses REQUESTED_ZIPF, and types the
dev cases of those words: the group `required`, and the categories
`requested_term_for_everyday_word` and `capital_requested`.

With --word WORD, the script moves that one word. It types the dev cases of the word, and every
case of english.dev.jsonl and english-symbols.dev.jsonl whose typed text holds the word. A word
gets a frequency of its own in required-terms.tsv by this rule, with the engine alone and with
the model:
1. A frequency must keep each of those existing cases right.
2. A word whose clean dev cases are all right at REQUESTED_ZIPF keeps REQUESTED_ZIPF.
3. Any other word takes the lowest frequency of the grid from REQUESTED_ZIPF up at which its clean
   dev cases are all right. When the grid lacks such a frequency, or rule 1 forbids it, the word
   takes the highest frequency that rule 1 allows.

Usage, from the repository root, on Linux:
    python3 scripts/domain-pack/requested_frequency.py --shim build/lm-rerank/libduo_shim.so \\
        [--lm build/lm-rerank/lm_score --model Shared/smollm2-lora-domain-s100-seed1.Q4_K_M.gguf] \\
        [--word todo] --out build/domain-pack/requested
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
WORD_ZIPFS = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5]
# REQUESTED_ZIPF of build_pack.py, which this script does not import: that file needs wordfreq.
DEFAULT_ZIPF = 4.5
REQUESTED_CATEGORIES = ("requested_term_for_everyday_word", "capital_requested")


def required_rows() -> list[tuple[str, float]]:
    """The requested words with their frequency, from pack/required-terms.tsv."""
    lines = [line for line in (ROOT / "scripts/domain-pack/pack/required-terms.tsv").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    if lines[0].split("\t") != ["word", "preferred", "zipf", "source"]:
        raise SystemExit("required-terms.tsv does not have the columns word, preferred, zipf, source")
    return [(fields[0], float(fields[2]) if fields[2] else DEFAULT_ZIPF) for fields in (line.split("\t") for line in lines[1:])]


def word_of(case: dict) -> str | None:
    """The requested word that a case of the domain file is about, or None."""
    if case["group"] != "required" and case["category"] not in REQUESTED_CATEGORIES:
        return None
    return case.get("requested", case.get("term"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--word", help="move this one requested word, and also type the existing dev cases that hold it")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.lm is None) != (arguments.model is None):
        raise SystemExit("--lm and --model go together")
    arguments.out.mkdir(parents=True, exist_ok=True)

    requested = required_rows()
    rows = [line.split("\t") for line in rerank.CAPITALS_TABLE.read_text(encoding="utf-8").splitlines()[1:]]
    if not {word for word, _ in requested} <= {row[0] for row in rows}:
        raise SystemExit("the table of the pack does not hold every requested word")
    domain = rerank.load_cases([rerank.DOMAIN_CASES])
    if arguments.word is not None:
        if arguments.word not in {word for word, _ in requested}:
            raise SystemExit(f"{arguments.word!r} is not a requested word")
        moved = {arguments.word}
        grid = WORD_ZIPFS
        cases = [case for case in domain if word_of(case) == arguments.word]
        # An existing case has no group. Its category gets the mark "existing".
        cases += [{**case, "category": "existing " + case["category"]} for case in rerank.load_cases(rerank.CASE_FILES)
                  if arguments.word in case["typed"].lower().split(" ")]
    else:
        moved = {word for word, zipf in requested if zipf == DEFAULT_ZIPF}
        own = {word for word, _ in requested} - moved
        grid = ZIPFS
        # The first requested words name themselves in `term`, and their controls name the control word.
        cases = [case for case in domain
                 if (case["group"] == "required" or case["category"] in REQUESTED_CATEGORIES) and word_of(case) not in own]
    if any(case["split"] != "dev" for case in cases):
        raise SystemExit("a case outside the dev half")
    capitals = rerank.PreferredCapitals(rerank.CAPITALS_TABLE)
    model = None
    if arguments.model is not None:
        model = rerank.LanguageModel(arguments.lm, arguments.model, arguments.threads, no_context=False,
                                     prompt_format=harness_trace.PROMPT_FORMAT)

    result = {}
    for index, zipf in enumerate(grid):
        supplement = arguments.out / f"supplement-{zipf}.bin"
        words = [(word, word, ((zipf if word in moved else float(value)) - 9) * math.log(10), 0.0)
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
            categories: dict[str, list[int]] = {}
            for case in cases:
                cell = categories.setdefault(case["category"], [0, 0])
                cell[0] += int(rerank.case_is_right(case, outputs[case["id"]]))
                cell[1] += 1
            entry[name] = {"categories": categories, "right": sum(cell[0] for cell in categories.values()), "cases": len(cases),
                           "wrong": [{"id": c["id"], "context": c["context"][-40:], "typed": c["typed"], "intended": c["intended"],
                                      "output": outputs[c["id"]]} for c in cases if not rerank.case_is_right(c, outputs[c["id"]])]}
        result[str(zipf)] = entry
        print(zipf, json.dumps({name: f"{value['right']}/{value['cases']}" for name, value in entry.items()}), flush=True)
    if model is not None:
        model.close()
    (arguments.out / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")

    names = list(next(iter(result.values())))
    categories = list(next(iter(result.values()))[names[0]]["categories"])
    subject = f"\"{arguments.word}\"" if arguments.word else f"the {len(moved)} requested words that use the frequency {DEFAULT_ZIPF}"
    for name in names:
        print()
        print(f"Right dev cases with {subject} at each frequency, {name}.")
        print()
        print("| Zipf | " + " | ".join(categories) + " | all |")
        print("| --- |" + " --- |" * (len(categories) + 1))
        for zipf, entry in result.items():
            cells = [f"{entry[name]['categories'][category][0]}/{entry[name]['categories'][category][1]}" for category in categories]
            print(f"| {zipf} | " + " | ".join(cells) + f" | {entry[name]['right']}/{entry[name]['cases']} |")


if __name__ == "__main__":
    main()

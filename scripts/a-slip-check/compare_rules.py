"""Compares margins of the rule for a move back to the text as typed: margin_to_typed, and
margin_to_typed_unknown for typed text with a word that the lexicon does not hold.

For each value the script reports three counts of right texts, with the language model:
- the English dev cases of scripts/typing-evaluation, per group (rerank.summarize),
- the words with "s" typed for "a" of check_a_slips.py, each after a text that is in the field,
- the whole typed sentences of check_typed_sentences.py.
The margin 99 never moves back to the text as typed. The first line is the engine alone.

Usage, from the repository root, on Linux:
    python3 scripts/a-slip-check/compare_rules.py --shim build/lm-rerank/libduo_shim.so \
        --lm build/lm-rerank/lm_score --model MODEL.gguf --out scripts/a-slip-check/compare_rules.json
"""
import argparse
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import rerank  # noqa: E402
from check_a_slips import CONTEXTS, KEYBOARD_RULE, frequent_words_with_a  # noqa: E402
from check_typed_sentences import SENTENCES, SLIPS  # noqa: E402

# Each pair: margin_to_typed, and margin_to_typed_unknown (None: one margin for every text).
MARGINS = [(4, None), (4, 8), (4, 10), (4, 12), (4, 16), (4, 99)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    # The dev cases run without the work area, as rerank.py runs them. The slips run with it, as
    # the keyboard does. One shim holds one supplement, and `use_supplement` turns it on and off.
    dev_engine = rerank.Engine(arguments.shim, rerank.LEXICON, rerank.SUPPLEMENT, use_supplement=False)
    engine = rerank.Engine(arguments.shim, rerank.LEXICON, rerank.SUPPLEMENT)
    capitals = rerank.PreferredCapitals(rerank.CAPITALS_TABLE)
    model = rerank.LanguageModel(arguments.lm, arguments.model, 4, False, "typed")
    dev_cases = rerank.load_cases(rerank.CASE_FILES)
    slip_cases = []
    for word in frequent_words_with_a():
        for position, letter in enumerate(word):
            if letter == "a":
                typed = word[:position] + "s" + word[position + 1:]
                slip_cases += [({"context": context, "typed": typed}, word) for context in CONTEXTS]
    sentence_cases = [({"context": "", "typed": " ".join(SLIPS.get(w, w) for w in s.split())}, s) for s in SENTENCES]

    def measure(name: str, chooser) -> dict:
        dev = rerank.summarize(dev_cases, rerank.run(dev_cases, dev_engine, chooser))

        def right(pairs) -> int:
            return sum(
                rerank.type_case(case, engine, chooser, capitals, keep_capitals=True).strip().lower() == intended
                for case, intended in pairs)

        row = {"rule": name, "dev_right": dev["right"], "dev_groups": dev["groups"],
               "slip_words_right": right(slip_cases), "slip_words": len(slip_cases),
               "sentences_right": right(sentence_cases), "sentences": len(sentence_cases)}
        print(json.dumps(row), flush=True)
        return row

    rows = [measure("engine alone", rerank.engine_choice)]
    for margin, margin_unknown in MARGINS:
        setting = dataclasses.replace(KEYBOARD_RULE, margin_to_typed=margin, margin_to_typed_unknown=margin_unknown)
        rows.append(measure(
            f"margin_to_typed {margin}, margin_to_typed_unknown {margin_unknown}", rerank.setting_chooser(setting, model)))
    model.close()
    arguments.out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

"""Checks how the keyboard reads a word with the key "s" pressed in place of the key "a".

The script takes the most frequent words with an "a" from the intended texts of the English dev
cases. For each "a" of a word it types the word with "s" at that place, after each text of
CONTEXTS, through the Linux copy of the keyboard rules (scripts/lm-rerank/rerank.py). It reports
the text of the engine alone and the text after the language model with the keyboard's rule
(`KeyboardLanguageModel.rule`).

Usage, from the repository root, on Linux, after scripts/lm-rerank/build_on_linux.sh llama:
    python3 scripts/a-slip-check/check_a_slips.py --shim build/lm-rerank/libduo_shim.so \
        --lm build/lm-rerank/lm_score --model MODEL.gguf --out scripts/a-slip-check/results.tsv
"""
import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import rerank  # noqa: E402

# The texts before the typed word. The empty text is the start of a field.
CONTEXTS = ["", "i think", "do you know", "we can see", "tell me", "it is not", "ok"]
WORD_COUNT = 150
# `KeyboardLanguageModel.rule` of Shared/KeyboardLanguageModel.swift.
KEYBOARD_RULE = rerank.Setting(
    weight=1.5, margin_from_typed=1, margin_to_typed=4, margin_other=2, space_after=1,
    margin_apostrophe=0.5, apostrophe_scope="next", apostrophe_score="slips", apostrophe_prompt="stock",
    margin_to_typed_unknown=12)


def frequent_words_with_a() -> list[str]:
    counts: collections.Counter[str] = collections.Counter()
    for path in rerank.CASE_FILES:
        for line in path.read_text(encoding="utf-8").splitlines():
            for word in json.loads(line)["intended"].lower().split():
                if word.isalpha() and word.isascii() and "a" in word and len(word) >= 2:
                    counts[word] += 1
    return [word for word, _ in counts.most_common(WORD_COUNT)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    engine = rerank.Engine(arguments.shim, rerank.LEXICON, rerank.SUPPLEMENT)
    capitals = rerank.PreferredCapitals(rerank.CAPITALS_TABLE)
    model = rerank.LanguageModel(arguments.lm, arguments.model, 4, False, "typed")
    with_model = rerank.setting_chooser(KEYBOARD_RULE, model)

    rows = []
    for word in frequent_words_with_a():
        for position, letter in enumerate(word):
            if letter != "a":
                continue
            typed = word[:position] + "s" + word[position + 1:]
            for context in CONTEXTS:
                case = {"context": context, "typed": typed}
                alone = rerank.type_case(case, engine, rerank.engine_choice, capitals, keep_capitals=True).strip()
                shown = rerank.type_case(case, engine, with_model, capitals, keep_capitals=True).strip()
                rows.append((word, typed, context, alone, shown))
    model.close()

    lines = ["intended\ttyped\tcontext\tengine alone\twith model"]
    lines += ["\t".join(row) for row in rows]
    arguments.out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def right(index: int) -> int:
        return sum(1 for row in rows if row[index].lower() == row[0])

    print(f"{len(rows)} typed words; engine alone right: {right(3)}; with model right: {right(4)}")
    kept = sum(1 for row in rows if row[4].lower() == row[1])
    print(f"with model, shown as typed: {kept}")
    broken = [row for row in rows if row[3].lower() == row[0] and row[4].lower() != row[0]]
    print(f"right by the engine alone and wrong with the model: {len(broken)}")
    for row in broken[:60]:
        print("   ", row)


if __name__ == "__main__":
    main()

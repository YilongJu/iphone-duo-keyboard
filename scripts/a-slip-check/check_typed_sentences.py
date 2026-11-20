"""Types whole sentences with "thst" or "whst" in them and reports the text the keyboard shows.

check_a_slips.py puts the text before the word in the field first. On the phone the person types
that text too, so a correction reads the word together with the word before it. This script types
every character of each sentence of SENTENCES through the Linux copy of the keyboard rules
(scripts/lm-rerank/rerank.py), with the engine alone and with the language model.

Usage, from the repository root, on Linux:
    python3 scripts/a-slip-check/check_typed_sentences.py --shim build/lm-rerank/libduo_shim.so \
        --lm build/lm-rerank/lm_score --model MODEL.gguf
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import rerank  # noqa: E402
from check_a_slips import KEYBOARD_RULE  # noqa: E402

# The intended sentence, in lower case. The script types "s" for the "a" of each word of SLIPS.
SENTENCES = [
    "i think that is fine", "do you know what i mean", "what do you think", "that is what i said",
    "is that ok", "so what", "i know that", "not sure what to do", "the one that works",
    "what about that", "i said that", "see what happens", "can you check that", "and that is all",
    "what is that", "for that reason", "what time is it", "like that", "about what", "that was fast",
    "i can make sure these cases are handled", "i often get that or what",
]
SLIPS = {"that": "thst", "what": "whst", "are": "sre"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    arguments = parser.parse_args()

    engine = rerank.Engine(arguments.shim, rerank.LEXICON, rerank.SUPPLEMENT)
    capitals = rerank.PreferredCapitals(rerank.CAPITALS_TABLE)
    model = rerank.LanguageModel(arguments.lm, arguments.model, 4, False, "typed")
    with_model = rerank.setting_chooser(KEYBOARD_RULE, model)
    wrong = 0
    for sentence in SENTENCES:
        typed = " ".join(SLIPS.get(word, word) for word in sentence.split())
        case = {"context": "", "typed": typed}
        alone = rerank.type_case(case, engine, rerank.engine_choice, capitals, keep_capitals=True).strip()
        shown = rerank.type_case(case, engine, with_model, capitals, keep_capitals=True).strip()
        mark = "ok   " if shown.lower() == sentence else "WRONG"
        wrong += shown.lower() != sentence
        print(f"{mark} typed: {typed!r}  engine alone: {alone!r}  with model: {shown!r}")
    model.close()
    print(f"{len(SENTENCES)} sentences, {wrong} wrong with the model")


if __name__ == "__main__":
    main()

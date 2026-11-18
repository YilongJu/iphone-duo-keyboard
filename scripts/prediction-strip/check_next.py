"""Checks the "next" mode of scripts/lm-rerank/lm_score.c.

1. The same request lines give the same answer lines and the same token lines from the program
   of the commit before the change (--old) and from the changed program (--lm).
2. For a candidate of one token, the answer line of the unchanged program holds the log
   probability of that token after the context. The next-token block of the changed program
   must hold the same number at that token, to the 5 decimals of the answer line.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/check_next.py --lm ~/predstrip/bin/lm_score \
        --old ~/predstrip/old/lm_score --model MODEL.gguf --tables build/prediction-strip/tables
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure import CASES, Scorer, Tables, language_model_text  # noqa: E402

ONE_TOKEN_WORDS = ["the", "to", "and", "of", "is", "you", "that", "for", "model", "data"]
# The answer line holds 5 decimals, and the block holds 32-bit floats.
TOLERANCE = 2e-5


def run(program: str, model: str, mode: list[str], requests: str) -> str:
    result = subprocess.run([program, model, "2", *mode], input=requests.encode("utf-8"), capture_output=True, check=True)
    return result.stdout.decode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm", required=True)
    parser.add_argument("--old", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--tables", required=True, type=Path)
    args = parser.parse_args()

    tables = Tables(args.tables)
    first, length, _, _ = tables.spaced
    for word in ONE_TOKEN_WORDS:
        number = tables.index[word]
        if tables.spaced_forms[number][0] != word or length[number, 0] != 1:
            raise SystemExit(f"{word!r} is not one token after a space")

    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines()][:400:40]
    contexts = []
    for case in cases:
        words = case["intended"].split(" ")
        for cut in (1, len(words) // 2, len(words)):
            contexts.append(language_model_text(" ".join(words[:cut]), True))
    requests = "".join("\t".join([context, *ONE_TOKEN_WORDS]) + "\n" for context in contexts)

    old_answers = run(args.old, args.model, [], requests)
    if run(args.lm, args.model, [], requests) != old_answers:
        raise SystemExit("the changed program gives other answer lines than the program before the change")
    if run(args.lm, args.model, ["tokens"], requests) != run(args.old, args.model, ["tokens"], requests):
        raise SystemExit("the changed program gives other token lines than the program before the change")
    print(f"same answer lines and token lines for {len(contexts)} requests")

    scorer = Scorer(args.lm, args.model, 2, args.tables / "check.lm_score.log")
    widest = 0.0
    compared = 0
    for context, line in zip(contexts, old_answers.splitlines()[1:]):
        block = scorer.next_tokens(context)
        # A request with candidates in "next" mode still gets its answer line.
        again = scorer.exact(context, ONE_TOKEN_WORDS)
        for word, field, (log_probability, _) in zip(ONE_TOKEN_WORDS, line.split("\t"), again):
            answer = float(field.split(" ")[0])
            if answer != log_probability:
                raise SystemExit(f"the answer line in next mode differs for {word!r} after {context!r}")
            difference = abs(float(block[first[tables.index[word], 0]]) - answer)
            widest = max(widest, difference)
            compared += 1
            if difference > TOLERANCE:
                raise SystemExit(f"{word!r} after {context!r}: block {block[first[tables.index[word], 0]]}, answer {answer}")
        total = float(np.exp(block.astype(np.float64)).sum())
        if abs(total - 1) > 1e-4:
            raise SystemExit(f"the probabilities of a block add up to {total}")
    scorer.close()
    print(f"{compared} numbers compared, widest difference {widest:.6f}, every block adds up to 1")


if __name__ == "__main__":
    main()

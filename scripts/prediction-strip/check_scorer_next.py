"""Checks the next-token numbers of the keyboard's scorer against lm_score.

The keyboard's scorer (LanguageModel/duo_lm_scorer.c, behind scripts/lm-keyboard/scorer_cli.c) and
scripts/lm-rerank/lm_score.c read the same requests in their mode "next". The check passes when
both write the same bytes: the next-token block of each request without a candidate, and the
answer line of each request with candidates.

The scorer runs three times: from an empty cache for each request, with the prefix reuse of the
cache, and with the keyboard's reuse (anchor, two slots). The two runs with reuse also read each
request again from an empty cache (the word "check" of scorer_cli) and stop on any difference.

Usage, from the repository root:
    python3 scripts/prediction-strip/check_scorer_next.py --lm LM_SCORE --scorer SCORER_CLI \
        --model MODEL.gguf [--sentences 40]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases" / "english-domain-stream.dev.jsonl"


def requests(sentences: int) -> list[str]:
    """Request lines in the order a person types: for each sentence, the text before each of its
    first words as a request without a candidate, and one request with two candidates."""
    lines = [""]  # the empty context: the start token alone
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    for case in cases[:sentences]:
        words = case["intended"].split(" ")
        for count in range(1, min(len(words), 8)):
            context = " ".join(words[:count])
            if "\t" in context:
                continue
            lines.append(context)
            if count == 3:
                lines.append(f"{context}\t{words[count]}\tthe")
    return lines


def run(program: list[str], text: str) -> bytes:
    done = subprocess.run(program, input=text.encode("utf-8"), capture_output=True)
    if done.returncode != 0:
        sys.exit(f"{' '.join(program)} ended with {done.returncode}: {done.stderr.decode('utf-8', 'replace')[-600:]}")
    return done.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm", required=True)
    parser.add_argument("--scorer", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--sentences", type=int, default=40)
    arguments = parser.parse_args()

    lines = requests(arguments.sentences)
    text = "\n".join(lines) + "\n"
    blocks = sum(1 for line in lines if "\t" not in line)
    reference = run([arguments.lm, arguments.model, "2", "next"], text)
    # In the mode "next", lm_score first writes one line that says it is ready. The blocks follow.
    ready, _, reference = reference.partition(b"\n")
    if not ready.startswith(b"ready "):
        sys.exit(f"lm_score did not start with its ready line: {ready[:80]!r}")
    print(f"{len(lines)} requests, {blocks} of them for a next-token block; lm_score wrote {len(reference)} bytes")
    failures = 0
    for name, words in [("empty cache", []), ("prefix reuse, checked", ["prefix", "check"]),
                        ("anchor reuse with two slots, checked", ["anchor", "slots2", "check"])]:
        answer = run([arguments.scorer, arguments.model, "2", *words, "next"], text)
        same = answer == reference
        failures += 0 if same else 1
        print(f"{'same bytes     ' if same else 'OTHER BYTES    '} scorer_cli, {name}: {len(answer)} bytes")
    if failures:
        sys.exit(f"{failures} run(s) of the keyboard's scorer differ from lm_score")
    print("the keyboard's scorer gives the next-token numbers of lm_score")


if __name__ == "__main__":
    main()

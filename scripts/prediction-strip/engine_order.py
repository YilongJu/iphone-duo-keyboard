"""The method F2 of the predicted-word measurement: the word order of `duo_predict_english`
in Engine/duo_engine.c, which the keyboard shows without the language model.

For every word of every dev stream sentence, and every count of typed letters from 0 to the
length of the word less 1, the script asks `duo_cli predict` for the first 20 words and writes
the place of the right word in that list, or null when the list does not hold it.

- The previous word is `word_before_space` of scripts/lm-rerank/rerank.py on the text before
  the word and one space: the lower-case letters and apostrophes right before the space, and an
  empty text at the start of the field or after a mark.
- The typed letters are the first letters of the word in lower case. Letters outside a to z and
  the apostrophe, or more than 32 letters, give no words, as the engine does.

Usage, from the repository root:
    python3 scripts/prediction-strip/engine_order.py --cli build/prediction-strip/duo_cli \
        --out build/prediction-strip/engine-order.jsonl
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
from rerank import word_before_space  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases" / "english-domain-stream.dev.jsonl"
LEXICON = ROOT / "Shared" / "lexicon-english.bin"
SUPPLEMENT = ROOT / "Shared" / "supplement-ai-software.bin"
WORDS = 20
TYPED = re.compile(r"[a-z']{0,32}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", required=True, help="duo_cli, built from Engine/duo_engine.c and Engine/duo_cli.c")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines()]
    if any(case["split"] != "dev" or case["context"] for case in cases):
        raise SystemExit("the measurement reads only dev sentences that open the field")

    # One request per pair of previous word and typed letters.
    requests: dict[tuple[str, str], int] = {}
    positions = []
    for case in cases:
        words = case["intended"].split(" ")
        for number, target in enumerate(words):
            previous = word_before_space(" ".join(words[:number]) + " ") if number else ""
            keys = []
            for typed_count in range(len(target)):
                typed = target[:typed_count].lower()
                if TYPED.fullmatch(typed) is None:
                    keys.append(None)
                else:
                    keys.append(requests.setdefault((previous, typed), len(requests)))
            positions.append((case, number, target, keys))

    lines = "".join(f"{number}\t{previous}\t{typed}\n" for (previous, typed), number in requests.items())
    run = subprocess.run(
        [args.cli, "predict", str(LEXICON), f"supplement={SUPPLEMENT}", f"words={WORDS}"],
        input=lines.encode("utf-8"), capture_output=True, check=False)
    if run.returncode != 0:
        raise SystemExit(f"duo_cli predict ended with {run.returncode}: {run.stderr.decode('utf-8', 'replace')[-2000:]}")
    answers: dict[int, list[str]] = {}
    for line in run.stdout.decode("utf-8").splitlines():
        number, _, listed = line.partition("\t")
        answers[int(number)] = listed.split(" ") if listed else []
    if len(answers) != len(requests):
        raise SystemExit(f"duo_cli answered {len(answers)} of {len(requests)} requests")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as file:
        for case, number, target, keys in positions:
            places = []
            for key in keys:
                listed = [] if key is None else answers[key]
                places.append(listed.index(target.lower()) if target.lower() in listed else None)
            file.write(json.dumps({"id": case["id"], "word": number, "places": places}, ensure_ascii=False) + "\n")
    print(f"{len(positions)} words, {len(requests)} requests to duo_cli predict")


if __name__ == "__main__":
    main()

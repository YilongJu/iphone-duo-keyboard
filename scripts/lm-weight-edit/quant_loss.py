"""Quantization loss of one converted arm on identical inputs: the 500 parity lists of the tuning
split that check_parity.py samples, scored by lm_score at f16 and at Q3_K_M. A list is right when
its target has the highest engine score + log probability + space-after log probability, the
training logit of train.py. The tuning split's targets are read here, and nothing else of it.

Usage: python scripts/lm-weight-edit/quant_loss.py PARITY_DIR [PARITY_DIR ...]
"""
import gzip
import json
import random
import sys
from pathlib import Path

FINETUNE = Path(__file__).resolve().parents[2].parent / "lm-finetune"
TOKEN_LISTS, SCORE_LISTS = 2000, 500


def scores(path: Path) -> list[list[tuple[float, float]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines[0].startswith("ready"):
        raise SystemExit(f"{path} does not start with the ready line of lm_score")
    return [[tuple(float(v) for v in field.split(" ")) for field in line.split("\t")] for line in lines[1:]]


def main():
    with gzip.open(FINETUNE / "build" / "lm-finetune" / "data" / "lists.tune.jsonl.gz", "rt", encoding="utf-8") as file:
        lists = [json.loads(line) for line in file]
    random.Random(20261110).shuffle(lists)
    lists = lists[:TOKEN_LISTS][:SCORE_LISTS]
    for directory in map(Path, sys.argv[1:]):
        result = {"arm": directory.parent.name}
        for label, name in (("f16", "llama-scores.txt"), ("q3_k_m", "llama-scores-quant.txt")):
            table = scores(directory / name)
            if len(table) != len(lists):
                raise SystemExit(f"{directory / name}: {len(table)} lists, expected {len(lists)}")
            right = 0
            for item, row in zip(lists, table):
                if len(row) != len(item["readings"]):
                    raise SystemExit("a list's reading count differs from lm_score's")
                logits = [reading[1] + lp + sa for reading, (lp, sa) in zip(item["readings"], row)]
                right += max(range(len(logits)), key=logits.__getitem__) == item["target"]
            result[label] = right
        result["lists"] = len(lists)
        print(json.dumps(result))


if __name__ == "__main__":
    main()

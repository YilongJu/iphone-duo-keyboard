"""Tests one cause of the score difference between PyTorch and lm_score on the f16 file: the
rounding of the weights to 16-bit floats in the conversion.

The script rounds every weight of the Hugging Face model to float16 and back, scores the first 500
parity lists again in float32 arithmetic, and compares three score sets: PyTorch with the float32
weights (hf-scores.jsonl), PyTorch with the rounded weights, and lm_score on the f16 file
(gaps-f16.txt of parity_gaps.py). When the rounding is the cause, the rounded PyTorch scores lie
close to lm_score, and far from the float32 PyTorch scores.

Usage, from the repository root, on Windows with uv:
    uv run --project scripts/lm-finetune python scripts/lm-finetune2/parity_f16.py \
        --model-dir build/lm-finetune2/models/NAME/hf --parity build/lm-finetune2/parity/NAME --round1 ROUND1
"""
import argparse
import json
import random
import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune"))
import train  # noqa: E402

SCORE_LISTS = 500


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--parity", type=Path, required=True)
    parser.add_argument("--round1", type=Path, required=True)
    arguments = parser.parse_args()
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_num_threads(4)
    lists = train.read_lists(arguments.round1 / "build" / "lm-finetune" / "data" / "lists.tune.jsonl.gz")
    random.Random(20261110).shuffle(lists)
    lists = lists[:SCORE_LISTS]
    tokenizer = AutoTokenizer.from_pretrained(arguments.model_dir)
    items = train.encode(lists, tokenizer, train.start_token_of(tokenizer), "typed", False)
    model = AutoModelForCausalLM.from_pretrained(arguments.model_dir, dtype=torch.float32).eval()
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.copy_(parameter.half().float())
    vocabulary = model.get_output_embeddings().weight.shape[0]
    space_tokens = torch.tensor(train.space_token_ids(tokenizer, vocabulary), dtype=torch.long)
    rounded = []
    with torch.no_grad():
        for start in range(0, SCORE_LISTS, 16):
            batch = train.make_batch(items[start:start + 16], tokenizer.eos_token_id, "cpu")
            log_probability, _ = train.reading_scores(model, batch, space_tokens, low_precision=False)
            rounded.extend(float(value) for value in log_probability)
    plain = [pair[0] for line in (arguments.parity / "hf-scores.jsonl").read_text(encoding="utf-8").splitlines() for pair in json.loads(line)]
    lines = (arguments.parity / "gaps-f16.txt").read_text(encoding="utf-8").splitlines()[1:]
    llama = [float(field.split(" ")[0]) for line in lines for field in line.split("\t")]
    if not len(plain) == len(rounded) == len(llama):
        raise SystemExit(f"{len(plain)} float32 scores, {len(rounded)} rounded scores, {len(llama)} lm_score scores")

    def gap(first, second):
        differences = [abs(a - b) for a, b in zip(first, second)]
        return {"largest": round(max(differences), 4), "mean": round(sum(differences) / len(differences), 5),
                "over_0.05": sum(d > 0.05 for d in differences)}

    report = {"readings": len(plain), "float32_weights_against_lm_score_f16": gap(plain, llama),
              "rounded_weights_against_lm_score_f16": gap(rounded, llama), "float32_weights_against_rounded_weights": gap(plain, rounded)}
    (arguments.parity / "f16-rounding.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(arguments.parity.name, json.dumps(report))


if __name__ == "__main__":
    main()

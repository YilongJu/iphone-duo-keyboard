"""Scores of PyTorch for the study of the parity differences (docs/lm-domain-results.md).

Two steps, each for one arm, on the GPU under the lock file:

rounded      For the first 500 parity lists of a parity folder (requests of check_parity.py): the
             scores of PyTorch with the float32 weights, and with every weight rounded to a 16-bit
             float and back. No llama.cpp takes part. The step writes torch-f32.jsonl and
             torch-rounded16.jsonl beside the lists, in the order of hf-scores.jsonl.
corrections  For every correction of corrections.jsonl.gz (trace_decisions.py): the float32
             scores of PyTorch for each reading. The step writes torch-scores.jsonl.gz.

Usage, from the repository root, on Windows:
    build/lm-domain/venv/Scripts/python.exe scripts/lm-domain/parity_study.py rounded --model-dir MODEL/hf \
        --lists build/lm-domain/data/parity-lists/domain --out build/lm-domain/parity/ARM/domain
    build/lm-domain/venv/Scripts/python.exe scripts/lm-domain/parity_study.py corrections --model-dir MODEL/hf \
        --out build/lm-domain/parity-study/ARM
"""
import argparse
import gzip
import json
import random
import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune2"))
import gpu_lock  # noqa: E402
import train  # noqa: E402

gpu_lock.NAME = "lm-domain (Claude agent, domain round of the re-ranker fine-tune)"
SCORE_LISTS = 500
BATCH_LISTS = 16


def scores_of(model, items: list[dict], pad: int, space_tokens, device) -> list[list[list[float]]]:
    found = []
    with torch.no_grad():
        for start in range(0, len(items), BATCH_LISTS):
            chunk = items[start:start + BATCH_LISTS]
            batch = train.make_batch(chunk, pad, device)
            log_probability, space_after = train.reading_scores(model, batch, space_tokens, low_precision=False)
            index = 0
            for item in chunk:
                count = len(item["readings"])
                found.append([[float(log_probability[index + k]), float(space_after[index + k])] for k in range(count)])
                index += count
    return found


def write(path: Path, rows: list) -> None:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["rounded", "corrections"])
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--lists", type=Path, help="the folder of lists.tune.jsonl.gz, for the step rounded")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gpu-lock", type=Path, default=Path("D:/Github/iphone-duo-keyboard/build/gpu.lock"))
    arguments = parser.parse_args()
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(arguments.model_dir)
    start_token = train.start_token_of(tokenizer)
    if arguments.step == "rounded":
        lists = train.read_lists(arguments.lists / "lists.tune.jsonl.gz")
        # The order and the count of check_parity.py.
        random.Random(20261110).shuffle(lists)
        lists = lists[:SCORE_LISTS]
    else:
        with gzip.open(arguments.out / "corrections.jsonl.gz", "rt", encoding="utf-8") as file:
            lists = [json.loads(line) for line in file]
        for item in lists:
            item["target"] = 0
    items = train.encode(lists, tokenizer, start_token, "typed", False)
    with gpu_lock.GpuLock(arguments.gpu_lock, f"parity study {arguments.step} {arguments.out}"):
        device = torch.device("cuda", 0)
        model = AutoModelForCausalLM.from_pretrained(arguments.model_dir, dtype=torch.float32).to(device).eval()
        vocabulary = model.get_output_embeddings().weight.shape[0]
        space_tokens = torch.tensor(train.space_token_ids(tokenizer, vocabulary), dtype=torch.long, device=device)
        pad = tokenizer.eos_token_id
        first = scores_of(model, items, pad, space_tokens, device)
        if arguments.step == "corrections":
            write(arguments.out / "torch-scores.jsonl.gz", first)
        else:
            write(arguments.out / "torch-f32.jsonl", first)
            with torch.no_grad():
                for parameter in model.parameters():
                    parameter.copy_(parameter.to(torch.float16).to(torch.float32))
            write(arguments.out / "torch-rounded16.jsonl", scores_of(model, items, pad, space_tokens, device))
            lengths = [{"context_tokens": len(item["prefix"]), "reading_tokens": [len(reading) for reading in item["readings"]]} for item in items]
            write(arguments.out / "token-counts.jsonl", lengths)
    print(json.dumps({"step": arguments.step, "lists": len(items), "out": str(arguments.out)}))


if __name__ == "__main__":
    main()

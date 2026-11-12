"""Averages the weights of several fine-tunes of one base model into one model.

Each input is the Hugging Face folder of a fine-tune with its LoRA weights merged in
(models/NAME/hf of train.py, train2.py or train3.py). The output holds, for every weight
tensor, the mean over the inputs. The inputs come from one base model, so the mean is the base
weights plus the mean of the fine-tunes' changes. The output has the size and the phone cost of
one input. Integer tensors must be the same in every input.

Usage, from the repository root, on Windows:
    build/lm-domain/venv/Scripts/python.exe scripts/lm-domain/average_weights.py \
        --inputs A/hf B/hf C/hf --out build/lm-domain/models/NAME
"""
import argparse
import json
import shutil
from pathlib import Path

import torch
from safetensors.torch import load_file, save_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if len(arguments.inputs) < 2:
        raise SystemExit("an average needs two inputs or more")
    if (arguments.out / "train-result.json").exists():
        raise SystemExit(f"{arguments.out} already holds a model")
    states = [load_file(path / "model.safetensors") for path in arguments.inputs]
    names = set(states[0])
    if any(set(state) != names for state in states):
        raise SystemExit("the inputs do not hold the same tensors")
    mean, largest = {}, 0.0
    for name in sorted(names):
        tensors = [state[name] for state in states]
        if any(tensor.shape != tensors[0].shape or tensor.dtype != tensors[0].dtype for tensor in tensors):
            raise SystemExit(f"the tensor {name} differs in shape or type")
        if tensors[0].is_floating_point():
            stack = torch.stack([tensor.to(torch.float64) for tensor in tensors])
            mean[name] = stack.mean(0).to(tensors[0].dtype)
            largest = max(largest, float((stack - stack.mean(0)).abs().max()))
        elif all(torch.equal(tensor, tensors[0]) for tensor in tensors):
            mean[name] = tensors[0]
        else:
            raise SystemExit(f"the integer tensor {name} differs between the inputs")
    hf = arguments.out / "hf"
    hf.mkdir(parents=True, exist_ok=True)
    for path in arguments.inputs[0].iterdir():
        if path.name != "model.safetensors" and path.is_file():
            shutil.copy2(path, hf / path.name)
    save_file(mean, str(hf / "model.safetensors"), metadata={"format": "pt"})
    result = {"method": "mean of the merged weights", "inputs": [str(path) for path in arguments.inputs],
              "tensors": len(names), "largest_distance_of_a_weight_from_the_mean": largest}
    (arguments.out / "train-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

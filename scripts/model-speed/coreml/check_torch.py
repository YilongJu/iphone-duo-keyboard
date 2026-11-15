"""Checks the scoring model of scoring_model.py and the rules of request_driver.py in PyTorch,
against the answers of llama.cpp on the same model.

Usage: python check_torch.py HF_FOLDER TOKENS ANSWERS OUT.json [--limit N] [--fixed]
  HF_FOLDER  the Hugging Face files of one model
  TOKENS     the tokens of the requests (speed_cli tokens)
  ANSWERS    llama.cpp's answers on the same requests (speed_cli cpu), from a 16-bit GGUF file
Writes the widest and the median difference of the two numbers per candidate, and the share of
requests with the same top candidate. The model reads in 32-bit floats, with its cache in 16-bit
floats, as the Core ML model keeps it.
"""

import argparse
import json
import pathlib
import statistics
import sys

import numpy as np
import torch

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from request_driver import Driver, read_tokens  # noqa: E402
from scoring_model import FIXED_SHAPES, ScoringModel, space_first_tokens  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("tokens")
    parser.add_argument("answers")
    parser.add_argument("out")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--fixed", action="store_true", help="the fixed form of convert.py --form fixed")
    arguments = parser.parse_args()
    folder = pathlib.Path(arguments.folder)
    model = ScoringModel(folder, space_first_tokens(folder), fixed_cells=arguments.fixed).eval()
    torch.set_num_threads(2)

    def make_state():
        return [torch.zeros_like(model.key_cache), torch.zeros_like(model.value_cache)]

    names = ["input_ids", "position_ids", "attention_mask"] + (["write_cells"] if arguments.fixed else []) + [
        "score_rows", "target_ids", "first_ids"]

    def call(state, inputs):
        model.key_cache, model.value_cache = state[0], state[1]
        tensors = [torch.from_numpy(inputs[name].astype(np.float32) if inputs[name].dtype == np.float16
                                    else inputs[name]) for name in names]
        with torch.no_grad():
            outputs = model(*tensors)
        state[0], state[1] = model.key_cache, model.value_cache
        return tuple(output[0].numpy() for output in outputs)

    requests = read_tokens(pathlib.Path(arguments.tokens))
    reference = []
    for line in pathlib.Path(arguments.answers).read_text().splitlines():
        reference.append([tuple(float(number) for number in field.split(" ")) for field in line.split("\t")])
    if arguments.limit:
        requests = requests[: arguments.limit]
    driver = Driver(call, make_state, shapes=list(FIXED_SHAPES) if arguments.fixed else None)
    differences, same = [], 0
    for index, request in enumerate(requests):
        mine = driver.score(request)
        theirs = reference[index]
        for (lp, sa), (rlp, rsa) in zip(mine, theirs):
            differences += [abs(lp - rlp), abs(sa - rsa)]
        top_mine = max(range(len(mine)), key=lambda c: mine[c][0] + mine[c][1])
        top_theirs = max(range(len(theirs)), key=lambda c: theirs[c][0] + theirs[c][1])
        same += top_mine == top_theirs
    result = {
        "requests": len(requests),
        "same_top_candidate": same,
        "agreement": round(same / len(requests), 4),
        "widest_difference": round(max(differences), 4),
        "median_difference": round(statistics.median(differences), 5),
        "reuse_share": round(driver.window_tokens_reused / driver.window_tokens, 3),
    }
    pathlib.Path(arguments.out).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

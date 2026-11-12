"""Trains the linear listwise chooser on engine features, the `linear-features` control of
docs/lm-finetune-design.md.

A reading's score is a weighted sum of the eight features of features.py, after each feature is
centered and scaled on the training readings. The training logit is the engine score plus that
score, as in train.py, and the loss is the same listwise cross-entropy. Adam fits the 8 weights
on all training lists at once, and the fit stops when the loss of the stopping lists has not
fallen for 20 checks of 10 steps each. The weights with the lowest stopping loss are the result.

Usage, from the repository root:
    uv run --project scripts/lm-finetune python scripts/lm-finetune/linear_features.py \
        --data build/lm-finetune/data --out build/lm-finetune/models/linear-features.json
"""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np

from features import NAMES, features

LEARNING_RATE = 0.01
MAX_STEPS = 5000
CHECK_EVERY = 10
PATIENCE = 20


def load(path: Path):
    """The feature table, the engine scores, the list of each reading, and the targets."""
    rows, engine, owner, targets = [], [], [], []
    with gzip.open(path, "rt", encoding="utf-8") as file:
        for index, line in enumerate(file):
            item = json.loads(line)
            for text, score, slips, as_typed, chosen in item["readings"]:
                rows.append(features(text, score, slips, bool(as_typed), bool(chosen), item["typed"]))
                engine.append(score)
                owner.append(index)
            targets.append(item["target"])
    return np.array(rows), np.array(engine), np.array(owner), np.array(targets)


class Lists:
    def __init__(self, table, engine, owner, targets):
        self.table, self.engine, self.owner, self.targets = table, engine, owner, targets
        self.count = len(targets)
        self.starts = np.searchsorted(owner, np.arange(self.count))
        self.target_rows = self.starts + targets

    def loss_and_gradient(self, weights):
        z = self.engine + self.table @ weights
        highest = np.maximum.reduceat(z, self.starts)
        exp = np.exp(z - highest[self.owner])
        total = np.add.reduceat(exp, self.starts)
        share = exp / total[self.owner]
        loss = float(np.mean(np.log(total) + highest - z[self.target_rows]))
        signal = share.copy()
        signal[self.target_rows] -= 1.0
        gradient = self.table.T @ signal / self.count
        right = int(np.sum(np.maximum.reduceat(z, self.starts) == z[self.target_rows]))
        return loss, gradient, right


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    train_table, train_engine, train_owner, train_targets = load(arguments.data / "lists.train.jsonl.gz")
    mean = train_table.mean(axis=0)
    scale = train_table.std(axis=0)
    scale[scale == 0] = 1.0
    train = Lists((train_table - mean) / scale, train_engine, train_owner, train_targets)
    stop_table, stop_engine, stop_owner, stop_targets = load(arguments.data / "lists.stop.jsonl.gz")
    stop = Lists((stop_table - mean) / scale, stop_engine, stop_owner, stop_targets)

    weights = np.zeros(len(NAMES))
    first_moment = np.zeros_like(weights)
    second_moment = np.zeros_like(weights)
    start_loss, _, start_right = stop.loss_and_gradient(weights)
    best = {"loss": start_loss, "weights": weights.copy(), "step": 0, "right": start_right}
    waited, step = 0, 0
    for step in range(1, MAX_STEPS + 1):
        _, gradient, _ = train.loss_and_gradient(weights)
        first_moment = 0.9 * first_moment + 0.1 * gradient
        second_moment = 0.999 * second_moment + 0.001 * gradient ** 2
        weights -= LEARNING_RATE * (first_moment / (1 - 0.9 ** step)) / (np.sqrt(second_moment / (1 - 0.999 ** step)) + 1e-8)
        if step % CHECK_EVERY == 0:
            loss, _, right = stop.loss_and_gradient(weights)
            if loss < best["loss"]:
                best = {"loss": loss, "weights": weights.copy(), "step": step, "right": right}
                waited = 0
            else:
                waited += 1
                if waited >= PATIENCE:
                    break
    train_loss, _, train_right = train.loss_and_gradient(best["weights"])
    result = {"names": NAMES, "mean": mean.tolist(), "scale": scale.tolist(), "weights": best["weights"].tolist(),
              "best_step": best["step"], "steps": step, "learning_rate": LEARNING_RATE,
              "stop_lists": stop.count, "stop_loss_before": start_loss, "stop_right_before": start_right,
              "stop_loss": best["loss"], "stop_right": best["right"],
              "train_lists": train.count, "train_loss": train_loss, "train_right": train_right}
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("mean", "scale")}))


if __name__ == "__main__":
    main()

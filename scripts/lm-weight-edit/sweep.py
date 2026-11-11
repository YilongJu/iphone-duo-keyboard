"""Builds weight-edited models and scores each one on the stopping split, the way train.py of the
fine-tune scores a checkpoint: lists right and listwise loss of engine score + model score at
weight 1, in the typed input format.

The stopping split chooses the edit's own numbers (the scale lam, the drop rate, the layer). The
tuning split then chooses the re-ranker setting in evaluate.py, and dev scores the arm. This
script never reads the tuning split, dev or test.

An arm file is a JSON list of arms. Each arm has a name, a kind and its numbers:
  {"name": "tv-0.5", "kind": "tv", "tuned": ["smollm2-lora-seed1"], "lam": 0.5}
Kinds: stock, tv (theta_0 + lam * tau of one fine-tune), ta (task arithmetic over several),
soup, ties (keep, lam), dare (drop, lam, seed), random (lam, seed, a random direction with the
norm of tau of "tuned"[0]), external (lam, a task vector from another public checkpoint of the
same base, no gradient step on this task), steer (layer, alpha: mean-reading attention-bias
steering, a constant residual vector folded into one attention output bias), tftv (blocks,
alpha: Training-Free Task Vectors of Perin et al. 2026 on the attention output projections).
A steer or tftv arm with "shuffle": true builds its vector from random labels, as a control.

Usage, from the repository root of the lm-edit worktree, with the venv of the fine-tune:
    python scripts/lm-weight-edit/sweep.py --base smollm2-135m --arms ARMS.json --out RESULTS.jsonl
    python scripts/lm-weight-edit/sweep.py --base smollm2-135m --arms ARMS.json --export NAME --export-dir DIR
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

import argparse  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import torch  # noqa: E402

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
# The fine-tune worktree holds train.py, the lists and the models. This script only reads it.
FINETUNE = Path(os.environ.get("LM_FINETUNE_ROOT", HERE.parents[2] / "lm-finetune"))
if not (FINETUNE / "scripts" / "lm-finetune" / "train.py").exists():
    raise SystemExit(f"train.py of the fine-tune is not under {FINETUNE}: set LM_FINETUNE_ROOT")
sys.path.insert(0, str(FINETUNE / "scripts" / "lm-finetune"))
sys.path.insert(0, str(HERE))
import train  # noqa: E402
import edits  # noqa: E402

MODELS = FINETUNE / "build" / "lm-finetune" / "models"
DATA = FINETUNE / "build" / "lm-finetune" / "data"
STOCK = {"smollm2-135m": MODELS / "smollm2-stock" / "hf", "distilgpt2": MODELS / "distilgpt2-stock" / "hf"}
# Public checkpoints of the same base, for the training-free task vector.
EXTERNAL = {"smollm2-135m-instruct": ("HuggingFaceTB/SmolLM2-135M-Instruct", "12fd25f77366fa6b3b4b768ec3050bf629380bac")}
STEER_LISTS = 2000


def parameters_of(model) -> dict:
    return {name: p.detach().to("cpu", copy=True).float() for name, p in model.named_parameters()}


def load_parameters(path_or_repo, revision=None) -> dict:
    from transformers import AutoModelForCausalLM
    model = AutoModelForCausalLM.from_pretrained(path_or_repo, revision=revision, dtype=torch.float32)
    return parameters_of(model)


class Workspace:
    def __init__(self, base: str, device, cache: Path):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.base, self.device, self.cache = base, device, cache
        self.tokenizer = AutoTokenizer.from_pretrained(STOCK[base])
        self.model = AutoModelForCausalLM.from_pretrained(STOCK[base], dtype=torch.float32).to(device).eval()
        self.stock = parameters_of(self.model)
        self.tuned: dict[str, dict] = {}
        vocabulary = self.model.get_output_embeddings().weight.shape[0]
        self.space_tokens = torch.tensor(train.space_token_ids(self.tokenizer, vocabulary), dtype=torch.long, device=device)
        self.pad = self.tokenizer.eos_token_id
        self.maker = train.make_packed_batch if base == "smollm2-135m" else train.make_batch
        started = time.monotonic()
        self.stop_items = train.encode(train.read_lists(DATA / "lists.stop.jsonl.gz"), self.tokenizer,
                                       train.LLAMA_START_TOKEN, "typed", False)
        print(f"encoded {len(self.stop_items)} stopping lists in {time.monotonic() - started:.0f} s", flush=True)
        self.loaded_statistics: dict = {}

    def tuned_parameters(self, name: str) -> dict:
        if name not in self.tuned:
            if name in EXTERNAL:
                self.tuned[name] = load_parameters(*EXTERNAL[name])
            else:
                self.tuned[name] = load_parameters(MODELS / name / "hf")
        return self.tuned[name]

    def statistics(self, shuffle: bool) -> dict:
        """Forward-pass statistics of the stock model on 2,000 training lists, without a gradient.
        - difference[k]: the mean over lists of (mean of hidden_states[k] at the target
          reading's tokens) less (the same mean over the other readings' tokens). hidden_states[k]
          is the residual stream entering block k, and hidden_states[k + 1] leaves it.
        - mean_input[b]: the mean input of block b's attention output projection over the
          tokens of every reading.
        With shuffle, a random reading of each list stands in for the target: the label control."""
        path = self.cache / f"statistics-{self.base}{'-shuffled' if shuffle else ''}.pt"
        if path in self.loaded_statistics:
            return self.loaded_statistics[path]
        if path.exists():
            self.loaded_statistics[path] = torch.load(path)
            return self.loaded_statistics[path]
        lists = train.read_lists(DATA / "lists.train.jsonl.gz")
        lists = [item for item in lists if item["target"] is not None and len(item["readings"]) > 1]
        random.Random(20261110).shuffle(lists)
        lists = lists[:STEER_LISTS]
        if shuffle:
            labels = random.Random(7)
            lists = [dict(item, target=labels.randrange(len(item["readings"]))) for item in lists]
        items = train.encode(lists, self.tokenizer, train.LLAMA_START_TOKEN, "typed", False)
        self.load(self.stock)
        self.model.eval()
        body = self.model.base_model
        blocks = self.model.transformer.h if self.base == "distilgpt2" else self.model.model.layers
        captured = {}
        hooks = [self.output_projection(b).register_forward_pre_hook(
            lambda module, args, b=b: captured.__setitem__(b, args[0].detach().float())) for b in range(len(blocks))]
        difference, input_sum, input_count = None, None, 0
        with torch.no_grad():
            for start in range(0, len(items), 16):
                chunk = items[start:start + 16]
                batch = train.make_batch(chunk, self.pad, self.device)
                hidden = torch.stack(body(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"],
                                          output_hidden_states=True).hidden_states).float()
                inputs = torch.stack([captured[b] for b in range(len(blocks))])
                sequence = 0
                for item in chunk:
                    means = []
                    for reading in item["readings"]:
                        begin = len(item["prefix"])
                        means.append(hidden[:, sequence, begin:begin + len(reading)].mean(1))
                        part = inputs[:, sequence, begin:begin + len(reading)]
                        input_sum = part.sum(1) if input_sum is None else input_sum + part.sum(1)
                        input_count += len(reading)
                        sequence += 1
                    target = item["target"]
                    others = torch.stack([m for i, m in enumerate(means) if i != target]).mean(0)
                    change = means[target] - others
                    difference = change if difference is None else difference + change
        for hook in hooks:
            hook.remove()
        result = {"difference": (difference / len(items)).cpu(), "mean_input": (input_sum / input_count).cpu(),
                  "lists": len(items), "shuffled": shuffle}
        self.cache.mkdir(parents=True, exist_ok=True)
        torch.save(result, path)
        self.loaded_statistics[path] = result
        return result

    def steering_vector(self, layer: int, shuffle: bool = False) -> torch.Tensor:
        return self.statistics(shuffle)["difference"][layer]

    def output_projection(self, block: int):
        if self.base == "distilgpt2":
            return self.model.transformer.h[block].attn.c_proj
        return self.model.model.layers[block].self_attn.o_proj

    def tftv(self, parameters: dict, blocks: list[int], alpha: float, shuffle: bool) -> dict:
        """W <- W + alpha * TFTV(W, s_bar, mu) on the attention output projection of each block,
        with s the steering vector of the residual stream that leaves the block."""
        stats = self.statistics(shuffle)
        edited = dict(parameters)
        for block in blocks:
            if self.base == "distilgpt2":
                name = f"transformer.h.{block}.attn.c_proj.weight"
                # GPT-2 Conv1D stores the weight as (in, out): y = x W + b.
                weight = parameters[name].T
            else:
                name = f"model.layers.{block}.self_attn.o_proj.weight"
                weight = parameters[name]
            update = edits.tftv_update(weight, stats["difference"][block + 1], stats["mean_input"][block])
            new = weight + alpha * update
            edited[name] = new.T.contiguous() if self.base == "distilgpt2" else new
        return edited

    def parameters_for(self, arm: dict) -> dict:
        kind = arm["kind"]
        if kind in ("stock", "steer"):
            return self.stock
        if kind == "tftv":
            first, last = arm["blocks"]
            return self.tftv(self.stock, list(range(first, last)), arm["alpha"], arm.get("shuffle", False))
        if kind in ("tv", "external"):
            return edits.scaled_task_vector(self.stock, self.tuned_parameters(arm["tuned"][0]), arm["lam"])
        tuned = [self.tuned_parameters(name) for name in arm["tuned"]]
        if kind == "ta":
            return edits.task_arithmetic(self.stock, tuned, arm["lam"])
        if kind == "soup":
            return edits.uniform_soup(tuned)
        if kind == "ties":
            return edits.ties(self.stock, tuned, arm["keep"], arm["lam"])
        if kind == "dare":
            return edits.dare(self.stock, tuned, arm["drop"], arm["lam"], arm["seed"])
        if kind == "random":
            direction = edits.random_like(edits.task_vector(self.stock, tuned[0]), arm["seed"])
            return edits.apply(self.stock, direction, arm["lam"])
        raise SystemExit(f"unknown kind {kind}")

    def load(self, parameters: dict, steer: tuple[int, float, bool] | None = None) -> None:
        named = dict(self.model.named_parameters())
        if named.keys() - {n for n in named if n.endswith("o_proj.bias")} != parameters.keys():
            raise SystemExit("the edited parameters do not match the model")
        with torch.no_grad():
            for name, value in parameters.items():
                named[name].copy_(value.to(self.device))
            # Remove the bias a former steer arm put on a Llama model, and put back GPT-2's own.
            if self.base == "smollm2-135m":
                for block in self.model.model.layers:
                    block.self_attn.o_proj.bias = None
            if steer is not None:
                layer, alpha, shuffle = steer
                vector = self.steering_vector(layer, shuffle).to(self.device) * alpha
                module = self.output_projection(layer)
                if module.bias is None:
                    module.bias = torch.nn.Parameter(vector.clone())
                else:
                    module.bias.add_(vector)
        # train.evaluate leaves the model in training mode, and GPT-2 has dropout.
        self.model.eval()

    def prepare(self, arm: dict) -> None:
        steer = (arm["layer"], arm["alpha"], arm.get("shuffle", False)) if arm["kind"] == "steer" else None
        if steer is not None:
            self.statistics(steer[2])
        if arm["kind"] == "tftv":
            self.statistics(arm.get("shuffle", False))
        self.load(self.parameters_for(arm), steer)

    def score(self) -> dict:
        return train.evaluate(self.model, self.stop_items, self.pad, self.space_tokens, self.device, self.maker)


def export(workspace: Workspace, arm: dict, out: Path) -> None:
    """Saves the arm as a Hugging Face model that convert_hf_to_gguf.py reads. A steer arm on
    SmolLM2 sets attention_bias, so every block gets q, k, v and o biases: zero, except the o
    bias of the steered block."""
    from transformers import AutoConfig, AutoModelForCausalLM
    workspace.prepare(arm)
    model = workspace.model
    if workspace.base == "smollm2-135m" and arm["kind"] == "steer":
        config = AutoConfig.from_pretrained(STOCK[workspace.base])
        config.attention_bias = True
        biased = AutoModelForCausalLM.from_config(config, dtype=torch.float32)
        state = {k: v.detach().cpu() for k, v in model.state_dict().items()}
        for name, value in biased.state_dict().items():
            if name.endswith(".bias") and name not in state:
                state[name] = torch.zeros_like(value)
        biased.load_state_dict(state, strict=True)
        model = biased
    out.mkdir(parents=True, exist_ok=True)
    model.to("cpu").save_pretrained(out, safe_serialization=True)
    workspace.tokenizer.save_pretrained(out)
    (out / "arm.json").write_text(json.dumps(arm, indent=2), encoding="utf-8")
    model.to(workspace.device)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", choices=sorted(STOCK), required=True)
    parser.add_argument("--arms", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="JSONL of stopping-split scores, one line per arm")
    parser.add_argument("--export", help="the name of one arm to save as a Hugging Face model")
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--cache", type=Path, default=HERE.parents[1] / "build" / "lm-weight-edit" / "cache")
    parser.add_argument("--memory-gb", type=float, default=3.5)
    parser.add_argument("--device", default="cuda")
    arguments = parser.parse_args()

    train.lower_priority()
    torch.set_num_threads(4)
    device = torch.device(arguments.device)
    if device.type == "cuda":
        total = torch.cuda.get_device_properties(0).total_memory
        torch.cuda.set_per_process_memory_fraction(arguments.memory_gb * 2**30 / total, 0)
    arms = json.loads(arguments.arms.read_text(encoding="utf-8"))
    workspace = Workspace(arguments.base, device, arguments.cache)
    if arguments.export:
        chosen = [arm for arm in arms if arm["name"] == arguments.export]
        if len(chosen) != 1:
            raise SystemExit(f"{len(chosen)} arms named {arguments.export}")
        export(workspace, chosen[0], arguments.export_dir)
        print(f"saved {arguments.export} to {arguments.export_dir}", flush=True)
        return
    done = set()
    if arguments.out.exists():
        done = {json.loads(line)["arm"]["name"] for line in arguments.out.read_text(encoding="utf-8").splitlines()}
    with arguments.out.open("a", encoding="utf-8") as file:
        for arm in arms:
            if arm["name"] in done:
                continue
            started = time.monotonic()
            workspace.prepare(arm)
            result = workspace.score()
            line = {"base": arguments.base, "arm": arm, "stop": result, "seconds": round(time.monotonic() - started, 1),
                    "torch_peak_reserved_mib": round(torch.cuda.max_memory_reserved(device) / 2**20) if device.type == "cuda" else None}
            file.write(json.dumps(line) + "\n")
            file.flush()
            print(json.dumps({"arm": arm["name"], "right": result["right"], "loss": round(result["loss"], 5),
                              "seconds": line["seconds"]}), flush=True)


if __name__ == "__main__":
    main()

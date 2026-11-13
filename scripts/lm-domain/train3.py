"""Fine-tunes of the domain round of the re-ranker, on the code of rounds 1 and 2.

The model, the typed format, the tokens, the engine score in the logit, AdamW, the warm-up and
the cosine decay are those of scripts/lm-finetune/train.py. Four things differ from
scripts/lm-finetune2/train2.py, and docs/lm-domain-design.md gives the reason for each:

--train-lists FILES      every list of these files trains.
--sampled-train-lists F  a list of these files trains when its field "u" is under --sample-share.
--sample-share S         "u" is a fixed number from 0 to 1 per source sentence, so a larger share
                         holds every list of a smaller share.
--stop-lists NAME=FILE   lists that never train. The script writes their loss per name every
                         --evaluate-every steps, on a seeded sample of --stop-sample lists per
                         name. The losses choose no weights. A sampled file (NAME=FILE with the
                         suffix @sampled) follows --sample-share too.
--steps N                the run takes N steps of 32 lists, with the cosine decay over exactly
                         these steps, and saves the weights of the last step. A run does not
                         stop early, so every arm takes the same steps.
--loss cross-entropy     the listwise cross-entropy, times --clean-weight on a list whose target
                         is the reading as typed (a clean list).
--loss expected-cost     the expected cost of the choice under the softmax over the readings,
                         plus --cross-entropy-share times the cross-entropy. A wrong reading
                         costs 1 on a slip list and --clean-cost on a clean list.

Usage, from the repository root, on Windows:
    build/lm-domain/venv/Scripts/python.exe scripts/lm-domain/train3.py --seed 1 --steps 11000 \
        --loss cross-entropy --train-lists ROUND1/lists.train.jsonl.gz ROUND2/lists2.train.jsonl.gz \
        --stop-lists everyday=ROUND1/lists.stop.jsonl.gz --evaluate-every 1000 --stop-sample 2000 \
        --micro-tokens 2500 --memory-gb 3.7 \
        --gpu-lock D:/Github/iphone-duo-keyboard/build/gpu.lock --out build/lm-domain/models/NAME
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import argparse  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune2"))
import gpu_lock  # noqa: E402
import train as t  # noqa: E402

gpu_lock.NAME = "lm-domain (Claude agent, domain round of the re-ranker fine-tune)"
FREE_MEMORY_MARGIN_MIB = 512
BASE = "smollm2-135m"
METHOD = "lora"


def list_losses(table: torch.Tensor, targets: torch.Tensor, clean: torch.Tensor, arguments) -> tuple[torch.Tensor, torch.Tensor]:
    """The loss of every list, and its plain cross-entropy.

    cross-entropy:  weight * (-log p of the target), weight = clean_weight on a clean list, else 1.
    expected-cost:  cost * (1 - p of the target) + share * (-log p of the target), where
                    cost = clean_cost on a clean list, else 1. The softmax holds at most 8
                    readings, so the expectation is exact."""
    cross_entropy = F.cross_entropy(table, targets, reduction="none")
    if arguments.loss == "cross-entropy":
        weight = 1.0 + (arguments.clean_weight - 1.0) * clean
        return weight * cross_entropy, cross_entropy
    cost = 1.0 + (arguments.clean_cost - 1.0) * clean
    probability = torch.exp(-cross_entropy)
    return cost * (1.0 - probability) + arguments.cross_entropy_share * cross_entropy, cross_entropy


def read_named(text: str) -> tuple[str, Path, bool]:
    name, path = text.split("=", 1)
    sampled = path.endswith("@sampled")
    return name, Path(path[:-len("@sampled")] if sampled else path), sampled


def take_share(lists: list[dict], share: float, path: Path) -> list[dict]:
    if any("u" not in item for item in lists):
        raise SystemExit(f"{path} holds a list without the field u")
    return [item for item in lists if item["u"] < share]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--train-lists", type=Path, nargs="+", required=True)
    parser.add_argument("--sampled-train-lists", type=Path, nargs="*", default=[])
    parser.add_argument("--sample-share", type=float)
    parser.add_argument("--stop-lists", nargs="+", required=True, help="NAME=FILE, or NAME=FILE@sampled")
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--evaluate-every", type=int, required=True)
    parser.add_argument("--stop-sample", type=int, required=True, help="lists of each stopping set that the script scores")
    parser.add_argument("--loss", choices=["cross-entropy", "expected-cost"], required=True)
    parser.add_argument("--clean-weight", type=float, default=1.0)
    parser.add_argument("--clean-cost", type=float)
    parser.add_argument("--cross-entropy-share", type=float)
    parser.add_argument("--gpu-lock", type=Path, required=True)
    parser.add_argument("--lock-held-by-parent", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--memory-gb", type=float, required=True, help="cap of the PyTorch allocator on the GPU")
    parser.add_argument("--micro-tokens", type=int, required=True)
    parser.add_argument("--max-steps", type=int, help="stop after this many steps, for a smoke test")
    parser.add_argument("--limit-lists", type=int, help="use only this many training lists, for a smoke test")
    arguments = parser.parse_args()
    if arguments.loss == "expected-cost":
        if arguments.clean_cost is None or arguments.cross_entropy_share is None or arguments.clean_weight != 1.0:
            raise SystemExit("--loss expected-cost needs --clean-cost and --cross-entropy-share, and no --clean-weight")
    elif arguments.clean_cost is not None or arguments.cross_entropy_share is not None:
        raise SystemExit("--clean-cost and --cross-entropy-share belong to --loss expected-cost")
    if bool(arguments.sampled_train_lists) != (arguments.sample_share is not None):
        raise SystemExit("--sampled-train-lists and --sample-share go together")
    if (arguments.out / "train-result.json").exists():
        raise SystemExit(f"{arguments.out} already holds a trained model")

    t.lower_priority()
    torch.set_num_threads(int(os.environ["OMP_NUM_THREADS"]))
    random.seed(arguments.seed)
    torch.manual_seed(arguments.seed)
    if arguments.lock_held_by_parent:
        gpu_lock.check_held(arguments.gpu_lock)
        run(arguments)
    else:
        with gpu_lock.GpuLock(arguments.gpu_lock, f"train {arguments.out.name}"):
            run(arguments)


def run(arguments) -> None:
    used_before = t.gpu_memory_used_mib()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available")
    device = torch.device("cuda", 0)
    total = torch.cuda.get_device_properties(0).total_memory
    free_mib = total / 2**20 - used_before
    if free_mib < arguments.memory_gb * 1024 + FREE_MEMORY_MARGIN_MIB:
        raise SystemExit(f"the GPU has {free_mib:.0f} MiB free, under the cap of {arguments.memory_gb} GB plus {FREE_MEMORY_MARGIN_MIB} MiB")
    torch.cuda.set_per_process_memory_fraction(arguments.memory_gb * 2**30 / total, 0)

    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup
    base = t.BASES[BASE]
    tokenizer = AutoTokenizer.from_pretrained(base["repository"], revision=base["revision"])
    model = AutoModelForCausalLM.from_pretrained(base["repository"], revision=base["revision"], dtype=torch.float32)
    start_token = t.start_token_of(tokenizer)
    pad = tokenizer.eos_token_id
    vocabulary = model.get_output_embeddings().weight.shape[0]
    space_ids = t.space_token_ids(tokenizer, vocabulary)
    space_tokens = torch.tensor(space_ids, dtype=torch.long, device=device)

    settings = dict(t.SETTINGS[METHOD])
    config = LoraConfig(r=settings["rank"], lora_alpha=settings["alpha"], lora_dropout=settings["dropout"],
                        target_modules=base["lora_targets"], fan_in_fan_out=base["fan_in_fan_out"], bias="none",
                        task_type="CAUSAL_LM")
    model = get_peft_model(model, config)
    parameters = [{"params": [p for p in model.parameters() if p.requires_grad], "weight_decay": settings["weight_decay"]}]
    model.to(device)
    model.train()
    trained = sum(p.numel() for group in parameters for p in group["params"])
    every = sum(p.numel() for p in model.parameters())

    started = time.monotonic()
    train_lists, counts = [], {}
    for path in arguments.train_lists:
        found = t.read_lists(path)
        counts[str(path)] = len(found)
        train_lists += found
    for path in arguments.sampled_train_lists:
        found = take_share(t.read_lists(path), arguments.sample_share, path)
        counts[str(path)] = len(found)
        train_lists += found
    stop_sets = {}
    for text in arguments.stop_lists:
        name, path, sampled = read_named(text)
        found = t.read_lists(path)
        if sampled:
            if arguments.sample_share is None:
                continue
            found = take_share(found, arguments.sample_share, path)
        # The same sample for every arm and seed: the order is seeded by the name of the set.
        random.Random(f"lm-domain-stop:{name}").shuffle(found)
        stop_sets[name] = found[:arguments.stop_sample]
    if arguments.limit_lists:
        random.Random(arguments.seed).shuffle(train_lists)
        train_lists = train_lists[:arguments.limit_lists]
        stop_sets = {name: found[:500] for name, found in stop_sets.items()}

    def encode(lists: list[dict]) -> list[dict]:
        items = t.encode(lists, tokenizer, start_token, "typed", False)
        for item, source in zip(items, lists):
            item["clean"] = float(source["readings"][source["target"]][3] == 1)
        return items

    train_items = encode(train_lists)
    stop_items = {name: encode(found) for name, found in stop_sets.items()}
    encode_seconds = time.monotonic() - started

    def losses_of(items: list[dict]) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        batch = t.make_packed_batch(items, pad, device)
        table, _ = t.logits_of_lists(model, batch, space_tokens)
        clean = torch.tensor([item["clean"] for item in items], dtype=torch.float32, device=device)
        loss, cross_entropy = list_losses(table, batch["list_targets"], clean, arguments)
        return loss, cross_entropy, table

    def evaluate(items: list[dict]) -> dict:
        """The means over the lists of the training loss and of the plain cross-entropy, and the
        lists whose highest logit is the target."""
        model.eval()
        loss_sum, cross_entropy_sum, right, clean_lists, clean_right = 0.0, 0.0, 0, 0, 0
        with torch.no_grad():
            for start in range(0, len(items), t.BATCH_LISTS):
                for chunk in t.micro_batches(items[start:start + t.BATCH_LISTS], t.MICRO_LISTS, arguments.micro_tokens, True):
                    loss, cross_entropy, table = losses_of(chunk)
                    loss_sum += float(loss.sum())
                    cross_entropy_sum += float(cross_entropy.sum())
                    targets = torch.tensor([item["target"] for item in chunk], device=device)
                    hit = table.argmax(1) == targets
                    clean = torch.tensor([item["clean"] for item in chunk], device=device) > 0
                    right += int(hit.sum())
                    clean_lists += int(clean.sum())
                    clean_right += int((hit & clean).sum())
        model.train()
        return {"loss": loss_sum / len(items), "cross_entropy": cross_entropy_sum / len(items), "right": right,
                "lists": len(items), "clean_lists": clean_lists, "clean_right": clean_right}

    def evaluate_all() -> dict:
        return {name: evaluate(items) for name, items in stop_items.items()}

    total_steps = arguments.steps
    schedule_steps = total_steps
    if arguments.max_steps:
        total_steps = min(total_steps, arguments.max_steps)
    optimizer = torch.optim.AdamW(parameters, lr=settings["learning_rate"], betas=(0.9, 0.999), eps=1e-8)
    schedule = get_cosine_schedule_with_warmup(optimizer, t.WARMUP_STEPS, schedule_steps)

    arguments.out.mkdir(parents=True, exist_ok=True)
    # A run saves its whole state after every check of the stopping lists, and starts again from
    # that state. A file named STOP in the output folder ends the run at the next saved state.
    checkpoint_path = arguments.out / "checkpoint.pt"
    stop_request = arguments.out / "STOP"
    rng = random.Random(arguments.seed)
    order = list(range(len(train_items)))
    resumed_from = []
    if checkpoint_path.exists():
        saved = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        if saved["train_lists"] != len(train_items) or saved["total_steps"] != total_steps:
            raise SystemExit(f"{checkpoint_path} belongs to a run with other lists or steps")
        with torch.no_grad():
            named = dict(model.named_parameters())
            for name, value in saved["trainable"].items():
                named[name].copy_(value.to(device))
        optimizer.load_state_dict(saved["optimizer"])
        schedule.load_state_dict(saved["schedule"])
        rng.setstate(saved["rng"])
        torch.set_rng_state(saved["torch_rng"])
        torch.cuda.set_rng_state_all(saved["cuda_rng"])
        order, position, step, first = (saved[key] for key in ("order", "position", "step", "first"))
        seconds_before = saved["seconds"]
        resumed_from = saved["resumed_from"] + [step]
        log = (arguments.out / "train-log.jsonl").open("a", encoding="utf-8")
        print(f"resumed at step {step}", flush=True)
    else:
        log = (arguments.out / "train-log.jsonl").open("w", encoding="utf-8")
        first = {"step": 0, "stop": evaluate_all()}
        log.write(json.dumps(first) + "\n")
        log.flush()
        print("step 0", json.dumps(first), flush=True)
        step, seconds_before = 0, 0.0
        position = len(order)  # the first step shuffles the order
    train_started, peak_used = time.monotonic() - seconds_before, used_before
    last = first
    while step < total_steps:
        if position >= len(order):
            rng.shuffle(order)
            position = 0
        step_items = [train_items[i] for i in order[position:position + t.BATCH_LISTS]]
        position += t.BATCH_LISTS
        optimizer.zero_grad(set_to_none=True)
        loss_sum = 0.0
        for micro_items in t.micro_batches(step_items, t.MICRO_LISTS, arguments.micro_tokens, True):
            loss, _, _ = losses_of(micro_items)
            loss = loss.sum() / len(step_items)
            loss.backward()
            loss_sum += float(loss.detach())
        torch.nn.utils.clip_grad_norm_([p for group in parameters for p in group["params"]], t.GRADIENT_CLIP)
        optimizer.step()
        schedule.step()
        step += 1
        if step % 100 == 0:
            peak_used = max(peak_used, t.gpu_memory_used_mib())
            print(f"step {step} of {total_steps}, loss {loss_sum:.4f}, {time.monotonic() - train_started:.0f} s", flush=True)
        if step % arguments.evaluate_every == 0 or step == total_steps:
            last = {"step": step, "seconds": round(time.monotonic() - train_started, 1), "stop": evaluate_all()}
            log.write(json.dumps(last) + "\n")
            log.flush()
            print("evaluate", json.dumps(last), flush=True)
            if step < total_steps:
                temporary = arguments.out / "checkpoint.tmp"
                torch.save({"trainable": {n: p.detach().to("cpu", copy=True) for n, p in model.named_parameters() if p.requires_grad},
                            "optimizer": optimizer.state_dict(), "schedule": schedule.state_dict(), "rng": rng.getstate(),
                            "torch_rng": torch.get_rng_state(), "cuda_rng": torch.cuda.get_rng_state_all(), "order": order,
                            "position": position, "step": step, "first": first, "resumed_from": resumed_from,
                            "train_lists": len(train_items), "total_steps": total_steps,
                            "seconds": time.monotonic() - train_started}, temporary)
                os.replace(temporary, checkpoint_path)
                if stop_request.exists():
                    stop_request.unlink()
                    log.close()
                    print(f"stopped at the saved state of step {step}", flush=True)
                    raise SystemExit(3)
    train_seconds = time.monotonic() - train_started
    log.close()

    model = model.merge_and_unload()
    model.to("cpu").save_pretrained(arguments.out / "hf", safe_serialization=True)
    tokenizer.save_pretrained(arguments.out / "hf")
    result = {
        "base": base, "method": METHOD, "settings": settings, "seed": arguments.seed,
        "loss": arguments.loss, "clean_weight": arguments.clean_weight, "clean_cost": arguments.clean_cost,
        "cross_entropy_share": arguments.cross_entropy_share,
        "times_each_training_list_is_seen": round(arguments.steps * t.BATCH_LISTS / len(train_items), 3),
        "sample_share": arguments.sample_share, "train_files": counts,
        "batch_lists": t.BATCH_LISTS, "micro_tokens": arguments.micro_tokens, "warmup_steps": t.WARMUP_STEPS,
        "evaluate_every": arguments.evaluate_every, "stop_sample": arguments.stop_sample, "gradient_clip": t.GRADIENT_CLIP,
        "prompt_format": "typed", "start_token": start_token, "space_tokens": len(space_ids),
        "trained_weights": trained, "all_weights": every,
        "train_lists": len(train_items), "train_lists_with_the_typed_reading_as_target": int(sum(item["clean"] for item in train_items)),
        "stop_lists": {name: len(items) for name, items in stop_items.items()},
        "steps": step, "schedule_steps": schedule_steps, "resumed_from_steps": resumed_from, "weights_of_step": step,
        "stop_before": first["stop"], "stop_last": last["stop"],
        "encode_seconds": round(encode_seconds, 1), "train_seconds": round(train_seconds, 1),
        "torch_peak_allocated_mib": round(torch.cuda.max_memory_allocated(device) / 2**20),
        "torch_peak_reserved_mib": round(torch.cuda.max_memory_reserved(device) / 2**20),
        "gpu_used_before_mib": used_before, "gpu_used_peak_mib": peak_used,
        "torch": torch.__version__, "gpu": torch.cuda.get_device_name(0),
    }
    (arguments.out / "train-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    checkpoint_path.unlink(missing_ok=True)
    print(json.dumps({k: v for k, v in result.items() if k not in ("base", "stop_before")}), flush=True)


if __name__ == "__main__":
    main()

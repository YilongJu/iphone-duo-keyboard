"""Round 2 fine-tunes of the re-ranker, on the code of round 1 (scripts/lm-finetune/train.py).

The model, the typed format, the tokens, the listwise cross-entropy loss, AdamW, the warm-up, the
cosine decay and the early stop are those of round 1. Three things are new, each behind a flag:

--extra-data DIR         adds the lists of build_lists2.py (clean running text and Wikipedia
                         misspellings) to the training lists and to the stopping lists.
--extra-without CATEGORY leaves the extra lists of one category out (the clean-only arm leaves
                         out real_misspelling_wikipedia).
--keep-typed-margin M    adds a hinge term to the loss of every list whose target is the reading
--keep-typed-weight W    as typed: W * max(0, M - (logit of the target - highest other logit)).
                         It asks the typed word to lead by M nats when the typed word is right.
--gpu-lock FILE          the lock file that the GPU's users share. The script creates it before
                         it touches the GPU and deletes it at the end, also after an error. With
                         --lock-held-by-parent, run_queue.py holds the lock for one or two runs.

Usage, from the repository root, on Windows with uv:
    uv run --project scripts/lm-finetune python scripts/lm-finetune2/train2.py --base smollm2-135m \
        --method lora --seed 1 --packed --micro-tokens 1500 --data ROUND1/build/lm-finetune/data \
        --extra-data build/lm-finetune2/data --gpu-lock D:/Github/iphone-duo-keyboard/build/gpu.lock \
        --out build/lm-finetune2/models/smollm2-lora-mix-seed1
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune2"))
import train as t  # noqa: E402

from gpu_lock import GpuLock, check_held  # noqa: E402

# The script starts only when the GPU has this much free memory, so its cap fits beside the other apps.
FREE_MEMORY_MARGIN_MIB = 512


def keep_typed_term(table: torch.Tensor, targets: torch.Tensor, typed_target: torch.Tensor, margin: float) -> torch.Tensor:
    """The sum over the lists whose target is the reading as typed of
    max(0, margin - (logit of the target - highest other logit))."""
    target_logit = table.gather(1, targets[:, None]).squeeze(1)
    others = table.scatter(1, targets[:, None], float("-inf"))
    lead = target_logit - others.max(dim=1).values
    return (torch.clamp(margin - lead, min=0.0) * typed_target).sum()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", choices=sorted(t.BASES), required=True)
    parser.add_argument("--method", choices=sorted(t.SETTINGS), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--data", type=Path, required=True, help="the lists of round 1")
    parser.add_argument("--extra-data", type=Path, help="the folder of lists2.train.jsonl.gz and lists2.stop.jsonl.gz")
    parser.add_argument("--extra-without", help="leave out the extra lists of this category, for the clean-only arm")
    parser.add_argument("--keep-typed-margin", type=float)
    parser.add_argument("--keep-typed-weight", type=float)
    parser.add_argument("--gpu-lock", type=Path, required=True)
    parser.add_argument("--lock-held-by-parent", action="store_true",
                        help="run_queue.py holds the lock for this run; the script only checks that the lock is ours")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--memory-gb", type=float, default=3.0, help="cap of the PyTorch allocator on the GPU")
    parser.add_argument("--packed", action="store_true")
    parser.add_argument("--micro-lists", type=int, default=t.MICRO_LISTS)
    parser.add_argument("--micro-tokens", type=int)
    parser.add_argument("--max-steps", type=int, help="stop after this many steps, for a smoke test")
    parser.add_argument("--limit-lists", type=int, help="use only this many training lists, for a smoke test")
    arguments = parser.parse_args()
    if (arguments.keep_typed_margin is None) != (arguments.keep_typed_weight is None):
        raise SystemExit("--keep-typed-margin and --keep-typed-weight go together")
    if (arguments.out / "train-result.json").exists():
        raise SystemExit(f"{arguments.out} already holds a trained model")

    t.lower_priority()
    torch.set_num_threads(int(os.environ["OMP_NUM_THREADS"]))
    random.seed(arguments.seed)
    torch.manual_seed(arguments.seed)
    if arguments.lock_held_by_parent:
        check_held(arguments.gpu_lock)
        run(arguments)
    else:
        with GpuLock(arguments.gpu_lock, f"train {arguments.out.name}"):
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

    from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup
    base = t.BASES[arguments.base]
    tokenizer = AutoTokenizer.from_pretrained(base["repository"], revision=base["revision"])
    model = AutoModelForCausalLM.from_pretrained(base["repository"], revision=base["revision"], dtype=torch.float32)
    start_token = t.start_token_of(tokenizer)
    pad = tokenizer.eos_token_id
    vocabulary = model.get_output_embeddings().weight.shape[0]
    space_ids = t.space_token_ids(tokenizer, vocabulary)
    space_tokens = torch.tensor(space_ids, dtype=torch.long, device=device)

    settings = dict(t.SETTINGS[arguments.method])
    if arguments.method == "lora":
        from peft import LoraConfig, get_peft_model
        config = LoraConfig(r=settings["rank"], lora_alpha=settings["alpha"], lora_dropout=settings["dropout"],
                            target_modules=base["lora_targets"], fan_in_fan_out=base["fan_in_fan_out"], bias="none",
                            task_type="CAUSAL_LM")
        model = get_peft_model(model, config)
        parameters = [{"params": [p for p in model.parameters() if p.requires_grad], "weight_decay": settings["weight_decay"]}]
    else:
        decay, plain = [], []
        for name, parameter in model.named_parameters():
            (plain if parameter.ndim < 2 or "ln" in name or "norm" in name or name.endswith(".bias") else decay).append(parameter)
        parameters = [{"params": decay, "weight_decay": settings["weight_decay"]}, {"params": plain, "weight_decay": 0.0}]
    model.to(device)
    model.train()
    trained = sum(p.numel() for group in parameters for p in group["params"])
    every = sum(p.numel() for p in model.parameters())

    started = time.monotonic()
    train_lists = t.read_lists(arguments.data / "lists.train.jsonl.gz")
    stop_lists = t.read_lists(arguments.data / "lists.stop.jsonl.gz")
    round1_counts = {"train": len(train_lists), "stop": len(stop_lists)}
    if arguments.extra_data is not None:
        for lists, name in ((train_lists, "lists2.train.jsonl.gz"), (stop_lists, "lists2.stop.jsonl.gz")):
            extra = t.read_lists(arguments.extra_data / name)
            if arguments.extra_without is not None:
                kept = [item for item in extra if item["category"] != arguments.extra_without]
                if len(kept) == len(extra):
                    raise SystemExit(f"{name} holds no list of the category {arguments.extra_without}")
                extra = kept
            lists += extra
    if arguments.limit_lists:
        random.Random(arguments.seed).shuffle(train_lists)
        train_lists = train_lists[:arguments.limit_lists]

    def encode(lists: list[dict]) -> list[dict]:
        items = t.encode(lists, tokenizer, start_token, "typed", False)
        for item, source in zip(items, lists):
            item["typed_target"] = float(source["readings"][source["target"]][3] == 1)
        return items

    train_items, stop_items = encode(train_lists), encode(stop_lists)
    encode_seconds = time.monotonic() - started
    maker = t.make_packed_batch if arguments.packed else t.make_batch
    margin, weight = arguments.keep_typed_margin, arguments.keep_typed_weight

    def loss_of(items: list[dict]) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """The sums over the lists of the cross-entropy and of the hinge term, and the logits."""
        batch = maker(items, pad, device)
        table, _ = t.logits_of_lists(model, batch, space_tokens)
        cross_entropy = F.cross_entropy(table, batch["list_targets"], reduction="sum")
        hinge = torch.zeros((), device=device)
        if margin is not None:
            typed_target = torch.tensor([item["typed_target"] for item in items], dtype=torch.float32, device=device)
            hinge = keep_typed_term(table, batch["list_targets"], typed_target, margin)
        return cross_entropy, hinge, table

    def evaluate(items: list[dict]) -> dict:
        """The stopping loss: the training loss, as a mean over the lists."""
        model.eval()
        sums = {"cross_entropy": 0.0, "hinge": 0.0}
        right = 0
        with torch.no_grad():
            for start in range(0, len(items), t.BATCH_LISTS):
                # The micro-batches of a training step, so the stopping loss needs the same memory.
                for chunk in t.micro_batches(items[start:start + t.BATCH_LISTS], arguments.micro_lists, arguments.micro_tokens, arguments.packed):
                    cross_entropy, hinge, table = loss_of(chunk)
                    sums["cross_entropy"] += float(cross_entropy)
                    sums["hinge"] += float(hinge)
                    targets = torch.tensor([item["target"] for item in chunk], device=device)
                    right += int((table.argmax(1) == targets).sum())
        model.train()
        loss = (sums["cross_entropy"] + (weight or 0.0) * sums["hinge"]) / len(items)
        return {"loss": loss, "cross_entropy": sums["cross_entropy"] / len(items), "hinge": sums["hinge"] / len(items),
                "right": right, "lists": len(items)}

    steps_per_epoch = math.ceil(len(train_items) / t.BATCH_LISTS)
    total_steps = steps_per_epoch * t.MAX_EPOCHS
    if arguments.max_steps:
        total_steps = min(total_steps, arguments.max_steps)
    optimizer = torch.optim.AdamW(parameters, lr=settings["learning_rate"], betas=(0.9, 0.999), eps=1e-8)
    schedule = get_cosine_schedule_with_warmup(optimizer, t.WARMUP_STEPS, steps_per_epoch * t.MAX_EPOCHS)

    arguments.out.mkdir(parents=True, exist_ok=True)
    log = (arguments.out / "train-log.jsonl").open("w", encoding="utf-8")
    first = evaluate(stop_items)
    first.update({"step": 0})
    log.write(json.dumps(first) + "\n")
    print("step 0", json.dumps(first), flush=True)
    best = {"loss": first["loss"], "step": 0, "state": None}
    waited, step, train_started, peak_used = 0, 0, time.monotonic(), used_before
    order = list(range(len(train_items)))
    rng = random.Random(arguments.seed)
    stopped = "max steps"
    while step < total_steps:
        rng.shuffle(order)
        for start in range(0, len(order), t.BATCH_LISTS):
            step_items = [train_items[i] for i in order[start:start + t.BATCH_LISTS]]
            optimizer.zero_grad(set_to_none=True)
            loss_sum = 0.0
            for micro_items in t.micro_batches(step_items, arguments.micro_lists, arguments.micro_tokens, arguments.packed):
                cross_entropy, hinge, _ = loss_of(micro_items)
                loss = (cross_entropy + (weight or 0.0) * hinge) / len(step_items)
                loss.backward()
                loss_sum += float(loss.detach())
            torch.nn.utils.clip_grad_norm_([p for group in parameters for p in group["params"]], t.GRADIENT_CLIP)
            optimizer.step()
            schedule.step()
            step += 1
            if step % 100 == 0:
                peak_used = max(peak_used, t.gpu_memory_used_mib())
                print(f"step {step} of {total_steps}, loss {loss_sum:.4f}, {time.monotonic() - train_started:.0f} s", flush=True)
            if step % t.EVALUATE_EVERY == 0 or step == total_steps:
                result = evaluate(stop_items)
                result.update({"step": step, "seconds": round(time.monotonic() - train_started, 1)})
                log.write(json.dumps(result) + "\n")
                log.flush()
                print("evaluate", json.dumps(result), flush=True)
                if result["loss"] < best["loss"]:
                    trainable = {n: p.detach().to("cpu", copy=True) for n, p in model.named_parameters() if p.requires_grad}
                    best = {"loss": result["loss"], "step": step, "state": trainable}
                    waited = 0
                else:
                    waited += 1
                    if waited >= t.PATIENCE:
                        stopped = "early stop"
                        break
            if step >= total_steps:
                break
        if stopped == "early stop":
            break
    train_seconds = time.monotonic() - train_started
    log.close()

    if best["state"] is None:
        raise SystemExit("the stopping loss never fell below the loss before training")
    with torch.no_grad():
        named = dict(model.named_parameters())
        for name, value in best["state"].items():
            named[name].copy_(value.to(device))
    final = evaluate(stop_items)
    if arguments.method == "lora":
        model = model.merge_and_unload()
    model.to("cpu").save_pretrained(arguments.out / "hf", safe_serialization=True)
    tokenizer.save_pretrained(arguments.out / "hf")
    result = {
        "base": base, "method": arguments.method, "settings": settings, "seed": arguments.seed,
        "extra_data": arguments.extra_data is not None, "extra_without": arguments.extra_without, "keep_typed_margin": margin, "keep_typed_weight": weight,
        "batch_lists": t.BATCH_LISTS, "micro_lists": arguments.micro_lists, "micro_tokens": arguments.micro_tokens,
        "packed": arguments.packed, "warmup_steps": t.WARMUP_STEPS, "max_epochs": t.MAX_EPOCHS,
        "evaluate_every": t.EVALUATE_EVERY, "patience": t.PATIENCE, "gradient_clip": t.GRADIENT_CLIP,
        "prompt_format": "typed", "start_token": start_token, "space_tokens": len(space_ids),
        "trained_weights": trained, "all_weights": every,
        "round1_lists": round1_counts, "train_lists": len(train_items), "stop_lists": len(stop_items),
        "train_lists_with_the_typed_reading_as_target": int(sum(item["typed_target"] for item in train_items)),
        "steps_per_epoch": steps_per_epoch, "steps": step, "stopped": stopped, "best_step": best["step"],
        "stop_before": first, "stop_best": final,
        "encode_seconds": round(encode_seconds, 1), "train_seconds": round(train_seconds, 1),
        "torch_peak_allocated_mib": round(torch.cuda.max_memory_allocated(device) / 2**20),
        "torch_peak_reserved_mib": round(torch.cuda.max_memory_reserved(device) / 2**20),
        "gpu_used_before_mib": used_before, "gpu_used_peak_mib": peak_used,
        "torch": torch.__version__, "gpu": torch.cuda.get_device_name(0),
    }
    (arguments.out / "train-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("base", "stop_before")}), flush=True)


if __name__ == "__main__":
    main()

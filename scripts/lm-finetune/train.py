"""Fine-tunes a small language model to pick the intended reading among the engine's readings.

One list holds the readings of one correction (build_lists.py). The model reads the text before
the span, the typed span and one reading, in the typed format of `language_model_prompt` in
scripts/lm-rerank/rerank.py, tokenized as scripts/lm-rerank/lm_score.c tokenizes it. The model
score of a reading is the log probability of its tokens plus the log probability that the next
token starts with a space. The training logit is the engine score plus the model score, and the
loss is the cross-entropy of the softmax over the readings at the target (listwise loss).

Two methods:
- lora: peft LoRA on the attention and MLP layers, base weights frozen.
- full: every weight trains.
Both use AdamW, a linear warm-up and a cosine decay, and stop early on the loss of the stopping
lists. The checkpoint with the lowest stopping loss is saved as a Hugging Face model, with the
LoRA weights merged into the base weights. --prompt-format stock and --no-context train the two
control arms of docs/lm-finetune-design.md.

The process caps its GPU memory, runs at below-normal priority and uses 4 CPU threads, so the
desktop it shares stays responsive.

Usage, from the repository root, on Windows with uv:
    uv run --project scripts/lm-finetune python scripts/lm-finetune/train.py --method lora --seed 1 \
        --data build/lm-finetune/data --out build/lm-finetune/models/distilgpt2-lora-seed1
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import argparse  # noqa: E402
import ctypes  # noqa: E402
import gzip  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import random  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import rerank  # noqa: E402

# The base models, each at a fixed commit of its Hugging Face repository.
BASES = {
    "distilgpt2": {"repository": "distilbert/distilgpt2", "revision": "2290a62682d06624634c1f46a6ad5be0f47f38aa",
                   "lora_targets": ["c_attn", "c_proj", "c_fc"], "fan_in_fan_out": True},
    "smollm2-135m": {"repository": "HuggingFaceTB/SmolLM2-135M", "revision": "93efa2f097d58c2a74874c7e644dbc9b0cee75a2",
                     "lora_targets": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
                     "fan_in_fan_out": False},
}
# As in lm_score.c: the context keeps its last 96 tokens, and a reading holds at most 32.
MAX_CONTEXT_TOKENS = 96
MAX_CANDIDATE_TOKENS = 32
SETTINGS = {
    "lora": {"learning_rate": 2e-4, "weight_decay": 0.01, "rank": 16, "alpha": 32, "dropout": 0.05},
    "full": {"learning_rate": 3e-5, "weight_decay": 0.01},
}
BATCH_LISTS = 32
# A step adds the gradients of micro-batches of this many lists, so the memory stays under the cap.
MICRO_LISTS = 8
WARMUP_STEPS = 300
MAX_EPOCHS = 4
EVALUATE_EVERY = 500
PATIENCE = 5
GRADIENT_CLIP = 1.0


def lower_priority() -> None:
    if sys.platform == "win32":
        below_normal = 0x00004000
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.SetPriorityClass.restype = ctypes.c_int
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), below_normal):
            raise SystemExit(f"could not lower the process priority: error {ctypes.get_last_error()}")
    else:
        os.nice(10)


def gpu_memory_used_mib() -> int:
    """The memory in use on GPU 0 by every process, from nvidia-smi."""
    answer = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"],
                            capture_output=True, text=True, check=True)
    return int(answer.stdout.strip())


# lm_score.c reads a token's text into a buffer of 64 bytes, and a longer token does not count as
# a space token there. In a byte-level vocabulary each character of a token is one byte.
PIECE_BUFFER = 64
# The start token that llama.cpp b4846 gives lm_score.c for a GPT-2 style vocabulary. The fork
# (azooKey/llama.cpp, src/llama-vocab.cpp line 1410) sets bos to 2 and leaves out the loop that
# reads the GGUF value, so every such model reads token 2 first ("#" in GPT-2). check_parity.py
# compares this with the ready line of lm_score.
LLAMA_START_TOKEN = 2


def space_token_ids(tokenizer, vocabulary: int) -> list[int]:
    """The tokens whose text starts with a space, as lm_score.c marks them."""
    return [token for token in range(vocabulary) if tokenizer.decode([token]).startswith(" ")
            and len(tokenizer.convert_ids_to_tokens(token)) <= PIECE_BUFFER]


def start_token_of(tokenizer) -> int:
    return LLAMA_START_TOKEN


def read_lists(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as file:
        return [json.loads(line) for line in file]


def encode(lists: list[dict], tokenizer, start_token: int, prompt_format: str, no_context: bool) -> list[dict]:
    """Token ids of each list, as rerank.LanguageModel and lm_score.c build them: the start token
    and the last 96 tokens of the first text, then each reading, tokenized apart. A reading
    follows a space, unless the first text is empty."""
    encoded = []
    for item in lists:
        opens_field = not item["context"]
        context = "" if no_context else item["context"]
        prefix_text = rerank.language_model_prompt(context, item["typed"], prompt_format)
        prefix = tokenizer(prefix_text, add_special_tokens=False)["input_ids"][-MAX_CONTEXT_TOKENS:] if prefix_text else []
        readings = []
        for text, *_ in item["readings"]:
            space = " " if prefix_text else ""
            ids = tokenizer(space + rerank.language_model_text(text, opens_field), add_special_tokens=False)["input_ids"]
            if not 1 <= len(ids) <= MAX_CANDIDATE_TOKENS:
                raise SystemExit(f"a reading gives {len(ids)} tokens: {text!r}")
            readings.append(ids)
        encoded.append({"prefix": [start_token] + prefix, "readings": readings,
                        "engine": [reading[1] for reading in item["readings"]], "target": item["target"]})
    return encoded


def make_batch(items: list[dict], pad: int, device) -> dict:
    sequences, rows, owners, targets, last_rows = [], [], [], [], []
    list_of_sequence, engine = [], []
    for list_index, item in enumerate(items):
        for reading_index, reading in enumerate(item["readings"]):
            sequence_index = len(sequences)
            sequences.append(item["prefix"] + reading)
            start = len(item["prefix"]) - 1
            # The rows that predict each token of the reading, then the row after its last token.
            for offset, token in enumerate(reading):
                rows.append((sequence_index, start + offset))
                owners.append(sequence_index)
                targets.append(token)
            last_rows.append((sequence_index, start + len(reading)))
            list_of_sequence.append(list_index)
            engine.append(item["engine"][reading_index])
    width = max(len(s) for s in sequences)
    input_ids = torch.full((len(sequences), width), pad, dtype=torch.long)
    mask = torch.zeros((len(sequences), width), dtype=torch.long)
    for index, sequence in enumerate(sequences):
        input_ids[index, :len(sequence)] = torch.tensor(sequence)
        mask[index, :len(sequence)] = 1
    return {
        "input_ids": input_ids.to(device), "attention_mask": mask.to(device),
        "rows": torch.tensor(rows, dtype=torch.long, device=device),
        "owners": torch.tensor(owners, dtype=torch.long, device=device),
        "targets": torch.tensor(targets, dtype=torch.long, device=device),
        "last_rows": torch.tensor(last_rows, dtype=torch.long, device=device),
        "list_of_sequence": torch.tensor(list_of_sequence, dtype=torch.long, device=device),
        "engine": torch.tensor(engine, dtype=torch.float32, device=device),
        "list_targets": torch.tensor([item["target"] for item in items], dtype=torch.long, device=device),
        "lists": len(items), "sequences": len(sequences),
    }


def reading_scores(model, batch: dict, space_tokens: torch.Tensor, low_precision: bool = True):
    """The two model scores of every reading sequence, as lm_score.c gives them: the log
    probability of the reading's tokens, and the log probability that the next token starts
    with a space."""
    body = model.get_base_model().base_model if hasattr(model, "get_base_model") else model.base_model
    head = model.get_output_embeddings()
    with torch.autocast("cuda", dtype=torch.bfloat16, enabled=low_precision):
        hidden = body(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"]).last_hidden_state
    # The output layer runs in float32: bfloat16 logits near 50 round in steps of 0.25.
    with torch.autocast("cuda", enabled=False):
        token_logits = head(hidden[batch["rows"][:, 0], batch["rows"][:, 1]].float())
        last_logits = head(hidden[batch["last_rows"][:, 0], batch["last_rows"][:, 1]].float())
    token_log = F.log_softmax(token_logits.float(), dim=-1)
    token_scores = token_log.gather(1, batch["targets"][:, None]).squeeze(1)
    last_log = F.log_softmax(last_logits.float(), dim=-1)
    space_after = torch.logsumexp(last_log[:, space_tokens], dim=-1)
    log_probability = torch.zeros(batch["sequences"], device=token_scores.device).index_add(0, batch["owners"], token_scores)
    return log_probability, space_after


def logits_of_lists(model, batch: dict, space_tokens: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """The training logits (engine score + model score) of every reading, as a padded table of
    lists by readings, and a mask of the cells that hold a reading."""
    log_probability, space_after = reading_scores(model, batch, space_tokens)
    scores = batch["engine"] + log_probability + space_after
    # A table of lists by readings, with minus infinity where a list holds fewer readings.
    counts = torch.bincount(batch["list_of_sequence"], minlength=batch["lists"])
    width = int(counts.max())
    starts = torch.cumsum(counts, 0) - counts
    columns = torch.arange(batch["sequences"], device=scores.device) - starts[batch["list_of_sequence"]]
    table = torch.full((batch["lists"], width), float("-inf"), device=scores.device)
    table[batch["list_of_sequence"], columns] = scores
    return table, table > float("-inf")


def evaluate(model, items: list[dict], pad: int, space_tokens, device) -> dict:
    model.eval()
    loss_sum, right, engine_right = 0.0, 0, 0
    with torch.no_grad():
        for start in range(0, len(items), BATCH_LISTS):
            chunk = items[start:start + BATCH_LISTS]
            batch = make_batch(chunk, pad, device)
            table, _ = logits_of_lists(model, batch, space_tokens)
            loss_sum += float(F.cross_entropy(table, batch["list_targets"], reduction="sum"))
            right += int((table.argmax(1) == batch["list_targets"]).sum())
            engine_right += sum(1 for item in chunk if max(range(len(item["engine"])), key=lambda i: item["engine"][i]) == item["target"])
    model.train()
    return {"loss": loss_sum / len(items), "right": right, "engine_right": engine_right, "lists": len(items)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", choices=sorted(BASES), default="distilgpt2")
    parser.add_argument("--method", choices=sorted(SETTINGS), required=True)
    parser.add_argument("--prompt-format", choices=rerank.PROMPT_FORMATS, default="typed")
    parser.add_argument("--no-context", action="store_true", help="train without the text before the span, as a control")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--memory-gb", type=float, default=3.0, help="cap of the PyTorch allocator on the GPU")
    parser.add_argument("--max-steps", type=int, help="stop after this many steps, for a smoke test")
    parser.add_argument("--limit-lists", type=int, help="use only this many training lists, for a smoke test")
    arguments = parser.parse_args()

    lower_priority()
    torch.set_num_threads(4)
    random.seed(arguments.seed)
    torch.manual_seed(arguments.seed)
    used_before = gpu_memory_used_mib()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available")
    device = torch.device("cuda", 0)
    total = torch.cuda.get_device_properties(0).total_memory
    torch.cuda.set_per_process_memory_fraction(arguments.memory_gb * 2**30 / total, 0)

    from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup
    base = BASES[arguments.base]
    tokenizer = AutoTokenizer.from_pretrained(base["repository"], revision=base["revision"])
    model = AutoModelForCausalLM.from_pretrained(base["repository"], revision=base["revision"], dtype=torch.float32)
    start_token = start_token_of(tokenizer)
    pad = tokenizer.eos_token_id
    vocabulary = model.get_output_embeddings().weight.shape[0]
    space_ids = space_token_ids(tokenizer, vocabulary)
    space_tokens = torch.tensor(space_ids, dtype=torch.long, device=device)

    settings = dict(SETTINGS[arguments.method])
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
    train_lists = read_lists(arguments.data / "lists.train.jsonl.gz")
    # The stopping split chooses the checkpoint. The tuning split stays for the re-ranker setting.
    stop_lists = read_lists(arguments.data / "lists.stop.jsonl.gz")
    if arguments.limit_lists:
        random.Random(arguments.seed).shuffle(train_lists)
        train_lists = train_lists[:arguments.limit_lists]
    train_items = encode(train_lists, tokenizer, start_token, arguments.prompt_format, arguments.no_context)
    tune_items = encode(stop_lists, tokenizer, start_token, arguments.prompt_format, arguments.no_context)
    encode_seconds = time.monotonic() - started

    steps_per_epoch = math.ceil(len(train_items) / BATCH_LISTS)
    total_steps = steps_per_epoch * MAX_EPOCHS
    if arguments.max_steps:
        total_steps = min(total_steps, arguments.max_steps)
    optimizer = torch.optim.AdamW(parameters, lr=settings["learning_rate"], betas=(0.9, 0.999), eps=1e-8)
    schedule = get_cosine_schedule_with_warmup(optimizer, WARMUP_STEPS, steps_per_epoch * MAX_EPOCHS)

    arguments.out.mkdir(parents=True, exist_ok=True)
    log = (arguments.out / "train-log.jsonl").open("w", encoding="utf-8")
    first = evaluate(model, tune_items, pad, space_tokens, device)
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
        for start in range(0, len(order), BATCH_LISTS):
            step_items = [train_items[i] for i in order[start:start + BATCH_LISTS]]
            optimizer.zero_grad(set_to_none=True)
            loss_sum = 0.0
            for micro in range(0, len(step_items), MICRO_LISTS):
                batch = make_batch(step_items[micro:micro + MICRO_LISTS], pad, device)
                table, _ = logits_of_lists(model, batch, space_tokens)
                # The mean over the lists of the whole step.
                loss = F.cross_entropy(table, batch["list_targets"], reduction="sum") / len(step_items)
                loss.backward()
                loss_sum += float(loss.detach())
            loss = torch.tensor(loss_sum)
            torch.nn.utils.clip_grad_norm_([p for group in parameters for p in group["params"]], GRADIENT_CLIP)
            optimizer.step()
            schedule.step()
            step += 1
            if step % 100 == 0:
                peak_used = max(peak_used, gpu_memory_used_mib())
                print(f"step {step} of {total_steps}, loss {float(loss):.4f}, {time.monotonic() - train_started:.0f} s", flush=True)
            if step % EVALUATE_EVERY == 0 or step == total_steps:
                result = evaluate(model, tune_items, pad, space_tokens, device)
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
                    if waited >= PATIENCE:
                        stopped = "early stop"
                        break
            if step >= total_steps:
                break
        if stopped == "early stop":
            break
    train_seconds = time.monotonic() - train_started
    log.close()

    if best["state"] is None:
        raise SystemExit("the tuning loss never fell below the loss before training")
    with torch.no_grad():
        named = dict(model.named_parameters())
        for name, value in best["state"].items():
            named[name].copy_(value.to(device))
    final = evaluate(model, tune_items, pad, space_tokens, device)
    if arguments.method == "lora":
        model = model.merge_and_unload()
    model.to("cpu").save_pretrained(arguments.out / "hf", safe_serialization=True)
    tokenizer.save_pretrained(arguments.out / "hf")
    result = {
        "base": base, "method": arguments.method, "settings": settings, "seed": arguments.seed,
        "batch_lists": BATCH_LISTS, "micro_lists": MICRO_LISTS, "warmup_steps": WARMUP_STEPS, "max_epochs": MAX_EPOCHS,
        "evaluate_every": EVALUATE_EVERY, "patience": PATIENCE, "gradient_clip": GRADIENT_CLIP,
        "prompt_format": arguments.prompt_format, "no_context": arguments.no_context,
        "start_token": start_token, "space_tokens": len(space_ids),
        "trained_weights": trained, "all_weights": every,
        "train_lists": len(train_items), "stop_lists": len(tune_items), "steps_per_epoch": steps_per_epoch,
        "steps": step, "stopped": stopped, "best_step": best["step"], "stop_before": first, "stop_best": final,
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

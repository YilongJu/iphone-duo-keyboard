"""Checks that the training code reads the same tokens, and gives the same scores, as the phone
path (scripts/lm-rerank/lm_score.c on the converted file).

Three steps, because the training code runs on Windows and lm_score on Linux:
1. prepare (Windows): samples lists of the tuning split. It writes the request lines that
   rerank.LanguageModel would send, the token ids of train.py, and, with --model-dir, the
   float32 PyTorch scores of the first 500 lists.
2. On Linux: lm_score MODEL 4 tokens < requests.tsv > llama-tokens.txt
             head -n 500 requests.tsv | lm_score MODEL-f16 4 > llama-scores.txt
3. compare: the token ids must match on every list, and the scores must agree within 0.05 nats.

Usage, from the repository root:
    uv run --project scripts/lm-finetune python scripts/lm-finetune/check_parity.py prepare \
        --data build/lm-finetune/data --prompt-format typed --model-dir MODEL/hf --out DIR
    uv run --project scripts/lm-finetune python scripts/lm-finetune/check_parity.py compare --out DIR
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import rerank  # noqa: E402

TOKEN_LISTS = 2000
SCORE_LISTS = 500
SCORE_LIMIT = 0.05


def prepare(arguments) -> None:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    import train

    lists = train.read_lists(arguments.data / "lists.tune.jsonl.gz")
    random.Random(20261110).shuffle(lists)
    lists = lists[:TOKEN_LISTS]
    source = arguments.model_dir if arguments.model_dir else train.BASES[arguments.base]["repository"]
    revision = None if arguments.model_dir else train.BASES[arguments.base]["revision"]
    tokenizer = AutoTokenizer.from_pretrained(source, revision=revision)
    items = train.encode(lists, tokenizer, train.start_token_of(tokenizer), arguments.prompt_format, arguments.no_context)
    arguments.out.mkdir(parents=True, exist_ok=True)
    with (arguments.out / "requests.tsv").open("w", encoding="utf-8", newline="\n") as requests, \
            (arguments.out / "hf-tokens.jsonl").open("w", encoding="utf-8") as tokens:
        for item, encoded in zip(lists, items):
            opens_field = not item["context"]
            context = "" if arguments.no_context else item["context"]
            prompt = rerank.language_model_prompt(context, item["typed"], arguments.prompt_format)
            candidates = [rerank.language_model_text(text, opens_field) for text, *_ in item["readings"]]
            requests.write("\t".join([prompt, *candidates]) + "\n")
            tokens.write(json.dumps({"prefix": encoded["prefix"], "readings": encoded["readings"]}) + "\n")
    report = {"lists": len(lists), "prompt_format": arguments.prompt_format, "no_context": arguments.no_context,
              "start_token": train.start_token_of(tokenizer),
              "space_tokens": len(train.space_token_ids(tokenizer, len(tokenizer)))}
    if arguments.model_dir:
        model = AutoModelForCausalLM.from_pretrained(arguments.model_dir, dtype=torch.float32).to("cuda").eval()
        vocabulary = model.get_output_embeddings().weight.shape[0]
        space_ids = train.space_token_ids(tokenizer, vocabulary)
        space_tokens = torch.tensor(space_ids, dtype=torch.long, device="cuda")
        report["space_tokens"] = len(space_ids)
        with (arguments.out / "hf-scores.jsonl").open("w", encoding="utf-8") as file, torch.no_grad():
            for start in range(0, SCORE_LISTS, 16):
                chunk = items[start:min(start + 16, SCORE_LISTS)]
                batch = train.make_batch(chunk, tokenizer.eos_token_id, "cuda")
                log_probability, space_after = train.reading_scores(model, batch, space_tokens, low_precision=False)
                index = 0
                for item in chunk:
                    count = len(item["readings"])
                    file.write(json.dumps([[float(log_probability[index + k]), float(space_after[index + k])] for k in range(count)]) + "\n")
                    index += count
    (arguments.out / "prepare.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


def without_ready_line(path: Path) -> tuple[str, list[str]]:
    """lm_score writes a ready line first, which names the count of space tokens."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].startswith("ready"):
        raise SystemExit(f"{path} does not start with the ready line of lm_score")
    return lines[0], lines[1:]


def compare(arguments) -> None:
    hf = [json.loads(line) for line in (arguments.out / "hf-tokens.jsonl").read_text(encoding="utf-8").splitlines()]
    ready, llama = without_ready_line(arguments.out / "llama-tokens.txt")
    if len(hf) != len(llama):
        raise SystemExit(f"{len(hf)} lists from the training code, {len(llama)} from lm_score")
    mismatches = []
    for number, (ours, line) in enumerate(zip(hf, llama)):
        fields = [[int(t) for t in field.split(" ")] for field in line.split("\t")]
        if fields[0] != ours["prefix"] or fields[1:] != ours["readings"]:
            mismatches.append({"list": number, "training": ours, "lm_score": fields})
    for number, line in enumerate(llama):
        fields = line.split("\t")
        if len(fields) < 2:
            raise SystemExit(f"line {number} of llama-tokens.txt holds no reading")
    report = {"lm_score_ready": ready, "token_lists": len(hf), "token_mismatches": len(mismatches),
              "first_mismatches": mismatches[:5]}
    prepared = json.loads((arguments.out / "prepare.json").read_text(encoding="utf-8"))
    if "space_tokens" in prepared:
        report["space_tokens_training"] = prepared["space_tokens"]
        if f"space_tokens={prepared['space_tokens']} " not in ready + " ":
            raise SystemExit(f"the training code marks {prepared['space_tokens']} space tokens, lm_score says {ready}")
        if f"start={prepared['start_token']} " not in ready + " ":
            raise SystemExit(f"the training code starts with token {prepared['start_token']}, lm_score says {ready}")
    scores_path = arguments.out / "hf-scores.jsonl"
    if scores_path.exists():
        ours = [json.loads(line) for line in scores_path.read_text(encoding="utf-8").splitlines()]
        theirs = [[[float(v) for v in field.split(" ")] for field in line.split("\t")]
                  for line in without_ready_line(arguments.out / "llama-scores.txt")[1]]
        if len(theirs) < len(ours):
            raise SystemExit(f"{len(ours)} scored lists from PyTorch, {len(theirs)} from lm_score")
        differences = [(abs(a[0] - b[0]), abs(a[1] - b[1])) for x, y in zip(ours, theirs) for a, b in zip(x, y)]
        report.update({"score_lists": len(ours), "score_readings": len(differences),
                       "largest_log_probability_difference": max(d[0] for d in differences),
                       "largest_space_after_difference": max(d[1] for d in differences),
                       "mean_log_probability_difference": sum(d[0] for d in differences) / len(differences),
                       "score_limit": SCORE_LIMIT})
    (arguments.out / "parity.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "first_mismatches"}))
    if mismatches:
        print(json.dumps(mismatches[:2]))
        raise SystemExit("the training tokens differ from the lm_score tokens")
    if scores_path.exists() and max(report["largest_log_probability_difference"], report["largest_space_after_difference"]) > SCORE_LIMIT:
        raise SystemExit(f"PyTorch and lm_score differ by more than {SCORE_LIMIT} nats")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["prepare", "compare"])
    parser.add_argument("--data", type=Path)
    parser.add_argument("--base", default="distilgpt2")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--prompt-format", choices=rerank.PROMPT_FORMATS, default="typed")
    parser.add_argument("--no-context", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    prepare(arguments) if arguments.step == "prepare" else compare(arguments)


if __name__ == "__main__":
    main()

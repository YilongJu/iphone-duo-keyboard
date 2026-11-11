"""Prints the comparison table of docs/lm-weight-edit-results.md from the result files.

It reads the stopping-split scores (build/lm-weight-edit/stop/*.jsonl), the dev results of
evaluate.py copied from WSL (build/lm-weight-edit/results/NAME/result.json, and the fine-tune's
own results under build/lm-weight-edit/results/finetune/NAME/result.json), the quantization
check (quant_loss.py) and the GGUF sizes in build/lm-weight-edit/results/gguf-sizes.txt.

Usage: python scripts/lm-weight-edit/collect.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build" / "lm-weight-edit"

# Rows: label, base, method as fit, gradient steps on this task, stop arm (or a fixed number with
# its source), dev result folder, parity folder.
ROWS = [
    ("s-stock", "SmolLM2-135M", "stock weights", "0", ("smollm2", "s-stock"), "smollm2-stock-q3", "smollm2-stock"),
    ("s-lora (fine-tune)", "SmolLM2-135M", "LoRA fine-tune, merged", "4,500", ("smollm2", "s-tv-1.0"), "smollm2-lora-seed1-q3", "smollm2-lora-seed1"),
    ("s-dare", "SmolLM2-135M", "DARE p 0.5 of tau, lam 1", "4,500 (inherited)", ("smollm2", "s-dare-p0.5-lam1.0"), "s-dare-p0.5-lam1.0", "s-dare-p0.5-lam1.0"),
    ("s-random", "SmolLM2-135M", "random direction, norm of tau, lam 1", "0", ("smollm2", "s-random-1.0"), "s-random-1.0", "s-random-1.0"),
    ("s-instruct", "SmolLM2-135M", "task vector of SmolLM2-135M-Instruct, lam 1", "0", ("smollm2", "s-instruct-1.0"), "s-instruct-1.0", "s-instruct-1.0"),
    ("s-steer", "SmolLM2-135M", "mean-reading attention-bias steering, block 22, alpha 2 (substitute for CAA)", "0", ("smollm2", "s-steer-L22-a2.0"), "s-steer-L22-a2.0", "s-steer-L22-a2.0"),
    ("s-tftv", "SmolLM2-135M", "TFTV, blocks 16 to 23, alpha 0.03", "0", ("smollm2", "s-tftv-b16-24-a0.03"), "s-tftv-b16-24-a0.03", "s-tftv-b16-24-a0.03"),
    ("s-stock, stock format, Q4_K_M", "SmolLM2-135M", "stock weights, stock input format (reference)", "0", None, "finetune/smollm2-stock", None),
    ("d-stock", "distilgpt2", "stock weights (shipped file)", "0", ("distilgpt2", "d-stock"), "finetune/stock-typed", None),
    ("d-stock, stock format", "distilgpt2", "stock weights, stock input format (reference)", "0", None, "finetune/stock-converted", None),
    ("d-lora (fine-tune)", "distilgpt2", "LoRA fine-tune seed 1, merged", "7,000", ("distilgpt2", "d-tv-lora-1.0"), "finetune/lora-seed1", "distilgpt2-lora-seed1"),
    ("d-lora seed 2 (fine-tune)", "distilgpt2", "LoRA fine-tune seed 2, merged", "6,000", None, "finetune/lora-seed2", None),
    ("d-full (fine-tune)", "distilgpt2", "full fine-tune seed 1", "2,000", ("distilgpt2", "d-tv-full-1.0"), "finetune/full-seed1", "distilgpt2-full-seed1"),
    ("d-tv-lora", "distilgpt2", "task vector of LoRA seed 1, lam 1.25", "7,000 (inherited)", ("distilgpt2", "d-tv-lora-1.25"), "d-tv-lora-1.25", "d-tv-lora-1.25"),
    ("d-tv-full", "distilgpt2", "task vector of full seed 1, lam 1.25", "2,000 (inherited)", ("distilgpt2", "d-tv-full-1.25"), "d-tv-full-1.25", "d-tv-full-1.25"),
    ("d-soup", "distilgpt2", "uniform soup of LoRA 1, LoRA 2, full 1", "15,000 (inherited)", ("distilgpt2", "d-soup3"), "d-soup3", "d-soup3"),
    ("d-ta", "distilgpt2", "task arithmetic of the three, lam 0.3", "15,000 (inherited)", ("distilgpt2", "d-ta3-0.3"), "d-ta3-0.3", "d-ta3-0.3"),
    ("d-ties", "distilgpt2", "TIES of the three, top 20 percent, lam 1", "15,000 (inherited)", ("distilgpt2", "d-ties3-1.0"), "d-ties3-1.0", "d-ties3-1.0"),
    ("d-dare", "distilgpt2", "DARE p 0.9 of the three, summed, lam 0.5", "15,000 (inherited)", ("distilgpt2", "d-dare3-0.5"), "d-dare3-0.5", "d-dare3-0.5"),
    ("d-random", "distilgpt2", "random direction, norm of tau LoRA 1, lam 1", "0", ("distilgpt2", "d-random-1.0"), "d-random-1.0", "d-random-1.0"),
    ("d-steer", "distilgpt2", "mean-reading attention-bias steering, block 3, alpha 8 (substitute for CAA)", "0", ("distilgpt2", "d-steer-L3-a8.0"), "d-steer-L3-a8.0", "d-steer-L3-a8.0"),
    ("d-tftv", "distilgpt2", "TFTV, blocks 2 and 3, alpha 0.15 (past the paper's grid)", "0", ("distilgpt2", "d-tftv-b2-4-a0.15"), "d-tftv-b2-4-a0.15", "d-tftv-b2-4-a0.15"),
]


def stop_scores() -> dict:
    scores = {}
    for base in ("smollm2", "distilgpt2"):
        for line in (OUT / "stop" / f"{base}.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            scores[(base, row["arm"]["name"])] = row["stop"]
    return scores


def main():
    stop = stop_scores()
    sizes = {}
    size_file = OUT / "results" / "gguf-sizes.txt"
    if size_file.exists():
        for line in size_file.read_text(encoding="utf-8").splitlines():
            name, size = line.rsplit(" ", 1)
            sizes[Path(name).name] = int(size)
    quant = {}
    parities = [OUT / "models" / row[6] / "parity" for row in ROWS
                if row[6] and (OUT / "models" / row[6] / "parity" / "llama-scores-quant.txt").exists()]
    for parity in parities:
        # A conversion still writing its Q3_K_M scores makes quant_loss.py stop; that arm shows as pending.
        answer = subprocess.run([sys.executable, str(Path(__file__).with_name("quant_loss.py")), str(parity)],
                                capture_output=True, text=True)
        if answer.returncode != 0:
            print(f"quant check pending for {parity.parent.name}: {answer.stderr.strip().splitlines()[-1]}", file=sys.stderr)
            continue
        entry = json.loads(answer.stdout)
        quant[entry["arm"]] = entry
    print("| Arm | Base | Edit, as fit | Gradient steps on this task | Stopping split right of 7,556 | Dev right of 6,799 at Q3_K_M | Published misspellings right of 751 | Parity lists right of 500, f16 then Q3_K_M | GGUF size, MB |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for label, base, method, steps, stop_key, dev_name, parity in ROWS:
        result_path = OUT / "results" / dev_name / "result.json"
        dev = published = "not run"
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            dev = f"{result['tuned']['dev']['right']:,}"
            published = f"{result['tuned']['published_dev']['right']:,}"
        q = quant.get(parity)
        parity_text = f"{q['f16']} / {q['q3_k_m']}" if q else "see fine-tune"
        model_file = json.loads(result_path.read_text(encoding="utf-8"))["model"] if result_path.exists() else None
        size = sizes.get(model_file)
        size_text = f"{size / 1e6:.1f}" if size else "n/a"
        stop_text = f"{stop[stop_key]['right']:,}" if stop_key else "n/a"
        print(f"| `{label}` | {base} | {method} | {steps} | {stop_text} | {dev} | {published} | {parity_text} | {size_text} |")


if __name__ == "__main__":
    main()

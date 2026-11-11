# Handoff of the weight-edit experiment for the English re-ranker

## Summary

No training-free weight edit improves the re-ranker on dev. Edits built from the existing
fine-tunes match those fine-tunes on dev, within the spread of two seeds.

To take over:

1. Read this file, then `docs/lm-weight-edit-design.md` (the reviewed design) and
   `scripts/lm-weight-edit/README.md` (the commands).
2. Run the `d-random-1.0` dev evaluation, which was stopped before it finished
   (section "Unfinished jobs").
3. Fill the `PENDING_*` markers and the `TABLE` line of `docs/lm-weight-edit-results.md`, with
   `python scripts/lm-weight-edit/collect.py` for the table. Remove this handoff file once the
   results document holds everything.

This handoff does not settle the test half, phone time or phone memory. The test half was never
read.

## Where everything lives

| Item | Windows path | WSL path |
| --- | --- | --- |
| Worktree, branch `engine/lm-edit` | `D:\Github\iphone-duo-keyboard\build\worktrees\lm-edit` | `/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit` |
| Scripts | `scripts\lm-weight-edit\` in the worktree | same, under `/mnt/d/...` |
| Design, results draft, this file | `docs\lm-weight-edit-design.md`, `docs\lm-weight-edit-results.md`, `docs\lm-weight-edit-handoff.md` | same |
| Arm files | `build\lm-weight-edit\arms\*.json` (git-ignored) | same |
| Stopping-split scores | `build\lm-weight-edit\stop\smollm2.jsonl`, `distilgpt2.jsonl`, with `*.log` | same |
| Steering and TFTV statistics | `build\lm-weight-edit\cache\statistics-*.pt` | same |
| Exported Hugging Face models, f16 GGUF, parity | `build\lm-weight-edit\models\NAME\hf`, `model-f16.gguf`, `parity\` | same |
| Q3_K_M and f16 GGUF of every arm | not on Windows | `/root/lmedit/models/NAME.Q3_K_M.gguf`, `NAME.f16.gguf` |
| evaluate.py output | copied by `copy_results.sh` to `build\lm-weight-edit\results\NAME\` | `/root/lmedit/results/NAME/` and `NAME.log` |
| Fine-tune results the comparison cites | `build\lm-weight-edit\results\finetune\NAME\` | `/root/lmft/results/NAME/` (fine-tune worker's, read only) |
| Codex review | `build\lm-weight-edit\review\design-request.txt`, `design-review.txt` | same |
| Helper shell files | `build\lm-weight-edit\stop_one.sh`, `quant_controls*.sh`, `quant_dg_controls.sh`, `eval_controls.sh` | same |

The scripts read the fine-tune worktree `build\worktrees\lm-finetune` and never write there. They
use its venv `build\lm-finetune\venv\Scripts\python.exe` (torch 2.8.0+cu128), its lists and models,
its `evaluate.py` and `check_parity.py`, and its WSL tools in `/root/lmft` (`lm_score`,
`libduo_shim.so`, `llama-quantize`, llama.cpp commit 10131b2).

## Search result and the methods kept

Table 1. Methods from the search, and their status in this work.

| Method | Status | Reason |
| --- | --- | --- |
| Task vector scaling, WiSE-FT interpolation (lam 0.25 to 3) | Run on both bases | Fits. Scaling a merged LoRA delta equals scaling the adapter's alpha. |
| Task arithmetic sum, uniform soup, TIES (authors' global trim), DARE | Run on distilgpt2 (three fine-tunes); DARE also on SmolLM2 | Fits. SmolLM2 has one fine-tune, so no merge of two vectors. |
| Task vector of SmolLM2-135M-Instruct (revision 12fd25f7) | Run | Training-free on this task |
| Training-Free Task Vectors, TFTV (Perin et al. 2026, arXiv 2609.09054) | Run | Training-free weight edit. Codex proposed it. |
| Contrastive activation addition | Run as a substitute, named "mean-reading attention-bias steering" | A weight edit adds a constant at every position, unlike CAA's answer positions. |
| ROME, MEMIT, AlphaEdit | Dropped | Fact edits keyed on one subject token; value vectors need gradient steps; no tested transfer to unseen pairs. The design gives the sources. |

## Design and review status

- `docs/lm-weight-edit-design.md` is final and holds the accepted review changes.
- Codex reviewed it once (`codex exec -c model_reasoning_effort=high`). Accepted: TIES now
  follows the authors' global trim and majority-sign rule; the steering arm is renamed as a
  substitute; a dropout bug is fixed (`train.evaluate` leaves GPT-2 in training mode, so
  `sweep.py` now calls `model.eval()` after every load); TFTV and shuffled-label controls are
  added; the ROME exclusion is softened; the stopping-split double search and the
  LoRA-alpha equivalence are stated; quantization loss is measured on identical lists.
- Rejected: none. Not done: Codex's request for several DARE seeds and random-vector samples, and a
  bootstrap over repeated contexts.
- The results document has not had a Codex review.

## Arms run so far

The stopping split is `lists.stop.jsonl.gz` (7,556 lists; engine alone 6,766). Dev is 6,799
generated cases (engine alone 6,069). Every dev number is Q3_K_M, typed format, setting from the
tuning split (6,748 cases), from `evaluate.py --skip-dev-grid`.

Table 2. Every arm that reached dev. The GGUF files are in `/root/lmedit/models` unless the row
says `/root/lmft/models` (the fine-tune worker's).

| Arm | Stopping split right | Tuned setting (weight, margins from/to/other, space-after) | Dev right | Clean / clean-symbol right (control 957 / 427) | Published misspellings right of 751 | GGUF file, size |
| --- | --- | --- | --- | --- | --- | --- |
| SmolLM2 stock | 6,492 | 0.75, 3/4/2, 1 | 6,084 | 948 / 426 | 394 | `smollm2-stock.Q3_K_M.gguf`, 93.5 MB |
| SmolLM2 LoRA fine-tune | 7,318 (train.py says 7,319) | 1.5, 2/4/2, 1 | 6,537 | 955 / 427 | 372 | `smollm2-lora-seed1.Q3_K_M.gguf`, 93.5 MB |
| `s-dare-p0.5-lam1.0` | 7,319 | 1.5, 1/4/2, 1 | 6,546 | 957 / 428 | 378 | 93.5 MB |
| `s-random-1.0` | 6,489 | 0.5, 6/8/2, 1 | 6,075 | 957 / 427 | 384 | 93.5 MB |
| `s-instruct-1.0` | 6,392 | 0.5, 3/4/2, 0 | 6,096 | 952 / 426 | 386 | 93.5 MB |
| `s-steer-L22-a2.0` | 6,634 | 0.5, 6/4/2, 0 | 6,080 | 956 / 427 | 385 | 93.7 MB |
| `s-tftv-b16-24-a0.03` | 6,661 | 0.5, 4/0/2, 0 | 6,068 | 948 / 426 | 382 | 93.5 MB |
| distilgpt2 stock, typed format (fine-tune worker's `stock-typed`) | 5,839 | from its log | 6,087 | 954 / 427 | 386 | `/root/lmft/models/distilgpt2.Q3_K_M.gguf`, 75.4 MB |
| distilgpt2 LoRA seed 1 (worker's) | 7,235 | from its log | 6,491 | 945 / 427 | 367 | `/root/lmft/models/lora-seed1.Q3_K_M.gguf`, 75.4 MB |
| distilgpt2 LoRA seed 2 (worker's) | 7,236 in its train-result.json | from its log | 6,486 | 950 / 429 | 328 | `/root/lmft/models`, 75.4 MB |
| distilgpt2 full seed 1 (worker's) | 7,196 | from its log | 6,451 | 956 / 429 | 369 | `/root/lmft/models/full-seed1.Q3_K_M.gguf`, 75.4 MB |
| `d-tv-lora-1.25` | 7,239 | 1.0, 1/0/0, 1 | 6,477 | 951 / 426 | 341 | 75.4 MB |
| `d-soup3` | 7,246 | 1.5, 4/4/2, 1 | 6,481 | 954 / 429 | 356 | 75.4 MB |
| `d-ta3-0.3` | 7,228 | 1.5, 2/4/2, 1 | 6,467 | 948 / 427 | 362 | 75.4 MB |
| `d-ties3-1.0` | 7,247 | 1.0, 1/0/2, 1 | 6,502 | 954 / 428 | 345 | 75.4 MB |
| `d-tv-full-1.25` | 7,197 | 1.0, 2/0/2, 1 | 6,460 | 956 / 426 | 362 | 75.4 MB |
| `d-dare3-0.5` | 7,212 | 0.75, 2/0/0, 1 | 6,488 | 959 / 427 | 351 | 75.4 MB |
| `d-steer-L3-a8.0` | 6,628 | 0.75, 6/4/2, 0 | 6,049 | 946 / 427 | 370 | 75.4 MB |
| `d-tftv-b2-4-a0.15` | 6,641 | 0.5, 6/2/2, 0 | 6,071 | 956 / 427 | 384 | 75.4 MB |

Table 3. Paired dev comparisons (exact McNemar, `scripts/lm-weight-edit/paired.py`).

| Arm A | Arm B | Right only by A | Right only by B | p |
| --- | --- | --- | --- | --- |
| `s-dare-p0.5-lam1.0` | SmolLM2 LoRA Q3_K_M | 29 | 20 | 0.25 |
| SmolLM2 LoRA Q3_K_M | SmolLM2 LoRA Q4_K_M (6,543) | 35 | 41 | 0.57 |
| `s-instruct-1.0` | SmolLM2 stock | 40 | 28 | 0.18 |
| `s-steer-L22-a2.0` | SmolLM2 stock | 38 | 42 | 0.74 |
| `s-tftv-b16-24-a0.03` | SmolLM2 stock | 25 | 41 | 0.064 |
| `d-ties3-1.0` | distilgpt2 LoRA seed 1 | 38 | 27 | 0.21 |
| `d-soup3` | distilgpt2 LoRA seed 1 | 32 | 42 | 0.30 |
| `d-tv-lora-1.25` | distilgpt2 LoRA seed 1 | 35 | 49 | 0.16 |
| `d-ta3-0.3` | distilgpt2 LoRA seed 1 | 25 | 49 | 0.0071 |
| `d-tv-full-1.25` | distilgpt2 full seed 1 | 42 | 33 | 0.36 |
| `d-dare3-0.5` | distilgpt2 LoRA seed 1 | 54 | 57 | 0.85 |
| `d-steer-L3-a8.0` | distilgpt2 stock typed | 45 | 83 | 0.001 |
| `d-tftv-b2-4-a0.15` | distilgpt2 stock typed | 48 | 64 | 0.16 |
| distilgpt2 LoRA seed 2 | distilgpt2 LoRA seed 1 | 51 | 56 | 0.70 |

Every stopping-split score of every arm, 162 in all, is in `build/lm-weight-edit/stop/*.jsonl`.
The selection winners, by `select_arms.py`, are the rows above plus the control `d-random-1.0`
(5,852), which has not reached dev. Shuffled-label controls on the
stopping split: `s-steer` 6,488, `s-tftv` 6,485, `d-steer` 5,820, `d-tftv` 6,317.

Quantization loss on the 500 parity lists (lists right at f16, then Q3_K_M), from
`quant_loss.py`: SmolLM2 stock 446 / 437, LoRA 489 / 486, `s-dare` 489 / 486, `s-random`
442 / 435, `s-instruct` 435 / 426, `s-steer` 445 / 447, `s-tftv` 447 / 446; distilgpt2 LoRA 1
477 / 478, full 1 478 / 476, `d-tv-lora` 478 / 479, `d-tv-full` 478 / 475, `d-soup` 480 / 476,
`d-ta` 477 / 477, `d-ties` 482 / 478, `d-dare` 476 / 477, `d-random` 397 / 406, `d-steer`
441 / 441, `d-tftv` 442 / 442.

## Unfinished jobs and the commands to resume them

Every chosen arm has a dev result except `d-random-1.0`, which was stopped on purpose. Check the
WSL runs and copy the results:

```bash
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit/scripts/lm-weight-edit/eval_status.sh
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit/scripts/lm-weight-edit/copy_results.sh
```

Rerun `d-random-1.0`. It takes 45 to 60 minutes at the lowest priority:

```bash
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit/scripts/lm-weight-edit/eval_queue.sh 1 d-random-1.0
```

Then, from the worktree in Git Bash:

```bash
python scripts/lm-weight-edit/collect.py > build/lm-weight-edit/results/table.md
R=build/lm-weight-edit/results
python scripts/lm-weight-edit/paired.py $R/d-random-1.0/tuned.dev.jsonl $R/finetune/stock-typed/tuned.dev.jsonl
```

The fine-tune worker's `full-seed2` dev run was still going. `copy_results.sh` copies it once it
exists.

## Problems met, with the exact errors

- `codex exec` waited for input: its stderr said `Reading additional input from stdin...`. Run it
  with `< /dev/null`.
- `wsl ... bash -c "nohup ... &"` did not survive the `wsl` call's exit. Run WSL jobs as a
  foreground `wsl` command inside a background tool call.
- Git Bash expands `$VAR` and `~` inside `wsl -- bash -lc '...'` quoting, and it rewrites
  `/mnt/...` arguments. Put WSL commands in a script file and call it with
  `MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash /mnt/d/.../script.sh`.
- A Python patch on Windows wrote CRLF line ends, and bash then failed with
  `set: pipefail: invalid option name`. Fixed with `sed -i 's/\r$//'`. Git warns
  `LF will be replaced by CRLF the next time Git touches it`: after a fresh checkout, run that
  `sed` on `scripts/lm-weight-edit/*.sh` before WSL runs them.
- `collect.py` stopped on `CalledProcessError` while a conversion still wrote its Q3_K_M scores
  (`464 lists, expected 500`). It now reports such an arm as pending.
- Three distilgpt2 arms fail the 0.05-nat score check of `check_parity.py` with
  `PyTorch and lm_score differ by more than 0.05 nats`: `d-tv-lora-1.25` 0.0572, `d-ta3-0.3`
  0.0509, `d-tftv-b2-4-a0.15` 0.0565. Each has one reading over the limit of 3,982, and tokens
  match on all 2,000 lists. Mean gaps are 0.0070 to 0.0078 nats, as the fine-tunes' 0.0074. The
  check was left unchanged.
- The distilgpt2 steer and TFTV optima sat at the edge of the design grid (alpha 8, and alpha past
  the paper's 0.05). The grids were extended on the stopping split only
  (`arms/distilgpt2-extension.json`). The winners stayed alpha 8 for steer and became alpha 0.15
  for TFTV.
- The first SmolLM2 sweep process was stopped after the instruct arms, so the steer arms run with
  the fixed code. No arm was scored twice.
- The SmolLM2 stopping score at lam 1 is 7,318, one list below the 7,319 of
  `train-result.json`, with the same loss to 5 digits.

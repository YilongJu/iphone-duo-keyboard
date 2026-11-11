# Handoff of the weight-edit experiment for the English re-ranker

## Summary

Round 1 is measured: no training-free weight edit improves the re-ranker on dev. Round 2, the
WiSE-FT interpolation, has a fixed design and running jobs, and it does not have a dev score yet.

To take over:

1. Read `docs/lm-weight-edit-design.md`, from "Interpolation between stock and fine-tuned weights
   for the clean dev cases" to "Shared held-out cases of the second fine-tuning round".
2. Print the state of every arm with the two commands of step 1 in "Commands to resume round 2".
3. Run the remaining steps of that section. Every step skips the arms that are done.
4. Read the answer from `python scripts/lm-weight-edit/interp_report.py s d d2`.
5. Leave the items of "Backlog of round 1" alone, unless an interpolation result needs one as a
   control.

This handoff does not settle the interpolation question, the test half, phone time or phone
memory. The test half was never read.

## Arm labels of round 2

Table 1. The labels of round 2. Every arm is a Q3_K_M file in the typed format.

| Label | Edit, in plain words | Why it exists |
| --- | --- | --- |
| `s-wise-a` | SmolLM2-135M weights at (1 - a) stock + a LoRA fine-tune, a from 0.1 to 0.9 | The interpolation test on SmolLM2 |
| `d-wise-a` | distilgpt2 weights at (1 - a) stock + a LoRA fine-tune seed 1 | The interpolation test on distilgpt2 |
| `d2-wise-a` | The same from the LoRA fine-tune seed 2 | Shows how far a pass depends on the fine-tuning seed |
| `s-stock`, `d-stock`, `d2-stock` | a = 0, the stock model in the typed format | The lower end of each curve |
| `s-lora`, `d-lora`, `d2-lora` | a = 1, the fine-tune, with nine calibration-only candidate settings | The upper end, and the control for the re-ranker setting |
| `s-random-1.0-seedN`, `d-random-1.0-seedN` | A random direction with the task vector's norm, seeds 2 to 5 | Backlog: the spread of the random-edit control |

WiSE-FT interpolation at a equals task vector scaling at lam = a for one fine-tune. So one arm per
coefficient covers both methods.

## Where everything lives

Table 2. Paths of the work. `build` is git-ignored.

| Item | Windows path under the worktree `D:\Github\iphone-duo-keyboard\build\worktrees\lm-edit` | WSL path |
| --- | --- | --- |
| Scripts | `scripts\lm-weight-edit\` | `/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit/scripts/lm-weight-edit` |
| Design, results draft, this file | `docs\lm-weight-edit-design.md`, `docs\lm-weight-edit-results.md`, `docs\lm-weight-edit-handoff.md` | same under `/mnt/d` |
| Arm files | `build\lm-weight-edit\arms\*.json`; round 2 in `smollm2-round2.json` and `distilgpt2-round2.json` | same |
| Stopping-list scores | `build\lm-weight-edit\stop\smollm2.jsonl`, `distilgpt2.jsonl`; round 2 in `*-round2.jsonl` | same |
| Exported models, f16 GGUF, parity | `build\lm-weight-edit\models\NAME\hf`, `model-f16.gguf`, `parity\` | same |
| Q3_K_M GGUF of every arm | not on Windows | `/root/lmedit/models/NAME.Q3_K_M.gguf` |
| `evaluate.py` output | copied by `copy_results.sh` to `build\lm-weight-edit\results\NAME\` | `/root/lmedit/results/NAME/` and `NAME.log` |
| `eval_extra.py` output | copied by `copy_results.sh` to `build\lm-weight-edit\extra\NAME\` | `/root/lmedit/extra/NAME/` |
| Fine-tune results the comparison cites | `build\lm-weight-edit\results\finetune\NAME\` | `/root/lmft/results/NAME/` (fine-tune worker's, read only) |
| Round 1 paired tests | `build\lm-weight-edit\results\paired-round1.jsonl` | same |
| Codex reviews | `build\lm-weight-edit\review\design-review.txt`, `interp-design-review.txt`, with their requests | same |

The scripts read the fine-tune worktree `build\worktrees\lm-finetune` and never write there. They
use its venv `build\lm-finetune\venv\Scripts\python.exe` (torch 2.8.0+cu128), its lists and models,
its `evaluate.py` and `check_parity.py`, and its WSL tools in `/root/lmft` (`lm_score`,
`libduo_shim.so`, `llama-quantize`, llama.cpp commit 10131b2).

## Design and review status

- The interpolation grid, the selection rule and the dev criteria are in commit `7783c50`. That
  commit came before any interpolated arm met dev. The logs of the stopped runs hold the control
  line only, which is the engine alone.
- Grid: a in 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, for `s-wise`, `d-wise` and `d2-wise`.
- Selection rule: a coefficient is eligible when its clean and clean-symbol groups on the 6,740
  stopping cases hold at least the control's counts. The eligible value with the most right
  stopping cases is chosen, and a tie goes to the smaller coefficient.
- Dev criteria for the chosen coefficient: at least 957 of 973 clean and 427 of 429 clean-symbol
  dev cases, and more than half of the dev gain between a = 0 and a = 1.
- Controls: dev at one common setting per base, and nine calibration-only candidate settings of
  the fine-tune that get the same selection on the stopping cases.

Codex reviewed the round 1 design once and the interpolation design once, each before its dev
runs. For the interpolation design (`codex exec -c model_reasoning_effort=medium`), these points were
accepted and are in the design:

1. A pass is a pass of the observed counts. The report adds paired tests per clean group.
2. The calibration-only candidates and the common setting were added as controls.
3. The wording about Wortsman et al. was corrected. They report accuracy under distribution
   shift, and they do not promise the stock model's choice on each input.
4. The stock models in the typed format already sit below the control on clean dev cases (948
   and 954 against 957). The design says so.
5. The stopping cases choose a coefficient and are not evidence for it.
6. The report gives broken and repaired clean cases, and a bootstrap interval of the half-gain.
7. `d2-wise` repeats the test on the second LoRA seed.

One point was not adopted: a pre-set size of acceptable clean loss with a confidence bound. The
request fixes the rule as "at or above the engine-alone count", so the design keeps that rule.

For the round 1 design, every Codex point was accepted. Not done from that review: several DARE
seeds. The results document has not had a Codex review.

## Round 1 arms on dev

The stopping split is `lists.stop.jsonl.gz` (7,556 lists; engine alone 6,766). Dev is 6,799
generated cases (engine alone 6,069). Every dev number is Q3_K_M, typed format, setting from the
tuning split (6,748 cases), from `evaluate.py --skip-dev-grid`.

Table 3. Every arm that reached dev. The GGUF files are in `/root/lmedit/models` unless the row
says `/root/lmft/models` (the fine-tune worker's). Edits that start from a fine-tune land within
about 30 dev cases of it. Edits without a gradient step land within 40 of the stock model.

| Arm | Stopping split right | Tuned setting (weight, margins from/to/other, space-after) | Dev right | Clean / clean-symbol right (control 957 / 427) | Published misspellings right of 751 | GGUF file, size |
| --- | --- | --- | --- | --- | --- | --- |
| SmolLM2 stock | 6,492 | 0.75, 3/4/2, 1 | 6,084 | 948 / 426 | 394 | `smollm2-stock.Q3_K_M.gguf`, 93.5 MB |
| SmolLM2 LoRA fine-tune | 7,318 (train.py says 7,319) | 1.5, 2/4/2, 1 | 6,537 | 955 / 427 | 372 | `smollm2-lora-seed1.Q3_K_M.gguf`, 93.5 MB |
| `s-dare-p0.5-lam1.0` | 7,319 | 1.5, 1/4/2, 1 | 6,546 | 957 / 428 | 378 | 93.5 MB |
| `s-random-1.0` | 6,489 | 0.5, 6/8/2, 1 | 6,075 | 957 / 427 | 384 | 93.5 MB |
| `s-instruct-1.0` | 6,392 | 0.5, 3/4/2, 0 | 6,096 | 952 / 426 | 386 | 93.5 MB |
| `s-steer-L22-a2.0` (substitute for contrastive activation addition) | 6,634 | 0.5, 6/4/2, 0 | 6,080 | 956 / 427 | 385 | 93.7 MB |
| `s-tftv-b16-24-a0.03` | 6,661 | 0.5, 4/0/2, 0 | 6,068 | 948 / 426 | 382 | 93.5 MB |
| distilgpt2 stock, typed format (fine-tune worker's `stock-typed`) | 5,839 | 0.3, 3/2/0, 1 | 6,087 | 954 / 427 | 386 | `/root/lmft/models/distilgpt2.Q3_K_M.gguf`, 75.4 MB |
| distilgpt2 LoRA seed 1 (worker's) | 7,235 | 1.5, 1/4/2, 1 | 6,491 | 945 / 427 | 367 | `/root/lmft/models/lora-seed1.Q3_K_M.gguf`, 75.4 MB |
| distilgpt2 LoRA seed 2 (worker's) | 7,236 in its train-result.json | 1.0, 1/0/0, 1 | 6,486 | 950 / 429 | 328 | `/root/lmft/models`, 75.4 MB |
| distilgpt2 full seed 1 (worker's) | 7,196 | 1.5, 4/4/2, 1 | 6,451 | 956 / 429 | 369 | `/root/lmft/models/full-seed1.Q3_K_M.gguf`, 75.4 MB |
| `d-tv-lora-1.25` | 7,239 | 1.0, 1/0/0, 1 | 6,477 | 951 / 426 | 341 | 75.4 MB |
| `d-soup3` | 7,246 | 1.5, 4/4/2, 1 | 6,481 | 954 / 429 | 356 | 75.4 MB |
| `d-ta3-0.3` | 7,228 | 1.5, 2/4/2, 1 | 6,467 | 948 / 427 | 362 | 75.4 MB |
| `d-ties3-1.0` | 7,247 | 1.0, 1/0/2, 1 | 6,502 | 954 / 428 | 345 | 75.4 MB |
| `d-tv-full-1.25` | 7,197 | 1.0, 2/0/2, 1 | 6,460 | 956 / 426 | 362 | 75.4 MB |
| `d-dare3-0.5` | 7,212 | 0.75, 2/0/0, 1 | 6,488 | 959 / 427 | 351 | 75.4 MB |
| `d-steer-L3-a8.0` (substitute for contrastive activation addition) | 6,628 | 0.75, 6/4/2, 0 | 6,049 | 946 / 427 | 370 | 75.4 MB |
| `d-tftv-b2-4-a0.15` | 6,641 | 0.5, 6/2/2, 0 | 6,071 | 956 / 427 | 384 | 75.4 MB |

Table 4. Paired dev comparisons from `scripts/lm-weight-edit/paired.py`: the exact McNemar test,
and the 95 percent interval of A less B. The interval resamples the 6,225 groups of one context
and one intended text, 10,000 times. Two edits differ from their reference with an interval
that excludes 0, `d-ta3-0.3` and `d-steer-L3-a8.0`, and both get fewer dev cases right. The
interval of every other edit includes 0.

| Arm A | Arm B | Right only by A | Right only by B | A less B | McNemar p | 95% interval |
| --- | --- | --- | --- | --- | --- | --- |
| `s-dare-p0.5-lam1.0` | SmolLM2 LoRA Q3_K_M | 29 | 20 | +9 | 0.25 | -6 to +25 |
| SmolLM2 LoRA Q3_K_M | SmolLM2 LoRA Q4_K_M (6,543) | 35 | 41 | -6 | 0.57 | -25 to +12 |
| `s-instruct-1.0` | SmolLM2 stock | 40 | 28 | +12 | 0.18 | -6 to +29 |
| `s-steer-L22-a2.0` | SmolLM2 stock | 38 | 42 | -4 | 0.74 | -25 to +16 |
| `s-tftv-b16-24-a0.03` | SmolLM2 stock | 25 | 41 | -16 | 0.064 | -36 to +3 |
| `s-random-1.0` | SmolLM2 stock | 37 | 46 | -9 | 0.38 | -31 to +11 |
| `d-ties3-1.0` | distilgpt2 LoRA seed 1 | 38 | 27 | +11 | 0.21 | -4 to +27 |
| `d-soup3` | distilgpt2 LoRA seed 1 | 32 | 42 | -10 | 0.30 | -26 to +7 |
| `d-tv-lora-1.25` | distilgpt2 LoRA seed 1 | 35 | 49 | -14 | 0.16 | -32 to +4 |
| `d-ta3-0.3` | distilgpt2 LoRA seed 1 | 25 | 49 | -24 | 0.0071 | -41 to -7 |
| `d-tv-full-1.25` | distilgpt2 full seed 1 | 42 | 33 | +9 | 0.36 | -8 to +27 |
| `d-dare3-0.5` | distilgpt2 LoRA seed 1 | 54 | 57 | -3 | 0.85 | -24 to +18 |
| `d-steer-L3-a8.0` | distilgpt2 stock typed | 45 | 83 | -38 | 0.001 | -65 to -12 |
| `d-tftv-b2-4-a0.15` | distilgpt2 stock typed | 48 | 64 | -16 | 0.16 | -41 to +7 |
| distilgpt2 LoRA seed 2 | distilgpt2 LoRA seed 1 | 51 | 56 | -5 | 0.70 | -26 to +16 |
| distilgpt2 full seed 2 (6,503) | distilgpt2 full seed 1 | 93 | 41 | +52 | below 0.0001 | +29 to +75 |
| SmolLM2 LoRA Q3_K_M | SmolLM2 stock | 497 | 44 | +453 | below 0.0001 | +396 to +518 |
| distilgpt2 LoRA seed 1 | distilgpt2 stock typed | 461 | 57 | +404 | below 0.0001 | +347 to +468 |

The two seeds of the full fine-tune differ by 52 dev cases, with an interval of +29 to +75. So
the spread between fine-tuning seeds is wider than any gap between an edit and its fine-tune.

Every stopping-split score of round 1, 162 in all, is in `build/lm-weight-edit/stop/smollm2.jsonl`
and `distilgpt2.jsonl`. Shuffled-label controls on the stopping split: `s-steer` 6,488, `s-tftv`
6,485, `d-steer` 5,820, `d-tftv` 6,317.

Quantization loss on the 500 parity lists (lists right at f16, then Q3_K_M), from
`quant_loss.py`: SmolLM2 stock 446 / 437, LoRA 489 / 486, `s-dare` 489 / 486, `s-random`
442 / 435, `s-instruct` 435 / 426, `s-steer` 445 / 447, `s-tftv` 447 / 446; distilgpt2 LoRA 1
477 / 478, full 1 478 / 476, `d-tv-lora` 478 / 479, `d-tv-full` 478 / 475, `d-soup` 480 / 476,
`d-ta` 477 / 477, `d-ties` 482 / 478, `d-dare` 476 / 477, `d-random` 397 / 406, `d-steer`
441 / 441, `d-tftv` 442 / 442.

## State of round 2 at 23:55 on 10 November 2026

Round 2 holds 35 arms. The user paused all jobs at 22:55 and allowed them again at 23:50, for
the interpolation arms only.

Table 5. Each group of round 2 arms at 23:55. "Converted" means the Q3_K_M file is in WSL and
`check_parity.py` has written `parity/parity.json`.

| Group | Arms | Stopping-list scores | Converted | Stopped part-way at the pause | Dev evaluation |
| --- | --- | --- | --- | --- | --- |
| `s-wise` | 9 | all 9 | 0.1, 0.2 | 0.3 (parity scores at 70 of 500 lists), 0.4 (quantized), 0.5, 0.6 (empty folder), 0.7 (export part-way) | none finished |
| `d-wise` | 9 | all 9 | 0.1, 0.2 | 0.3 (quantized), 0.4 (empty folder) | none finished |
| `d2-wise` | 9 | all 9 | 0.1, 0.2 | 0.3 (empty folder), 0.4 (exported) | none finished |
| reference rows | 6 | from round 1 | from round 1 | `eval_extra.py` wrote the control predictions only | none finished |
| `s-random` seeds 2 to 5 | 4 | all 4 | none | none | backlog |
| `d-random` seeds 2 to 5 | 4 | all 4 | none | none | backlog |

Jobs running since 23:50, with a budget of 14 threads for the night:

- Two conversion streams of `export_convert.sh`: `s-wise-0.3` to `0.9` then `d2-wise-0.6` to
  `0.9`, and `d-wise-0.3` to `0.9` then `d2-wise-0.3` to `0.5`. They convert the part-way arms
  again from the export.
- `round2_queue.sh 3 references s-wise`, and `round2_queue.sh 4 d-wise d2-wise` after the first
  conversion stream ends.

A GPU job is not running, and `build/gpu.lock` does not exist.

Table 6. Lists right of 7,556 on the stopping split at weight 1, for the round 2 arms. The engine
alone gets 6,766. The larger the coefficient, the more lists right, and a = 0.9 lies within 6
lists of the fine-tune in all three columns.

| a | `s-wise` | `d-wise` | `d2-wise` |
| --- | --- | --- | --- |
| 0 (stock) | 6,492 | 5,839 | 5,839 |
| 0.1 | 6,712 | 6,306 | 6,358 |
| 0.2 | 6,872 | 6,643 | 6,716 |
| 0.3 | 7,053 | 6,881 | 6,916 |
| 0.4 | 7,141 | 7,032 | 7,055 |
| 0.5 | 7,210 | 7,116 | 7,117 |
| 0.6 | 7,254 | 7,161 | 7,172 |
| 0.7 | 7,289 | 7,205 | 7,205 |
| 0.8 | 7,304 | 7,225 | 7,227 |
| 0.9 | 7,316 | 7,241 | 7,233 |
| 1 (fine-tune) | 7,318 | 7,235 | 7,236 (from its train-result.json) |

The random-edit seeds at lam 1 on the same lists: `s-random` seeds 1 to 5 get 6,489, 6,501,
6,510, 6,481 and 6,506, against 6,492 for the stock model. `d-random` seeds 1 to 5 get 5,852,
5,897, 5,864, 5,948 and 5,908, against 5,839. These numbers are in `stop/*-round2.jsonl`.

Three scripts have not finished a run yet: `eval_extra.py`, `interp_report.py` and the committed
`export_convert.sh`. `eval_extra.py` ran for about 13 minutes on the six reference rows
before the pause and wrote the control predictions. `interp_report.py` passed a syntax check only.
The `--status` mode of `export_convert.sh` ran, and it reports the states of Table 5.

## Commands to resume round 2

Run them from Git Bash. Each step skips the arms that are done. While the user works on the
desktop, run at most 4 jobs of 2 threads. On 10 November, up to 17 evaluation jobs and 4
conversion streams ran at once. The load reached 28 on 32 logical cores, and the user stopped them.

```bash
cd /d/Github/iphone-duo-keyboard/build/worktrees/lm-edit
sed -i 's/\r$//' scripts/lm-weight-edit/*.sh
Q=/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit/scripts/lm-weight-edit

# 1. State of every arm. Both commands only read.
bash scripts/lm-weight-edit/export_convert.sh --status s-wise-0.{1..9} d-wise-0.{1..9} d2-wise-0.{1..9}
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash $Q/eval_status.sh

# 2. Conversions, one stream after the other. A stream uses up to 4 threads and no GPU.
bash scripts/lm-weight-edit/export_convert.sh smollm2-135m build/lm-weight-edit/arms/smollm2-round2.json s-wise-0.{1..9}
bash scripts/lm-weight-edit/export_convert.sh distilgpt2 build/lm-weight-edit/arms/distilgpt2-round2.json d-wise-0.{1..9} d2-wise-0.{1..9}

# 3. Evaluations: one queue, 4 jobs of 2 threads. Start it once only.
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash $Q/round2_queue.sh 4 references s-wise d-wise d2-wise

# 4. Copy the results to Windows, then print the tables, the chosen coefficient and the criteria.
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash $Q/copy_results.sh
python scripts/lm-weight-edit/interp_report.py s d d2 --json build/lm-weight-edit/results/interp.json \
    > build/lm-weight-edit/results/interp.md
```

These steps do not need the GPU. Every stopping-list score of round 2 exists. Run each long step
as a foreground command inside a background tool call. A job started with
`nohup` inside `wsl ... bash -c` ends when the `wsl` call returns. To stop every job of this work,
stop four kinds of process in WSL: `round2_queue.sh`, `evaluate.py` with `--out /root/lmedit/`,
`eval_extra.py`, and their `lm_score` children. Then stop `export_convert.sh`, `convert_edit.sh`
and their Python children on Windows.

One SmolLM2 evaluation took 47 to 67 minutes at 2 threads in round 1, and one distilgpt2
evaluation took 28 to 48 minutes. `eval_extra.py` adds the stopping cases to each, and its time
is not measured yet.

## Backlog of round 1

The user moved these items to the backlog on 10 November. They are not running.

- The dev run of `d-random-1.0`. Its conversion is done. `round2_queue.sh 4 d-random` runs it
  with seeds 2 to 5.
- The random-edit seeds 2 to 5. Their stopping-list scores exist. Convert them with
  `export_convert.sh ... s-random-1.0-seed{2..5}` and `d-random-1.0-seed{2..5}`, then run
  `round2_queue.sh 4 s-random d-random`. `collect.py` does not have rows for them yet.
- `docs/lm-weight-edit-results.md` still holds the `PENDING_*` markers and the `TABLE` line.
  `python scripts/lm-weight-edit/collect.py` prints the table. Codex has not reviewed that file.
- Several DARE seeds, which Codex asked for in the round 1 review.

## Problems met, with the exact errors

- `codex exec` waited for input: its stderr said `Reading additional input from stdin...`. Run it
  with `< /dev/null`.
- `wsl ... bash -c "nohup ... &"` did not survive the `wsl` call's exit. Run WSL jobs as a
  foreground `wsl` command inside a background tool call.
- Git Bash expands `$VAR` and `~` inside `wsl -- bash -lc '...'` quoting, and it rewrites
  `/mnt/...` arguments. Put WSL commands in a script file and call it with
  `MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash /mnt/d/.../script.sh`.
- A Python patch on Windows wrote CRLF line ends, and bash then stopped with
  `set: pipefail: invalid option name`. Fixed with `sed -i 's/\r$//'`. Git warns
  `LF will be replaced by CRLF the next time Git touches it`: after a fresh checkout, run that
  `sed` on `scripts/lm-weight-edit/*.sh` before WSL runs them.
- `collect.py` stopped on `CalledProcessError` while a conversion still wrote its Q3_K_M scores
  (`464 lists, expected 500`). It now reports such an arm as pending.
- Three distilgpt2 arms exceed the 0.05-nat score check of `check_parity.py` with
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
- A stopped conversion left a part-written `parity/llama-scores-quant.txt` for `s-wise-0.3`. The
  first conversion loop took any non-empty file as "converted", and so did the queue. Both now
  need `parity/parity.json`, which `check_parity.py` writes last.
- A command of the shape `cd DIR && X=... && ( A ) & ( B ) & wait` set `X` in the first
  background job only. The second job printed `bash: distilgpt2: No such file or directory`. Start
  each stream as its own command.
- Two queues with the same group run the same arm twice, because a queue checks for a finished
  result only when it reaches the arm. Start one queue per group.
- `paired.py` takes about 20 seconds per pair for its 10,000 bootstrap draws. Its output through
  `tee` appears only when the whole command ends.

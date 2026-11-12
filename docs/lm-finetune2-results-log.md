# Log of the held-out read of round 2

This file is a log. It records the one read of the held-out set, with its stop and its second part.
`scripts/lm-finetune2/README.md` holds the results.

## Events in order

Table 1. The events of the read, in local time (UTC-8).

| Time | Event |
| --- | --- |
| 2026-11-11 20:50 | The pick on the selection sets names no candidate. `holdout-plan.json` is committed in 6d30d67, with 21 arms. Its SHA-256 is `8659d70c053fb9e90f53216af4e2ef9ac1c22219f5c988cf62db8890cda9a962`. |
| 2026-11-11 21:02 | A first start stops at its own check before it reads a file. Git in WSL cannot read a worktree that Windows made, so the check of the plan failed. The check now compares SHA-256 values. |
| 2026-11-11 21:07 | The read starts: 8 model files at a time, 2 threads per scorer. |
| 2026-11-11 23:02 | A restart of Claude Code and of WSL kills the read. The folder holds 49 of 84 files and does not hold `result.json`. The first run did not write a count that a person saw: its output went to a task that died with it. |
| 2026-11-11 23:33 | The coordinator lists file names and sizes only. Nobody opens a file. |
| 2026-11-11 23:36 | `read_holdout.py` gets `--resume` (commit 5e7204a). `wsl_test_resume.sh` passes on the selection files. |
| 2026-11-11 23:41 | The second part starts as a hidden process apart from the terminal. All 49 files pass the whole-file check: one line per case, the ids of the set in order. The check does not delete a file. |
| 2026-11-11 23:43 | `summarize2.py` gets the paired counts against `ship` (commit 67eb5ff), before a held-out count exists. `wsl_test_summary.sh` passes on the selection files. |
| 2026-11-12 02:00 | The second part ends. It scored 35 files. `result.json` is written, and the tables are made once. |

## Files of each part

- First part, 49 files: all four sets of `control`, `stock-dev`, `linear-features`, `lora-seed1`,
  `full-seed1`, `smollm2-stock`, `ship`, `smollm2-lora-seed1-calibrated`, `smollm2-lora-seed2` and
  `smollm2-lora-seed2-at-ship-setting`. The generated set of `smollm2-lora-seed3`, of the three
  `mix` seeds, of their four `-at-ship-setting` rows and of `smollm2-lora-mix-hinge-seed1`.
- Second part, 35 files: the stream, github and mitton sets of those nine rows, and all four sets
  of `smollm2-full-mix-seed1` and `smollm2-lora-clean-seed1`.

## Effect on the results

- Each file of outputs was scored once. The plan, the settings, the cases and the rule did not change.
- A typed case depends only on the model file, the setting and the case. So a file of the second
  part equals the file that the first run would have written. `wsl_test_resume.sh` shows this on
  the selection files: a file scored after a stop equals the first file byte for byte.
- The first run lost its counts of tokens and model time. So the cost table of the README holds
  only the arms of the second part.
- The outputs stay in `/root/lmft2/holdout` in WSL. The repository holds the tables of the README only.

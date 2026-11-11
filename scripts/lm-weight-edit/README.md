# Weight edits of the English re-ranker

These scripts build weight-edited versions of distilgpt2 and SmolLM2-135M, score them as the
fine-tune scores its checkpoints, and convert the chosen edits the way the phone runs them. The
design is `docs/lm-weight-edit-design.md`.

The scripts read the fine-tune worktree (`build/worktrees/lm-finetune`, branch
`engine/lm-finetune`) and never write to it. They import its `train.py`, read its lists and
models, and run its `evaluate.py` and `check_parity.py` with outputs in this worktree or in
`~/lmedit` under WSL. They use the fine-tune's venv (torch 2.8.0+cu128, transformers 4.57.1).

## Files

| File | Job |
| --- | --- |
| `edits.py` | The edits: task vector scaling, task arithmetic, uniform soup, TIES, DARE, a random direction, and the TFTV rank-one update. |
| `make_arms.py` | Writes the arm files of Tables 2 and 3 of the design. |
| `sweep.py` | Builds each arm and scores it on the stopping split (lists right and listwise loss), or exports one arm as a Hugging Face model. |
| `select_arms.py` | Applies the selection rule: within a family, most lists right, then lower loss. |
| `convert_edit.sh` | f16 conversion with `convert_hf_to_gguf.py` of llama.cpp b4846, Q3_K_M in WSL, then token and score parity with `lm_score`. |
| `quant_loss.py` | Lists right at f16 and at Q3_K_M on the same 500 parity lists. |
| `eval_edit.sh` | `evaluate.py` of the fine-tune in WSL: the tuning split picks the setting, then dev scores the arm. |
| `eval_status.sh` | Progress of the WSL evaluations. |
| `eval_extra.py`, `eval_extra.sh` | For one evaluated arm: the stopping cases at its tuned setting, dev at the common setting of its base, and the calibration-only candidates of a fine-tune. |
| `export_convert.sh` | One conversion stream: export on the processor, `convert_edit.sh`, parity. `--status` prints each arm's state. |
| `round2_queue.sh` | The WSL queue of the interpolation arms, the random-edit seeds and the reference rows. |
| `interp_report.py` | The interpolation tables, the selection rule on the stopping cases and the dev criteria. |
| `paired.py` | Exact McNemar test and grouped bootstrap interval for two arms on dev. |
| `collect.py` | The table of every chosen arm. |
| `copy_results.sh` | Copies results from WSL into `build/lm-weight-edit`. |
| `with_gpu_lock.sh` | Runs a GPU command while it holds `build/gpu.lock` of the main checkout. |

## Commands

From the root of this worktree, in Git Bash, with `PY` set to the fine-tune's venv python:

```bash
PY=../lm-finetune/build/lm-finetune/venv/Scripts/python.exe
$PY scripts/lm-weight-edit/make_arms.py --out build/lm-weight-edit/arms --with-seed2
$PY scripts/lm-weight-edit/sweep.py --base smollm2-135m --arms build/lm-weight-edit/arms/smollm2.json \
    --out build/lm-weight-edit/stop/smollm2.jsonl
python scripts/lm-weight-edit/select_arms.py build/lm-weight-edit/stop/smollm2.jsonl
$PY scripts/lm-weight-edit/sweep.py --base smollm2-135m --arms build/lm-weight-edit/arms/smollm2.json \
    --device cpu --export NAME --export-dir build/lm-weight-edit/models/NAME/hf
bash scripts/lm-weight-edit/convert_edit.sh NAME
python scripts/lm-weight-edit/quant_loss.py build/lm-weight-edit/models/NAME/parity
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit/scripts/lm-weight-edit/eval_edit.sh NAME NAME.Q3_K_M.gguf 2
```

The interpolation arms and the random-edit seeds (`make_arms.py` writes `*-round2.json`):

```bash
bash scripts/lm-weight-edit/with_gpu_lock.sh "stopping-list scores" $PY scripts/lm-weight-edit/sweep.py     --base distilgpt2 --arms build/lm-weight-edit/arms/distilgpt2-round2.json --out build/lm-weight-edit/stop/distilgpt2-round2.jsonl
bash scripts/lm-weight-edit/export_convert.sh smollm2-135m build/lm-weight-edit/arms/smollm2-round2.json s-wise-0.{1..9} s-random-1.0-seed{2..5}
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit/scripts/lm-weight-edit/round2_queue.sh 4 references s-wise s-random
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit/scripts/lm-weight-edit/copy_results.sh
python scripts/lm-weight-edit/interp_report.py s d d2
```

These evaluations have not finished for any arm. `docs/lm-weight-edit-handoff.md` gives the state
and the full resume commands. Run at most 4 jobs of 2 threads on the working desktop.

After a fresh checkout on Windows, run `sed -i 's/
$//' scripts/lm-weight-edit/*.sh` before WSL
reads the shell files.

`sweep.py` caps its GPU memory at 3.5 GB and runs at below-normal priority. An arm takes about
40 s on the stopping split on an RTX 4090. `sweep.py` appends to its output and skips arms it has
already scored.

## Checks

- `sweep.py` on the stock SmolLM2 gives 6,492 lists right and loss 0.61709, as step 0 of the
  fine-tune log. At lam = 1 it gives 7,318 and loss 0.12156, against 7,319 and 0.121557 in
  `train-result.json` of `smollm2-lora-seed1`.
- `edits.tftv_update` gives an update with the Frobenius norm of W, which maps the mean input onto
  a positive multiple of the steering direction, as the paper proves.
- `convert_edit.sh` stops when the tokens differ from `lm_score`, or when f16 scores differ from
  PyTorch by more than 0.05 nats.

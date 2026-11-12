# Round 2 of the re-ranker fine-tune: results on a fresh held-out set

## Summary

Training on clean running text cuts the correct words that the re-ranker changes by about three
quarters, and it keeps the repairs. The pre-set rule still keeps the shipped file `ship`, because
no arm qualified as the candidate on the selection sets.

1. Keep `ship` in the phone experiment if the pre-set rule is binding. The pick named no candidate.
2. Decide whether to replace `ship` outside the rule. On the held-out set `ship` changes 181 of
   26,060 clean words. The six arms with clean running text in training change 22 to 54.
3. If you replace it, take `smollm2-full-mix-seed1` at weight 1.5, margins 0, 8, 2, space-after on.
   It was the nearest miss of the pick, and the held-out set repeats that picture (Table 5).
4. Measure the chosen file on the phone. This round measured Linux only.

This page does not settle the gain on real phone typing, or the phone time of any file.

```mermaid
xychart-beta
    title "Changed words of 26,060 clean held-out words"
    x-axis ["control 332", "ship 181", "seed2 156", "seed3 172", "clean 54", "mix1 51", "mix2 52", "mix3 46", "full-mix 46", "hinge 22"]
    y-axis "changed words" 0 --> 350
    bar [332, 181, 156, 172, 54, 51, 52, 46, 46, 22]
    line [181, 181, 181, 181, 181, 181, 181, 181, 181, 181]
```

Figure 1. Changed words of the clean running text, each arm at its own setting. The line marks
`ship` at 181. The more clean running text the training holds, the fewer correct words change.

```mermaid
xychart-beta
    title "Right real misspellings of 2,221 held-out cases"
    x-axis ["control 1642", "ship 1682", "seed2 1657", "seed3 1666", "clean 1659", "mix1 1699", "mix2 1686", "mix3 1676", "full-mix 1708", "hinge 1683"]
    y-axis "right cases" 1600 --> 1720
    bar [1642, 1682, 1657, 1666, 1659, 1699, 1686, 1676, 1708, 1683]
    line [1682, 1682, 1682, 1682, 1682, 1682, 1682, 1682, 1682, 1682]
```

Figure 2. Right real misspellings (GitHub misspellings and Mitton pairs). The line marks `ship` at
1,682. The axis starts at 1,600. The arms do not differ much here: the range is 1,657 to 1,708.

## Glossary

| Term | Meaning |
| --- | --- |
| reading | One way to read the typed span as words. The text as typed is one reading. |
| setting | The weight, the three margins (from typed, to typed, other) and the space-after switch of the re-ranker. |
| `ship` | `smollm2-lora-seed1.Q4_K_M.gguf` of round 1 at weight 1.0, margins 0, 4, 2, space-after on. |
| clean running text | Whole sentences typed word by word without a slip. |
| changed word | A word of clean running text that the field does not hold as typed. |
| closed and open stream | Clean sentences with only words of the 60,000 most frequent, and sentences with one or two rarer real words. |
| non-word slip | A generated slip case outside `real_word_slip`: letter, space and symbol slips and missing apostrophes. |
| real misspelling | A wrong form that a person wrote: `github_misspelling` cases and Mitton's Birkbeck and Holbrook pairs. |
| selection sets | The dev half, the published dev misspellings, and the select parts of the stream and of the GitHub typos. They picked the candidate. |
| held-out set | Four sets that no model had scored before the one read (Table 2). |

## Arms and their settings

Table 1. Every arm of the held-out read, named by how it is fit. Each SmolLM2 fine-tune is a
Q4_K_M file of 105,453,504 bytes in the typed format. The more new lists a fit reads, the longer it trains.

| Label | Model and fit | Training lists | Setting: weight; margins; space-after | Setting from |
| --- | --- | --- | --- | --- |
| `control` | The engine's own choice | none | none | none |
| `stock-dev` | Shipped distilgpt2 Q3_K_M, not trained, stock format | none | 1.0; 24, 0, 2; on | round 1, dev |
| `linear-features` | Linear listwise chooser on 8 engine features, trained by Adam | round 1 | 1.5; 2, 4, 0; off | round 1, tuning split |
| `lora-seed1` | distilgpt2, LoRA fine-tune, Q3_K_M | round 1 | 1.5; 1, 4, 2; on | round 1, tuning split |
| `full-seed1` | distilgpt2, full fine-tune, Q3_K_M | round 1 | 1.5; 4, 4, 2; on | round 1, tuning split |
| `smollm2-stock` | Shipped SmolLM2-135M Q4_K_M, not trained, stock format | none | 0.75; 16, 0, 2; on | round 1, tuning split |
| `ship` | SmolLM2-135M, LoRA fine-tune (rank 16, AdamW, listwise cross-entropy), seed 1 of round 1 | round 1 | 1.0; 0, 4, 2; on | round 1, tuning split |
| `smollm2-lora-seed1-calibrated` | The file of `ship` | round 1 | 1.0; 0, 4, 2; on | tuning sets, clean-text rule |
| `smollm2-lora-seed2` | The recipe of `ship`, seed 2 | round 1 | 2.0; 1, 8, 2; on | tuning sets, clean-text rule |
| `smollm2-lora-seed3` | The recipe of `ship`, seed 3 | round 1 | 1.5; 0, 8, 2; on | tuning sets, clean-text rule |
| `smollm2-lora-mix-seed1` | SmolLM2-135M, LoRA fine-tune, seed 1 | round 1, clean running text, Wikipedia misspellings | 1.5; 1, 8, 2; on | tuning sets, clean-text rule |
| `smollm2-lora-mix-seed2` | The same fit, seed 2 | the same | 1.5; 0, 4, 2; on | tuning sets, clean-text rule |
| `smollm2-lora-mix-seed3` | The same fit, seed 3 | the same | 1.5; 1, 2, 2; on | tuning sets, clean-text rule |
| `smollm2-lora-mix-hinge-seed1` | The same fit with a keep-typed hinge term (margin 4, weight 1.0) in the loss | the same | 1.5; 0, 8, 2; on | tuning sets, clean-text rule |
| `smollm2-full-mix-seed1` | SmolLM2-135M, full fine-tune (AdamW, listwise cross-entropy) | the same | 1.5; 0, 8, 2; on | tuning sets, clean-text rule |
| `smollm2-lora-clean-seed1` | The LoRA fit without the Wikipedia misspellings | round 1, clean running text | 1.0; 0, 2, 0; on | tuning sets, clean-text rule |
| `...-at-ship-setting` | Five of the files above at the setting of `ship` | | 1.0; 0, 4, 2; on | fixed |

The clean-text rule chose the setting of `ship` for the file of `ship`. So `ship` and
`smollm2-lora-seed1-calibrated` are one arm with two names. `docs/lm-finetune2-design.md` gives the
design, and `docs/lm-finetune2-design-review.md` the Codex review of it.

## Four parts of the held-out set

Table 2. The held-out set. `check_leakage2.py` passes on these files. The one read used the plan
`holdout-plan.json` of commit 6d30d67 (SHA-256 `8659d70c...a962`).

| Part | Cases | Source |
| --- | --- | --- |
| generated | 6,745 cases in the 24 categories of dev | Fresh Tatoeba sentences, the project's slip generator |
| stream | 3,000 closed sentences (19,482 words) and 1,000 open sentences (6,578 words) | Fresh Tatoeba sentences |
| github | 1,500 `github_misspelling` and 1,000 `github_real_word` | GitHub Typo Corpus v1.0.0, a corpus that round 1 did not use |
| mitton | 600 Birkbeck and 121 Holbrook pairs | Roger Mitton's lists, pairs outside every round 1 case |

The read ran in two parts, because a restart of the machine stopped the first run. Each file of
outputs was scored once. `docs/lm-finetune2-results-log.md` holds the record.

## Held-out counts of every arm

Table 3. Changed words of the clean running text, and right cases per group, for all 21 arms.
The arms with clean running text in training change 22 to 54 clean words, against 156 to 181 for
the round 1 recipe at its tuned settings.

{{A}}

`github real word` holds edits that often fix grammar, such as "notes" to "note". No rule uses it.

Table 4. Real misspellings per source, non-word slips, all generated cases, and changed stream
sentences. The non-word slips of every SmolLM2 fine-tune lie between 4,845 and 4,877 of 5,044.

{{B}}

## Six conditions of the replacement rule on the held-out set

The pick on the selection sets named no candidate, so the rule keeps `ship` and the six conditions
decide nothing. Table 5 shows them for every arm, for reading.

Table 5. The six conditions of every arm against `ship`. Condition 1: fewer changed stream
sentences at p < 0.05. Condition 2: changed words of each stream at most those of `ship`.
Condition 3: clean and clean symbols each at least those of `ship`. Condition 4: non-word slips at
least those of `ship` less 25, with an interval floor of -50. Condition 5: real misspellings pooled
at least those of `ship`, each source within 1 percent. Condition 6: half of the real-word gain of
`ship`. Two arms hold all six: `smollm2-lora-mix-seed1` and `smollm2-lora-mix-hinge-seed1`.

{{G}}

- Every arm with clean running text in training holds conditions 1, 2, 4 and 6.
- `smollm2-full-mix-seed1` misses condition 3 by one case: 424 clean symbols against 425.
- The misses of conditions 3 and 5 are small counts. Table 6 shows that most lie inside the noise
  of a paired comparison.

Table 6. Cases that only the arm gets right, and cases that only `ship` gets right, per group.
The p value is the two-sided exact McNemar test. The generated groups repeat some contexts, so
their p values read a little too small.

{{H}}

## `smollm2-full-mix-seed1` against `ship` on the held-out set

Table 7. The full fine-tune against the shipped file. It changes about a quarter of the clean
words that `ship` changes, and it does not lose a group of repairs.

| Count | `ship` | `smollm2-full-mix-seed1` | Paired comparison |
| --- | --- | --- | --- |
| Changed words, closed stream of 19,482 | 120 | 23 | |
| Changed words, open stream of 6,578 | 61 | 23 | |
| Changed stream sentences of 4,000 | 155 | 34 | 125 only `ship`, 4 only the arm, one-sided p = 1.7e-32 |
| Clean cases of 972 | 942 | 944 | clean and clean symbols together: 10 only the arm, 9 only `ship`, p = 1 |
| Clean symbol cases of 429 | 425 | 424 | |
| Non-word slips of 5,044 | 4,864 | 4,877 | +13, 95 percent interval -3 to +29 |
| Real-word slips of 300 | 246 | 252 | 15 only the arm, 9 only `ship`, p = 0.31 |
| Real misspellings of 2,221 | 1,682 | 1,708 | 69 only the arm, 43 only `ship`, p = 0.018 |
| GitHub misspellings of 1,500 | 1,313 | 1,325 | 43 only the arm, 31 only `ship`, p = 0.20 |
| Mitton pairs of 721 | 369 | 383 | 26 only the arm, 12 only `ship`, p = 0.034 |

The interval of the non-word slips resamples groups of one context and one intended text.

## Pick on the selection sets

Table 8. Selection sets: changed words and right cases per arm, each at its tuned setting.

{{PICK1}}

Table 9. The five conditions of the pick. Each arm misses condition 2 or condition 3 by 2 to 21
cases, so the pick named no candidate. `smollm2-full-mix-seed1` misses only condition 2, by 2 clean cases.

{{PICK2}}

## Spread of the seeds and effect of the setting

- Round 1 recipe, three seeds at the setting of `ship`: 181, 211 and 166 changed held-out words.
- Fit with the new lists, three seeds at the setting of `ship`: 60, 65 and 96 changed held-out words.
- So the drop is larger than the spread of the seeds at one fixed setting.
- At the setting of `ship`, the three `mix` seeds keep 1,714, 1,707 and 1,722 real misspellings,
  against 1,682 for `ship`. Their tuned settings have weight 1.5 and keep 1,676 to 1,699.
- `smollm2-lora-clean-seed1` keeps 1,659 real misspellings. The `mix` seeds keep 1,676 to 1,699 at
  their tuned settings. So the Wikipedia misspellings add a little there, with one seed of the clean-only fit.
- The hinge arm changes the fewest clean words (22). On the selection sets it kept 21 fewer real
  misspellings than `ship`, and on the held-out set 1 more.

## Seen and new phrases and pairs

Table 10. Right held-out cases by whether training holds the phrase or the pair. The gain of the
fine-tunes over the control shows on new phrases and new pairs too.

{{D}}

## Weighted estimate

Table 11. Wrong words per 1,000 typed, for a slip share s and a real-word share r that nobody
measured. No rule uses the estimate. A slip case counts as one wrong word.

{{C}}

## File size and cost per request

Every SmolLM2 fine-tune is 105,453,504 bytes as Q4_K_M. The distilgpt2 files are 75,417,280 bytes as Q3_K_M.

Table 12. Cost on the held-out stream for the arms of the second part of the read, in WSL with 2
threads per scorer, while 7 scorers and another worker ran. The typed format reads 28.3 tokens per request.

{{E}}

- On the select stream with 2 scorers running, the file of `ship` took 83 ms per request for 28.1
  tokens per request. So the 229 to 235 ms of Table 12 show the load of the machine.
- The scorer needs about 140 MiB of resident memory in Linux for every SmolLM2 file.
- The files of one base model have the same size, format and token count. Their phone time is the
  time of `ship`, which this round did not measure.

## File formats on the selection sets

Table 13. `ship` and `smollm2-lora-mix-seed1` in five formats, each at its own tuned setting.
The time is the model time of 500 requests against plain Q4_K_M on the PC. The format moves the
counts less than the setting does, and the importance matrix does not improve on plain Q4_K_M.

| File | Format | Bytes | Setting | Dev right /6,799 | Changed select words /8,439 | Published dev /751 | GitHub misspelling /1,500 | Time against Q4_K_M |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ship` | f16 | 270,885,312 | 1.5; 1, 4, 2; on | 6,539 | 46 | 390 | 1,232 | 1.10 |
| `ship` | Q8_0 | 144,810,432 | 1.5; 1, 4, 2; on | 6,541 | 46 | 387 | 1,226 | 0.87 |
| `ship` | Q5_K_M | 112,102,848 | 1.5; 0, 4, 2; on | 6,533 | 52 | 390 | 1,233 | 1.22 |
| `ship` | Q4_K_M | 105,453,504 | 1.0; 0, 4, 2; on | 6,543 | 68 | 403 | 1,279 | 1.00 |
| `ship` | Q4_K_M with importance matrix | 105,453,760 | 1.5; 0, 4, 2; on | 6,535 | 50 | 387 | 1,233 | 1.00 |
| `mix-seed1` | f16 | 270,885,312 | 1.0; 0, 4, 2; on | 6,558 | 27 | 410 | 1,294 | 1.07 |
| `mix-seed1` | Q8_0 | 144,810,432 | 1.0; 1, 4, 2; on | 6,558 | 24 | 407 | 1,296 | 0.85 |
| `mix-seed1` | Q5_K_M | 112,102,848 | 1.0; 0, 2, 2; on | 6,562 | 20 | 400 | 1,281 | 1.21 |
| `mix-seed1` | Q4_K_M | 105,453,504 | 1.5; 1, 8, 2; on | 6,548 | 19 | 400 | 1,277 | 1.00 |
| `mix-seed1` | Q4_K_M with importance matrix | 105,453,760 | 1.5; 2, 8, 2; on | 6,541 | 19 | 404 | 1,280 | 1.01 |

The importance matrix comes from 3,000 training lists of round 2 (`imatrix_text.py`).

## Training runs

Table 14. Each training run on the RTX 4090. A step adds the gradients of micro-batches of at most
800 padded tokens. The fits with the new lists stop later than the round 1 recipe.

| Run | Trained weights | Training lists | Stopping lists | Steps | Checkpoint step | Stopping loss at the checkpoint | Training time | Peak reserved MiB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `smollm2-lora-seed2` | 4,884,480 | 118,169 | 7,556 | 6,000 | 3,500 | 0.1232 | 155 min | 2,354 |
| `smollm2-lora-seed3` | 4,884,480 | 118,169 | 7,556 | 9,000 | 6,500 | 0.1179 | 221 min | 2,350 |
| `smollm2-lora-mix-seed1` | 4,884,480 | 175,831 | 11,076 | 13,500 | 11,000 | 0.1145 | 364 min | 2,354 |
| `smollm2-lora-mix-seed2` | 4,884,480 | 175,831 | 11,076 | 8,500 | 6,000 | 0.1200 | 203 min | 2,354 |
| `smollm2-lora-mix-seed3` | 4,884,480 | 175,831 | 11,076 | 7,500 | 5,000 | 0.1199 | 123 min | 2,354 |
| `smollm2-lora-mix-hinge-seed1` | 4,884,480 | 175,831 | 11,076 | 13,000 | 10,500 | 0.1481 (cross-entropy 0.1298) | 287 min | 2,354 |
| `smollm2-full-mix-seed1` | 134,515,008 | 175,831 | 11,076 | 8,000 | 5,500 | 0.1159 | 109 min | 3,478 |
| `smollm2-lora-clean-seed1` | 4,884,480 | 172,928 | 10,883 | 12,500 | 10,000 | 0.1143 | 301 min | 2,354 |

- Two runs shared the GPU for most of the time, so the training times are not comparable.
- `smollm2-lora-seed3` stopped at its saved state of step 1,500 and went on from it.
- The stopping losses of runs with different stopping lists are not comparable.

## Checks of the path the phone runs

Table 15. Tokens and scores of the training code against `lm_score`. The tokens match for every
arm. Four arms miss the score limit of 0.05 nats on the f16 file, by a few readings each.

| Arm | Token mismatches on 2,000 lists | Largest score difference, nats | Mean difference | Under the limit of 0.05 |
| --- | --- | --- | --- | --- |
| `smollm2-lora-seed2` | 0 | 0.036 | 0.0042 | yes |
| `smollm2-lora-seed3` | 0 | 0.049 | 0.0045 | yes |
| `smollm2-lora-mix-seed1` | 0 | 0.058 | 0.0059 | no |
| `smollm2-lora-mix-seed2` | 0 | 0.131 | 0.0050 | no |
| `smollm2-lora-mix-seed3` | 0 | 0.023 | 0.0038 | yes |
| `smollm2-lora-mix-hinge-seed1` | 0 | 0.119 | 0.0054 | no |
| `smollm2-full-mix-seed1` | 0 | 0.050 (0.0503) | 0.0058 | no |
| `smollm2-lora-clean-seed1` | 0 | 0.046 | 0.0055 | yes |

- The large differences sit on a few contexts, such as "Nevertheless many are choosing | earl6 |".
- Weights rounded to 16 bits move a score by at most 0.03 nats (`parity_f16.py`). A 32-bit cache
  and flash attention off move the same few readings up or down (`wsl_kv_test.sh`).
- The tests did not find one cause. Tokens, the 96-token cut and the start token agree.
- At the setting of `ship`, 0 to 4 of 2,000 tuning decisions lie within 0.05 nats of a flip (`parity_gaps.py`).
- Every reported count comes from the Q4_K_M file through `lm_score`. Q4_K_M differs from f16 by
  0.46 to 0.61 nats on average.

## Commands

    python3 scripts/lm-finetune2/build_real_typo_cases.py --corpora build/lm-finetune2/corpora \
        --round1-external ROUND1/build/typing-evaluation/external --out build/lm-finetune2/data
    python3 scripts/lm-finetune2/build_cases2.py --round1 ROUND1 --out build/lm-finetune2/data
    python3 scripts/lm-finetune2/build_lists2.py --shim SHIM --data build/lm-finetune2/data --workers 7
    python3 scripts/lm-finetune2/check_leakage2.py --round1 ROUND1 --data build/lm-finetune2/data --self-test
    uv run --project scripts/lm-finetune python scripts/lm-finetune2/run_slots.py \
        --queue scripts/lm-finetune2/train-queue.json --lock D:/Github/iphone-duo-keyboard/build/gpu.lock
    bash scripts/lm-finetune2/post_arm.sh NAME          # convert, check, tune and score one arm
    bash scripts/lm-finetune2/wsl_pick.sh               # the pick on the selection sets
    bash scripts/lm-finetune2/wsl_plan.sh               # holdout-plan.json
    bash scripts/lm-finetune2/wsl_read_holdout.sh SHA256_OF_THE_PLAN [resume]
    python3 scripts/lm-finetune2/write_readme.py --summary ~/lmft2/holdout/summary/holdout-summary.md

The held-out read gives one number per arm, once. To score another model on it, write a plan with
that model's file and setting first, and give `read_holdout.py` a new output folder.

## Limits of this measurement

- The generator made the generated cases. The real misspellings come from desktop text. The sets do
  not hold phone slips.
- The clean running text is Tatoeba sentences of 4 to 12 words in lower case, without punctuation.
- The pick named no candidate, so the choice in the Summary is a judgement after the read.
- `smollm2-full-mix-seed1` and `smollm2-lora-clean-seed1` have one seed each.
- A `mix` fit also stops on more lists and trains longer than the round 1 recipe.
- Four arms miss the score limit of the f16 check, and the cause is not found.

These points were not verified:

- The phone time and memory of any file of round 2.
- The cost per request of the round 1 arms on the held-out stream: the restart lost those counts.
- The link between the few contexts with a large score difference and the new training lists.

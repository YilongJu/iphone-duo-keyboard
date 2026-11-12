# Agreement of the keyboard's re-ranking code with the harness

## Summary

The keyboard re-ranks with the SmolLM2-135M LoRA fine-tune in the typed format, with the
apostrophe step in the stock prompt at lead 4 and the work area "AI and software" on. On the
macOS runner its own code and the harness of `scripts/lm-rerank` agree in every case: the same
output in all 12,787 dev cases and the same choice in all 13,404 corrections. The keyboard's
scorer and `lm_score` differ in 1 of 12,886 requests on that runner, by 0.285 in one candidate,
and that step of the keyboard job is red in run 43142371994. llama.cpp gives other model numbers
on other machines, so the totals differ by a few cases between machines.

1. Install a TestFlight build of `engine/lm-keyboard` on the iPhone Duo and type a few sentences
   in Notes. Then type `duo:lm` and a space. The `reranker` lines give the time per space press
   and the footprint on the phone.
2. Expect the phone to differ from the simulator by a few cases. The device part of the app's
   llama.cpp framework holds other instructions than its simulator part (Table 7).
3. Tune a later model with the harness on the macOS runner, as the keyboard job of
   `.github/workflows/lm-keyboard.yml` runs it. Its numbers equal the keyboard's in the simulator.

This page does not settle the phone's time and memory, which need step 1, or the phone's numbers.
It does not read the test half.

## Glossary of the agreement check

| Term | Meaning |
| --- | --- |
| harness | `harness_trace.py`: `rerank.py`, its engine shim and `lm_score.c` of `engine/lm-finetune`, with the shipped setting and the typed format. |
| x86 harness | The harness on an ubuntu-24.04 runner, built from llama.cpp b4846 source. |
| ARM harness | The harness on an ubuntu-24.04-arm runner (Neoverse-N2), built the same way. |
| macOS harness | The harness in the keyboard job, on the macOS runner of the simulator, with `lm_score` linked against the macOS part of the app's framework. |
| keyboard | `Tests/TypingEvaluationTests.swift`: the keyboard's controller, engine, scorer and rule in the iOS simulator. |
| typed format | The model reads the text before the span, the typed span between bars, then each reading: "How much \| sutar \|", then " sugar". `LanguageModelPrompt.make` builds it. |
| shipped setting | Weight 1.0, margins 0, 4 and 2, the space-after term, and the apostrophe step (first word of a two-word span, model score less slip cost, stock prompt) at lead 4. The work area "AI and software" is on: its supplement, its preferred capitals and the protection of a typed new word (`docs/domain-pack-design.md`). |
| dev cases | The 6,799 cases of `english.dev.jsonl` and `english-symbols.dev.jsonl`, and the 5,988 cases of `english-domain.dev.jsonl`, the cases of the work area. |
| correction | One space press whose typed span has more than one engine reading, so the model scores the readings. |

## Dev scores of the keyboard and the three harnesses

Table 1. Right dev cases per group, from run 43142371994 at commit 6eef96e. The first six
columns count the 6,799 cases of `english.dev.jsonl` and `english-symbols.dev.jsonl`.

| Run | clean | letter slips | space slips | symbol slips | clean symbols | all 6,799 | work area, of 5,988 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| each harness and the keyboard, engine only | 960/973 | 1943/2100 | 1299/1500 | 1131/1197 | 427/429 | 6077 | 5313 |
| x86 harness, with the model | 953/973 | 2057/2100 | 1387/1500 | 1165/1197 | 429/429 | 6543 | 5325 |
| ARM harness, with the model | 953/973 | 2055/2100 | 1388/1500 | 1166/1197 | 428/429 | 6541 | 5329 |
| macOS harness, with the model | 953/973 | 2055/2100 | 1386/1500 | 1165/1197 | 427/429 | 6537 | 5326 |
| keyboard, with the model | 953/973 | 2055/2100 | 1386/1500 | 1165/1197 | 427/429 | 6537 | 5326 |

The work area adds 3 engine cases in the group clean. Without it the x86 harness gave 6,074
with the engine alone and 6,542 with the model, in run 43010544544. `compare.py` pins the x86
numbers of this table.

## Exact agreement on one machine

Table 2. Checks of the keyboard against the macOS harness, both in the same job on the same
virtual machine.

| Check | Result |
| --- | --- |
| Outputs, with the model and engine only | the same in 12,787 of 12,787. A case of the work area that is about capitals is compared with its capitals, and every other case after the scorer's normalization. |
| Corrections on each side | 13,404 and 13,404, matched by case and place |
| Context the model reads, in the typed format | the same in 13,404 |
| Readings and their marks, in order | the same in 13,404 |
| Choice | the same in 13,404 |
| Choice of `rerank.choose` on each side's own numbers, apostrophe step included | equal to the recorded choice in 13,404 on both sides |
| Model numbers | median 0.000003 apart, 99th percentile 0.000005, and 0.285 in one reading (Table 3) |

In 46 cases, with the model and engine only, the keyboard's output differs in letter case only.
All 46 are symbol cases whose first letter was typed as a symbol key at the start of the field,
as "Please" against "please". The harness gives that letter the capital of a sentence start.
The field of the keyboard test does not capitalize sentences for these cases.

Table 3. The keyboard's C scorer against `lm_score` on the 12,886 requests of each harness, in
run 43142371994. `scorer_cli` runs `LanguageModel/duo_lm_scorer.c` with 2 threads and calls of
at most 31 tokens. `lm_score` runs one call per batch. Both read start token 2.

| Machine | `lm_score` threads | Answers |
| --- | --- | --- |
| x86 runner | 4 | the same bytes, 5 decimals each |
| macOS runner, with the app's framework | 2 | 1 of 12,886 differs: one candidate of one request by 0.285 |
| ARM runner | 4 | 168 of 12,886 differ, the widest by 0.932 |

The split of a batch into calls of 31 tokens moves some answers on the two ARM machines. On
the macOS runner the one request is a case of the work area: 23 words before the typed "ggnns",
and the candidate "egg nns". The choice of that correction is the same on both sides. The 7,719
requests of the cases without the work area gave the same bytes on the macOS runner in run
43010544544. The step that compares the two scorers on the macOS runner stops on any
difference, so the keyboard job of run 43142371994 is red at that step. The cause in the scorer
was not found.

## Model numbers on three kinds of machine

Table 4. Differences of the model's log probability over the readings of the matched
corrections, in natural-log units, from run 42973707094 before the merge of the apostrophe words.

| Pair | median | widest | choices that differ | cases that differ |
| --- | --- | --- | --- | --- |
| macOS harness and keyboard, one machine | 0.000003 | 0.000005 | 0 | 0 |
| x86 harness and keyboard | 0.140 | 1.681 | 13 | 6 |
| ARM harness and keyboard | 0.119 | 1.860 | 13 | 5 |

Each machine repeats its own numbers. The two kinds of x86 runner, with and without AVX-512, give
each other other numbers as well.

## Apostrophe step with SmolLM2

The step compares the choice with its twins, as "we're going" for the typed "were going". It reads
the stock prompt, the text before the span without the typed span. With the typed format the
fine-tune reads the typed words between bars and prefers the typed real word, so the step then
repairs few ambiguous pairs.

`scripts/lm-rerank/apostrophe_words.py --steps prompts` ran the dev half of the apostrophe words
in run 43005655129, for three prompts of the step, each with the scores model and model less slip
cost over 8 leads. The design's rule keeps every existing dev category and every new control at
its count without the step, and then takes the most right new cases with the next word typed.
`apostrophe_prompts_table.py` writes these tables from the run's result.

Table 5. The setting each prompt takes under the rule.

| Prompt of the step | settings the rule allows | chosen | new cases right, next word typed, of 1,623 |
| --- | --- | --- | --- |
| margin scores, typed span "\| were going \|" | 4 of 16 | slip cost, lead 8 | 1,335 |
| stock prompt, no typed span | 6 of 16 | slip cost, lead 4 | 1,432 |
| typed span showing the reading scored | 0 of 16 | none | none |

With the step off the keyboard gets 684. Each reading in its own typed span turns some
"its stays its" controls wrong at every lead.

Table 6. Right dev cases per pair with the next word typed, at each prompt's chosen setting.
Dropped: the person meant the contraction. Control: the person meant the word without it.

| Pair | distilgpt2, margin scores, lead 1 | SmolLM2, margin scores, lead 8 | SmolLM2, stock prompt, lead 4 | SmolLM2, stock prompt, control |
| --- | --- | --- | --- | --- |
| its/it's | 12/40 | 1/40 | 17/40 | 40/40 |
| were/we're | 38/40 | 0/40 | 16/40 | 40/40 |
| well/we'll | 33/40 | 1/40 | 13/40 | 40/40 |
| ill/i'll | 39/40 | 29/40 | 30/40 | 40/40 |
| hell/he'll | 40/40 | 7/40 | 22/40 | 40/40 |
| id/i'd | 24/24 | 18/24 | 22/24 | 20/24 |
| lets/let's | 31/32 | 23/32 | 23/32 | 25/32 |
| shed/she'd | 30/32 | 25/32 | 29/32 | 31/32 |

The stock prompt at leads under 4 repairs more pairs, as were 33/40 and its 38/40 at lead 0.5, and
it then turns 3 "its stays its" controls wrong, which the rule refuses. A second run on another
runner (43009847437) picks the stock prompt at lead 4 as well, with 1,432 new cases. The keyboard
in the simulator gets 1,427 of the new cases with the next word typed. The step's second request
is part of the trace, and `compare.py` replays it with the case-by-case check of Table 2.

## Instructions in the parts of the app's framework

Table 7. Counts of instruction words in each arm64 part of `llama.framework`, by their encoding.

| Instruction | device | simulator | macOS |
| --- | --- | --- | --- |
| `smmla` (i8mm) | 0 | 0 | 0 |
| `sdot`, vector | 1 | 338 | 338 |
| `fmla`, half-precision vector | 2 | 458 | 458 |

The simulator and macOS parts match, which the exact agreement of Table 2 needs. The device part
was built without the dot-product and half-precision instructions, so the phone computes with
other kernels than the simulator.

## Time and memory of the model in the simulator

Table 8. The `reranker` lines of the simulator after the English dev cases, run 43142371994, with
the work area on. The simulator shares 3 cores of the macOS runner, so these numbers do not
stand for the phone.

| Measure | Value |
| --- | --- |
| Load of the model | 80 ms |
| Footprint before the load, after it, after the first correction | 143.1 MB, 157.6 MB, 162.7 MB |
| Time added per space press, mean, median, 95th percentile | 107.2 ms, 84.1 ms, 147.5 ms |

Without the work area the three footprints were 142.8 MB, 157.3 MB and 162.5 MB in run
43010544544, so the work area adds about 0.3 MB in the simulator. After the cases of the work
area, whose text before the word is longer, the time added per space press is 140.2 ms in the
mean, 103.7 ms in the median and 204.5 ms at the 95th percentile.

In the language model test of the simulator, 8 candidates after a 20-token context take 73.6 ms
with SmolLM2 and 37.5 ms with distilgpt2. The phone measured 23.4 ms for distilgpt2. The `duo:lm`
test frees the keyboard's model before it loads its own copy, and the keyboard loads its model
again after, so the keyboard never holds two copies.

## Method of the agreement check

1. `harness_trace.py` types the dev cases through `rerank.py` with the shipped setting and writes
   each correction: the text before, the context, the readings with their slip costs, the model's
   numbers and the choice.
2. The workflow scores every distinct request of that run again with `lm_score` and `scorer_cli`.
3. The simulator runs every unit test. `TypingEvaluationTests` types the dev cases with the model
   and with the engine alone, and writes the same trace.
4. The same job then builds the engine shim, `lm_score` and `scorer_cli` against the macOS part of
   the app's framework, and runs steps 1 and 2 on the same machine.
5. `compare.py` compares two runs case by case and correction by correction. It recomputes each
   recorded choice with `rerank.choose`, the apostrophe step included.
6. The compare job passes or fails on the keyboard against the macOS harness. The x86 and ARM
   harnesses are reports, and the x86 harness is held against the pinned numbers of `compare.py`.

## Files of this folder

| File | Content |
| --- | --- |
| `harness_trace.py` | The harness with the shipped setting, with a trace of every correction |
| `scorer_cli.c` | The keyboard's scorer behind the request format of `lm_score.c` |
| `compare.py` | The comparison of two runs, and the pinned numbers of the x86 harness |

## Limits of this check

- The phone's part of the framework computes with other instructions than the simulator's.
- The scorer check compares 5-decimal answers, the precision of `lm_score`.
- The cases of `english.dev.jsonl` and `english-symbols.dev.jsonl` hold lower-case text only. A bar in the text before a word gives no prompt, and the
  keyboard then keeps the engine's choice.

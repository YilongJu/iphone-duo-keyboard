# Agreement of the keyboard's re-ranking code with the harness

## Summary

The keyboard re-ranks with the shipped file, the SmolLM2-135M LoRA fine-tune `dom-s100-seed1`
in the typed format, at the shipped setting. On the macOS runner its own code and the harness of
`scripts/lm-rerank` agree in every case: the same output in all 13,936 dev cases and the same
choice in all 14,626 corrections. The keyboard's scorer and `lm_score` give the same answers in
all 13,928 requests on that runner. llama.cpp gives other model numbers on other machines, so
the totals differ by a few cases between machines.

1. Install a TestFlight build of `engine/domain-model` on the iPhone Duo and type a few sentences
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
| local x86 harness | The harness on an Intel i9-13900K in WSL, built the same way: the job `scripts/lm-domain/jobs/shipped-harness.sh`. |
| macOS harness | The harness in the keyboard job, on the macOS runner of the simulator, with `lm_score` linked against the macOS part of the app's framework. |
| keyboard | `Tests/TypingEvaluationTests.swift`: the keyboard's controller, engine, scorer and rule in the iOS simulator. |
| typed format | The model reads the text before the span, the typed span between bars, then each reading: "How much \| sutar \|", then " sugar". `LanguageModelPrompt.make` builds it. |
| shipped file | `smollm2-lora-domain-s100-seed1.Q4_K_M.gguf` of the pre-release `lm-domain-candidate-1`: the SmolLM2-135M LoRA fine-tune `dom-s100-seed1` of `docs/lm-domain-design.md`. |
| shipped setting | The setting of `scripts/lm-domain/candidate.json`: weight 1.5, margins 1 from typed, 4 to typed and 2 other, the space-after term, and the apostrophe step (first word of a two-word span, model score less slip cost, stock prompt) at lead 0.5. The work area "AI and software" is on: its supplement, its preferred capitals and the protection of a typed new word (`docs/domain-pack-design.md`). |
| dev cases | The 6,799 cases of `english.dev.jsonl` and `english-symbols.dev.jsonl`, and the 7,137 cases of `english-domain.dev.jsonl`, the cases of the work area. |
| correction | One space press whose typed span has more than one engine reading, so the model scores the readings. |

## Dev scores of the keyboard and the three harnesses

Table 1. Right dev cases per group, from run 43481402003 at commit 6576495. The first six
columns count the 6,799 cases of `english.dev.jsonl` and `english-symbols.dev.jsonl`.

| Run | clean | letter slips | space slips | symbol slips | clean symbols | all 6,799 | work area, of 7,137 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| each harness and the keyboard, engine only | 961/973 | 1943/2100 | 1299/1500 | 1132/1197 | 427/429 | 6079 | 6357 |
| x86 harness, with the model | 957/973 | 2053/2100 | 1388/1500 | 1164/1197 | 429/429 | 6539 | 6621 |
| local x86 harness, with the model | 957/973 | 2052/2100 | 1387/1500 | 1164/1197 | 429/429 | 6538 | 6619 |
| ARM harness, with the model | 957/973 | 2052/2100 | 1386/1500 | 1164/1197 | 429/429 | 6536 | 6621 |
| macOS harness, with the model | 957/973 | 2055/2100 | 1386/1500 | 1164/1197 | 429/429 | 6539 | 6616 |
| keyboard, with the model | 957/973 | 2055/2100 | 1386/1500 | 1164/1197 | 429/429 | 6539 | 6616 |

In the keyboard the model adds 460 right cases to the engine's 6,079, and 259 right cases of the
work area to the engine's 6,357.

The x86 harness of the run is an AMD EPYC 9V74 with AVX-512, on an ubuntu-24.04 runner.
`compare.py` pins the numbers of this x86 harness. The local x86 harness is the job
`scripts/lm-domain/jobs/shipped-harness.sh` on an Intel i9-13900K without AVX-512, at the same
commit. The comparison with the pinned numbers is a report. It reads "different" on a processor
that computes other last digits, as the Intel i9-13900K does.

The file `smollm2-lora-typed-seed1.Q4_K_M.gguf` at weight 1.0, margins 0, 4 and 2 and lead 4 is
the reference of `docs/lm-domain-results.md`. On these cases the keyboard got 6,537 of 6,799 and
6,350 of 7,137 with that file, in run 43312412590.

## Exact agreement on one machine

Table 2. Checks of the keyboard against the macOS harness, both in the same job on the same
virtual machine.

| Check | Result |
| --- | --- |
| Outputs, with the model and engine only | the same in 13,936 of 13,936. A case of the work area that is about capitals is compared with its capitals, and every other case after the scorer's normalization. |
| Corrections on each side | 14,626 and 14,626, matched by case and place |
| Context the model reads, in the typed format | the same in 14,626 |
| Readings and their marks, in order | the same in 14,626 |
| Choice | the same in 14,626 |
| Choice of `rerank.choose` on each side's own numbers, apostrophe step included | equal to the recorded choice in 14,626 on both sides |
| Model numbers | median 0.000002 apart, 99th percentile 0.000005, widest 0.000005 |

The keyboard's output differs in letter case only in 46 cases with the model and in 45 cases
with the engine alone. They are symbol cases whose first letter was typed as a symbol key at the
start of the field, as "Please" against "please". The harness gives that letter the capital of a
sentence start. The field of the keyboard test does not capitalize sentences for these cases.

Table 3. The keyboard's C scorer against `lm_score` on the requests of each harness, in run
43481402003. `scorer_cli` runs `LanguageModel/duo_lm_scorer.c` with 2 threads and calls of at
most 31 tokens. `lm_score` runs one call per batch. Both read start token 2.

| Machine | `lm_score` threads | Requests | Answers |
| --- | --- | --- | --- |
| x86 runner | 4 | 13,928 | the same bytes, 5 decimals each |
| macOS runner, with the app's framework | 2 | 13,928 | the same bytes, 5 decimals each |
| ARM runner | 4 | 13,928 | 210 of 13,928 differ, the widest by 1.139 |

The local x86 harness gives the same bytes in its 13,928 requests as well.

The scorer gives the calls of a context sizes that differ by one token at most (`call_size`).
The same rule holds for the calls of the candidates. llama.cpp b4846 computes a call of one
token with another routine than a call of two or more tokens. On the macOS runner the two
routines differ in the last bits of their sums. A context whose last call holds one token gave
a candidate a number 0.47 away from the number of one call, in the sweep of run 43477574581.
A context of 32 tokens read as two calls of 16 tokens gives the number of `lm_score`.

`scripts/lm-keyboard/scorer-probe` holds a request with a context of 32 tokens as a check, and
the workflow `scorer-probe.yml` stops when the two scorers differ. Run 43477574581 passed with
the shipped file. Its sweep compares calls of 31 tokens with calls of 256 tokens on the 12,886
requests of run 43142371994, in full precision. The two give the same numbers in every request.
The step that compares the two scorers on the macOS runner stops on any difference.

On the ARM runner the two scorers differ in 210 requests. The cause on that machine was not
studied. The ARM harness is a report, and the phone was not measured.

## Model numbers on three kinds of machine

Table 4. Differences of the model's log probability over the readings of the matched
corrections, in natural-log units, from run 43481402003.

| Pair | median | widest | choices that differ | cases that differ |
| --- | --- | --- | --- | --- |
| macOS harness and keyboard, one machine | 0.000002 | 0.000005 | 0 | 0 |
| x86 harness and keyboard | 0.129 | 1.754 | 41 | 22 |
| ARM harness and keyboard | 0.111 | 1.775 | 40 | 20 |

Each machine repeats its own numbers. The two kinds of x86 processor, with and without AVX-512,
give each other other numbers as well: 41 choices and 21 cases differ between the x86 harness and the local x86
harness.

## Apostrophe step with the shipped file

The step compares the choice with its twins, as "we're going" for the typed "were going". It reads
the stock prompt, the text before the span without the typed span. With the typed format the
fine-tune reads the typed words between bars and prefers the typed real word, so the step then
repairs few ambiguous pairs.

`scripts/lm-domain/tune_apostrophe.py` picked lead 0.5 for the shipped file at the shipped
setting, on the dev half of the apostrophe words. A lead of the grid 0.5 to 8 is allowed when
every category of the generated dev half and the two clean controls of the apostrophe words keep
the count without the step. The allowed lead with the most right cases with the next word typed
wins. `docs/lm-domain-design.md` gives the rule, and `docs/lm-domain-results.md` the counts of
the harness.

Table 5. Right dev cases of the apostrophe words in the keyboard of the simulator, of 1,623, in
run 43481402003. Dropped: the person meant the contraction. Added: the person meant the word
without the apostrophe. Clean: the person typed the intended form.

| Category | engine only, word alone | engine only, next word typed | with the model, word alone | with the model, next word typed |
| --- | --- | --- | --- | --- |
| apostrophe dropped, of 843 | 497 | 240 | 734 | 796 |
| apostrophe dropped, ambiguous word, of 318 | 0 | 0 | 146 | 220 |
| apostrophe added, of 72 | 0 | 11 | 6 | 53 |
| clean ambiguous word, of 318 | 313 | 306 | 290 | 317 |
| clean ambiguous contraction, of 72 | 72 | 71 | 72 | 72 |
| all, of 1,623 | 882 | 628 | 1,248 | 1,458 |

With the next word typed the model raises the right cases from 628 to 1,458 of 1,623, and it
keeps 317 of 318 clean ambiguous words.

Table 6. Right dev cases per ambiguous pair with the next word typed, with the model, in the
same run.

| Pair | apostrophe dropped | clean word |
| --- | --- | --- |
| its/it's | 13/40 | 40/40 |
| were/we're | 38/40 | 40/40 |
| well/we'll | 13/40 | 40/40 |
| ill/i'll | 14/40 | 40/40 |
| hell/he'll | 39/40 | 40/40 |
| shell/she'll | 19/19 | 19/19 |
| wed/we'd | 4/5 | 5/5 |
| id/i'd | 13/24 | 24/24 |
| lets/let's | 30/32 | 31/32 |
| shed/she'd | 32/32 | 32/32 |
| whore/who're | 5/6 | 6/6 |

The step repairs 38 and 39 of 40 cases of were/we're and hell/he'll, and 13 to 14 of 40 cases of
its/it's, well/we'll and ill/i'll. It keeps the clean word in 317 of 318 cases.

The step's second request is part of the trace, and `compare.py` replays it with the
case-by-case check of Table 2.

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

Table 8. The `reranker` lines of the simulator after the cases of `english.dev.jsonl`, run
43481402003, with the work area on. The simulator shares 3 cores of the macOS runner, so these
numbers do not stand for the phone.

| Measure | Value |
| --- | --- |
| Size of the model file | 105,453,504 bytes |
| Load of the model | 98 ms |
| Footprint before the load, after it, after the first correction | 164.6 MB, 181.0 MB, 184.6 MB |
| Time added per space press, mean, median, 95th percentile | 109.8 ms, 90.4 ms, 158.6 ms |

The cases of the work area have a longer text before the word. After those cases, the mean time
added per space press is 151.6 ms. The median is 130.6 ms, and the 95th percentile is 241.2 ms.
After the symbol cases the mean is 173.1 ms, the median 159.7 ms and the 95th percentile 283.6 ms.

In the language model test of the simulator at 2 threads, a context of 20 tokens takes 119.7 ms,
and 8 candidates of 14 tokens then take 36.0 ms in one batch. No run measured the shipped file on
the phone. The `duo:lm` test frees the keyboard's model before it loads its own copy, and the
keyboard loads its model again after, so the keyboard never holds two copies.

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

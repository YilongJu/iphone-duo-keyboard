# Agreement of the keyboard's re-ranking code with the Linux harness

## Summary

On one machine the keyboard's own code and the harness of `scripts/lm-rerank` agree exactly. They
give the same output in all 6,799 dev cases, ignoring letter case, and the same choice in all
8,066 corrections.
llama.cpp gives other model numbers on another machine. The keyboard therefore types 6,124 cases
right on the macOS runner, where the published x86 harness types 6,126.

1. Install a build of `engine/lm-keyboard` on the iPhone Duo and type a few sentences in Notes.
   Then type `duo:lm` and a space. The `reranker` lines give the time per space press and the
   footprint on the phone.
2. Read 6,123 to 6,126 as one result. The harness alone gives 6,126 on x86, 6,123 on ARM Linux
   and 6,124 on the macOS runner.
3. Tune a later model with the harness on the macOS runner, as the keyboard job of
   `.github/workflows/lm-keyboard.yml` runs it. For distilgpt2 the numbers there equal the
   keyboard's numbers in the simulator.

This page does not settle the phone's time and memory, which need step 1. It does not show that
the phone's processor gives the simulator's numbers. It does not read the test half.

## Glossary of the agreement check

| Term | Meaning |
| --- | --- |
| harness | `harness_trace.py`: `rerank.py`, its engine shim and `lm_score.c` with the tuned rule. |
| x86 harness | The harness on an ubuntu-24.04 runner, built from llama.cpp b4846 source. |
| ARM harness | The harness on an ubuntu-24.04-arm runner (Neoverse-N2), built the same way. |
| macOS harness | The harness on the macOS runner of the simulator (Apple M1, virtual), with `lm_score` linked against the macOS part of the app's llama.cpp framework. |
| keyboard | `Tests/TypingEvaluationTests.swift`: the keyboard's controller, engine, scorer and rule in the iOS simulator. |
| correction | One space press whose typed span has more than one engine reading, so the model scores the readings. |
| engine only | The same typing with the engine's own choice, as the keyboard types before its model is ready. |
| distance | The smallest change of one combined score that turns a choice: the lead of the best reading over the next, or the distance of the deciding lead from its margin. |

## Dev scores of the keyboard and the three harnesses

Table 1. Right dev cases per group, from run 42919055547 at commit 8ac2a83. The x86 runner of
this run has the processor of the tuning run 42877972004, an AMD EPYC 7763.

| Run | clean | letter slips | space slips | symbol slips | clean symbols | all dev cases |
| --- | --- | --- | --- | --- | --- | --- |
| each harness and the keyboard, engine only | 957/973 | 1943/2100 | 1299/1500 | 1131/1197 | 427/429 | 6069/6799 |
| x86 harness, with the model | 958/973 | 1975/2100 | 1316/1500 | 1139/1197 | 427/429 | 6126/6799 |
| ARM harness, with the model | 958/973 | 1976/2100 | 1315/1500 | 1138/1197 | 427/429 | 6123/6799 |
| macOS harness, with the model | 958/973 | 1975/2100 | 1315/1500 | 1139/1197 | 427/429 | 6124/6799 |
| keyboard, with the model | 958/973 | 1975/2100 | 1315/1500 | 1139/1197 | 427/429 | 6124/6799 |

The x86 harness gives the numbers of `scripts/lm-rerank/README.md`. Its outputs equal those of the
tuning run byte for byte. Without the model the three harnesses give the same bytes. The keyboard
gives the same outputs after the scorer's normalization.

## Exact agreement of the keyboard and the macOS harness on one machine

Table 2. Checks of the keyboard against the macOS harness. Both ran in the same job, on the same
virtual machine.

| Check | Result |
| --- | --- |
| Outputs, with the model and engine only | the same in 6,799 of 6,799, after the scorer's normalization |
| Corrections on each side | 8,066 and 8,066, matched by case and place |
| Text before the span, ignoring letter case | the same in 8,066 |
| Context the model reads | the same in 8,066 |
| Readings and their marks, in order | the same in 8,066 |
| Choice | the same in 8,066 |
| Choice of the tuned rule on each side's own numbers | equal to the recorded choice in 8,066 on both sides |
| Model numbers | 0.000005 apart at most, the 5 decimals of `lm_score` |

In 92 cases with the model and 97 engine only, the keyboard's output differs in letter case only.
The field gets the capital of a lone "i", and the scorer ignores letter case.

Table 3. The keyboard's C scorer against `lm_score` on the 7,719 requests of each harness.
`scorer_cli` runs `LanguageModel/duo_lm_scorer.c` with 2 threads and calls of at most 31 tokens.

| Machine | `lm_score` threads | Answers |
| --- | --- | --- |
| x86 runner | 4 | the same bytes, 5 decimals each |
| ARM runner | 4 | the same bytes, 5 decimals each |
| macOS runner, with the app's framework | 2 | the same bytes, 5 decimals each |

## Model numbers on four kinds of machine

Table 4. Differences of the model's log probability over the readings of the matched
corrections, in natural-log units. The last two columns count the choices and cases that differ.

| Pair | median | 99th percentile | widest | choices that differ | cases that differ |
| --- | --- | --- | --- | --- | --- |
| macOS harness and keyboard, one machine | 0.000002 | 0.000005 | 0.000005 | 0 | 0 |
| x86 harness on two x86 runners | 0.000010 | 0.612 | 2.020 | 1 | 0 |
| x86 harness and ARM harness | 0.161 | 0.942 | 2.506 | 8 | 5 |
| x86 harness and macOS harness | 0.160 | 0.954 | 2.164 | 4 | 2 |
| x86 harness and keyboard | 0.160 | 0.954 | 2.164 | 4 | 2 |
| ARM harness and keyboard | 0.075 | 0.785 | 2.042 | 8 | 3 |

The second row compares runs 42910824562 and 42919055547 of the same programs. The first runner
offers the AVX-512 instructions of an AMD EPYC 9V74, and the second does not. The build of llama.cpp
follows the instructions of its runner. Then 24 percent of the candidate scores differ by more
than 0.1. Each machine repeats its own numbers exactly: the ARM runner in three runs, the
simulator in four.

Table 5. The four choices of the keyboard that differ from the x86 harness. Each has the same
readings on both sides, and each lies within 0.33 of its turning point.

| Case | Context | x86 harness | keyboard | distance, x86 | distance, keyboard |
| --- | --- | --- | --- | --- | --- |
| en-dev-apostrophe_missing-0174 | I have friends | who'll | who all | 0.323 | 0.054 |
| en-dev-letter_to_space-0045 | I've neither eaten nor | drug | dry | 0.248 | 0.079 |
| en-dev-space_transposed-0027 | Sami decided to put god in the | center | centre | 0.174 | 0.230 |
| en-dev-space_transposed-0031 | Are the | doors high | door high | 0.220 | 0.253 |

Two of the four change a right case: `apostrophe_missing-0174` and `space_transposed-0031`, both
right in the x86 harness. In the x86 harness, 279 of 8,066 choices lie within 0.5 of their
turning point.

## Readings of equal engine score on Linux and Apple

The engine sorts its readings with `qsort`, which does not keep the order of equal scores. The
C library of Linux and that of Apple order such readings differently. Against a Linux harness, 51
of the keyboard's 8,066 reading lists come in another order. Each differs at places of equal score.
In 4 of them two readings share one score near the end of the list. The list holds room for one of
the two, and each side keeps a different one. All 51 keep the same choice. On one machine the
reading lists agree in all 8,066 corrections.

## Time and memory of the model in the simulator

Table 6. The `reranker` lines of the simulator after the English dev cases, in runs 42902804816,
42910824562 and 42919055547. The simulator shares 3 cores of the macOS runner. Its process holds
thousands of keyboard views, so these numbers do not stand for the phone.

| Measure | Range over the three runs |
| --- | --- |
| Load of the model | 61 ms to 90 ms |
| Footprint added by the model, up to the first correction | 16.5 MB to 17.5 MB |
| Time added per space press, median | 36.2 ms to 55.1 ms |
| Time added per space press, mean | 41.3 ms to 71.5 ms |
| Corrections, and choices the model changed | 6,238, and 163, in each run |

The language model test on the phone measured 23.4 ms for 8 candidates after a 20-token context.
Its peak footprint was 47.3 MB, with its own settings.

## Method of the agreement check

1. `harness_trace.py` types the dev cases through `rerank.py` with the tuned setting. It writes
   each correction: the text before, the context, the readings, the model's numbers and the choice.
2. The workflow scores every distinct request of that run again with `lm_score` and `scorer_cli`.
   `scorer_cli` wraps `LanguageModel/duo_lm_scorer.c`. The workflow compares the two answers.
3. The simulator runs every unit test. `TypingEvaluationTests` types the dev cases of `english`
   and `english-symbols` with the model and with the engine alone. It writes the same trace.
4. The same job then builds the engine shim, `lm_score` and `scorer_cli` against the macOS part of
   the app's framework. It runs steps 1 and 2 on the same machine.
5. `compare.py` compares two runs case by case and correction by correction. It recomputes each
   choice from the run's own numbers, and it checks the x86 harness against the published numbers.
6. The harness also runs on an x86 and an ARM Linux runner, as controls for the machine.

The runs type, score and compare the dev half only. The workflow stops when the simulator writes a
test-half file, and `compare.py` stops when a folder holds one.

## Commands of the agreement check

All runs are on GitHub Actions (`.github/workflows/lm-keyboard.yml`). From the repository root:

    gh run download RUN_ID --dir artifacts
    python3 scripts/lm-keyboard/compare.py --reference artifacts/harness-mac --reference-name "macOS harness" \
        --other artifacts/keyboard --other-name keyboard --out build/lm-keyboard/compare

`compare.py` exits with code 1 when any case differs. The compare job of this workflow therefore
stays red. The two cases of Table 5 differ between the x86 harness and the keyboard.

## Files of this folder

| File | Content |
| --- | --- |
| `harness_trace.py` | The harness with the tuned rule, with a trace of every correction |
| `scorer_cli.c` | The keyboard's scorer behind the request format of `lm_score.c` |
| `compare.py` | The comparison of two runs, and the tables of this page |

## Limits of this check

- The phone has another processor than the simulator's runner, and Table 4 shows how much the
  model's numbers move between machines.
- The scorer check compares 5-decimal answers, the precision of `lm_score`.
- The x86 runners differ in instruction set, and the build of run 42902804816 did not record its
  full set. Its numbers equal those of the runner without AVX-512.
- The cases hold lower-case text only. Capitals that the keyboard restores could change a later
  context in other text, and this check does not cover that.

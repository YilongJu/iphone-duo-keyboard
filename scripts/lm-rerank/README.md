# Re-ranking of English corrections with a small language model

## Summary

A small language model that re-ranks the engine's 8 best readings raises the right dev cases
from 6,069 to between 6,112 and 6,177 of 6,799. Clean text stays right as often as before.
Only the distilgpt2 models are likely to stay under 50 ms on the phone.

1. Keep distilgpt2 Q3_K_M (the model that ships) for a first keyboard build: weight 1.0,
   `margin_from_typed` 24, `margin_to_typed` 0, `margin_other` 2, with the space-after term.
   It gains 57 dev cases at an estimated 23 ms per correction.
2. Measure SmolLM2-135M and Qwen2.5-0.5B on the phone with the language model test before
   choosing either. Their phone time comes from a Linux ratio only.
3. Any keyboard code that tokenizes with llama.cpp b4846 must repair token -1 the way
   `lm_score.c` does (see "Tokenizer defect in llama.cpp b4846").

This page does not settle the test-half score, the phone time and memory of any model except
distilgpt2 Q3_K_M, or Qwen3-0.6B, which llama.cpp b4846 does not load.

## Glossary

| Term | Meaning |
| --- | --- |
| reading | One way to read the typed span as words, from `duo_english_readings` in `Engine/duo_engine.c`. The text as typed is always one reading. |
| engine score | The engine's log probability of a reading, slips included: the number `duo_correct_english` compares. |
| slip cost | The part of the engine score that the assumed slips cost. The rest is the lexicon's log probability. |
| control | The engine's own choice, typed through the Linux copy of the keyboard rules. |
| combined score | engine score + weight × (model log probability of the reading after the text before it, plus, with the space-after term, the log probability that the next token starts with a space). |
| margin | How much higher the combined score of another reading must be before it replaces the engine's choice. `margin_from_typed` applies when the engine kept the text as typed, `margin_to_typed` when the other reading is the text as typed, and `margin_other` otherwise. |
| oracle | A chooser that knows the intended text and picks it whenever the 8 readings hold it. Its score is the ceiling for any re-ranker over the same readings. |
| fold | One of two halves of the dev cases, split by a hash of context and intended text. |

## Dev scores per group

Table 1. Right dev cases per group, from run 42877972004 at commit 6a000f7. The control
equals the macOS keyboard run (`Tests/TypingEvaluationTests.swift`) in every group.

| Run | clean | letter slips | space slips | symbol slips | clean symbols | all dev cases |
| --- | --- | --- | --- | --- | --- | --- |
| control | 957/973 | 1943/2100 | 1299/1500 | 1131/1197 | 427/429 | 6069/6799 |
| margins without a model | 957/973 | 1943/2100 | 1299/1500 | 1131/1197 | 427/429 | 6069/6799 |
| distilgpt2 Q3_K_M | 958/973 | 1975/2100 | 1316/1500 | 1139/1197 | 427/429 | 6126/6799 |
| distilgpt2 Q3_K_M, no context | 959/973 | 1946/2100 | 1304/1500 | 1135/1197 | 427/429 | 6078/6799 |
| distilgpt2 Q4_K_M | 957/973 | 1980/2100 | 1311/1500 | 1135/1197 | 427/429 | 6129/6799 |
| gpt2 Q4_K_M | 957/973 | 1966/2100 | 1315/1500 | 1138/1197 | 427/429 | 6112/6799 |
| SmolLM2-135M Q4_K_M | 957/973 | 1983/2100 | 1323/1500 | 1144/1197 | 427/429 | 6146/6799 |
| SmolLM2-360M Q4_K_M | 957/973 | 1990/2100 | 1326/1500 | 1151/1197 | 427/429 | 6171/6799 |
| Qwen2.5-0.5B Q4_K_M | 958/973 | 1990/2100 | 1327/1500 | 1151/1197 | 427/429 | 6177/6799 |
| Qwen2.5-0.5B Q4_K_M, no context | 959/973 | 1947/2100 | 1307/1500 | 1131/1197 | 427/429 | 6081/6799 |
| oracle over the 8 readings | 973/973 | 2097/2100 | 1413/1500 | 1176/1197 | 429/429 | 6688/6799 |

The larger the model, the more letter and space slips the re-ranker repairs. The gain needs
the text before the span: without it, distilgpt2 gains 9 cases and Qwen2.5 gains 12. The
margins alone, tuned the same way with weight 0, gain nothing.

Per case, distilgpt2 Q3_K_M repairs 79 cases and breaks 22. Qwen2.5-0.5B repairs 125 and
breaks 17. A typical repair is "how much sutar" to "sugar" (the engine gave "star"). A
typical break is "i need foty" to "to try" (intended "forty").

## Tuned settings and the check inside the dev half

Table 2. Tuned settings, and the gain in right cases over the control. In the two-fold
check, the clean rule and the choice of setting use one fold only, and the gain is read on the
other fold. The last column is the change in right clean cases on the other fold.

| Run | weight | margin from typed | margin to typed | margin other | space after | gain on dev | fold 0 to 1 | fold 1 to 0 | clean change |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| margins without a model | 0 | 6 | 0 | 0 | off | +0 | +0 | +0 | +0 / +0 |
| distilgpt2 Q3_K_M | 1.0 | 24 | 0 | 2 | on | +57 | +54 | +23 | -2 / +1 |
| distilgpt2 Q3_K_M, no context | 0.75 | 12 | 0 | 2 | off | +9 | +6 | +2 | -1 / +2 |
| distilgpt2 Q4_K_M | 0.3 | 8 | 0 | 0 | on | +60 | +48 | +20 | -4 / +0 |
| gpt2 Q4_K_M | 0.75 | 16 | 0 | 2 | on | +43 | +21 | +11 | +0 / +0 |
| SmolLM2-135M Q4_K_M | 0.75 | 16 | 0 | 2 | on | +77 | +43 | +27 | +0 / -2 |
| SmolLM2-360M Q4_K_M | 0.75 | 12 | 0 | 2 | on | +102 | +60 | +42 | +0 / +0 |
| Qwen2.5-0.5B Q4_K_M | 0.75 | 12 | 0 | 2 | on | +108 | +55 | +44 | -4 / +1 |
| Qwen2.5-0.5B Q4_K_M, no context | 0.5 | 12 | 0 | 2 | on | +12 | +6 | +9 | -3 / +2 |

Every tuned value sits inside the grid, except `margin_to_typed` 0, which is its lowest
value. The grid holds 2,160 settings per model: weight 0.1 to 3, `margin_from_typed` 0 to 48,
`margin_to_typed` 0 to 99, `margin_other` 0 or 2, and the space-after term on or off.

## Size, licence and expected phone cost per model

Table 3. File size, licence, and the phone estimates. The Linux numbers come from the
language model test (`LanguageModel/duo_lm_probe.c`) at 2 threads, with distilgpt2 Q3_K_M
measured on the same runner. The phone measured 1.71 ms per token and 23.4 ms for 8
candidates (13.6 ms context and 9.8 ms batch) with distilgpt2 Q3_K_M. Estimate A scales
23.4 ms by the per-token ratio, and estimate B by the ratio of the 8-candidate times.

| Model | File MB | Licence | Per-token ratio | Phone per token ms | Phone 8 candidates ms, A / B | Phone extra memory MB | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| distilgpt2 Q3_K_M | 71.9 | Apache-2.0 | 0.98 | 1.67 | 22.9 / 23.5 | 26.5 | none |
| distilgpt2 Q4_K_M | 81.0 | Apache-2.0 | 1.03 | 1.77 | 24.2 / 24.0 | 26.5 | none |
| gpt2 Q4_K_M | 107.6 | MIT | 1.63 | 2.79 | 38.1 / 42.7 | 35.6 | none |
| SmolLM2-135M Q4_K_M | 100.6 | Apache-2.0 | 2.30 | 3.92 | 53.7 / 46.8 | 29.0 | latency near 50 ms |
| SmolLM2-360M Q4_K_M | 258.1 | Apache-2.0 | 4.73 | 8.09 | 110.7 / 132.4 | 38.1 | latency over 50 ms |
| Qwen2.5-0.5B Q4_K_M | 379.4 | Apache-2.0 | 6.05 to 10.08 | 10.4 to 17.2 | 141.6 / 164.9 (AMD runner) | 54.1 (AMD runner) | latency over 50 ms |
| Qwen3-0.6B-Base Q4_K_M | 378.3 | Apache-2.0 | | | | | does not load in llama.cpp b4846 |

The more weights a model has, the longer it takes per token. Qwen2.5 also has a vocabulary
of 151,936 tokens, and the model scores every token at each place.

- The phone memory estimate is 26.5 MB plus the model's growth in anonymous memory on Linux,
  less the growth of distilgpt2 Q3_K_M. The weights stay mapped from the file, and iOS does
  not count those pages against the keyboard limit of about 177 MB.
- On the Intel Xeon 8573C runner, llama.cpp copied the Qwen2.5 weights into anonymous memory
  (285 MB after the load). On an AMD runner the growth was 60 MB. Table 3 shows the AMD numbers.
- The licences come from the model cards of the GGUF repositories.
- Qwen3-0.6B stops at the load with "unknown model architecture: 'qwen3'". It needs a newer
  llama.cpp than b4846. This measurement does not upgrade llama.cpp.

## Tokenizer defect in llama.cpp b4846

The BPE tokenizer of llama.cpp b4846 gives token -1 for some texts, for example " ich". The
cause sits in `src/llama-vocab.cpp`: a word piece that is a lone space becomes the token of
"[UNK]", and a GPT-2 style vocabulary has no "[UNK]". `lm_score.c` puts the single-space token
in place of -1. For the GPT-2 vocabulary, 10 of the repaired texts were compared with the
Hugging Face tokenizer, and all 10 gave the same tokens. The distilgpt2 run repaired 117
tokens. Without the repair, `llama_decode` refuses the batch.

## Method

1. `duo_english_readings` returns up to 8 readings of a typed span, best engine score first.
   The list holds the text as typed, and the best reading per last word of each search: the
   text, and each shifted space. It marks the reading that `duo_correct_english` returns.
2. `duo_correct_english` keeps its output. The workflow compares `duo_cli` with the engine of
   `engine/small-lm` on the English, symbol and Pinyin dev cases, and the outputs are the same.
   `readings_check.c` checks the readings of all 6,799 dev inputs under the memory checks.
3. `rerank.py` types each dev case through a Python copy of `correctLastWord`
   (`Shared/KeyboardTextController.swift`), as the macOS evaluation test does.
4. At each correction, `lm_score.c` scores every reading after the text before the span.
   The text gets the capitals a person would see: the word "I" and the first letter of the field.
5. The engine's choice stays unless another reading's combined score is higher by the margin.
6. The tuning picks the setting with the most right dev cases. A setting must keep as many
   cases right as the control in the groups clean and clean symbols.

The test half is never read. `rerank.py` loads only `english.dev.jsonl` and
`english-symbols.dev.jsonl`, and stops on a case from another half.

## Commands

All runs are on GitHub Actions (`.github/workflows/lm-rerank.yml`, ubuntu-24.04, 4 cores).
The same commands work on any Linux machine, from the repository root:

    bash scripts/lm-rerank/build_on_linux.sh llama
    bash scripts/lm-rerank/fetch_models.sh qwen2.5-0.5b-q4
    LD_LIBRARY_PATH=$PWD/build/lm-rerank/llama/lib python3 scripts/lm-rerank/rerank.py \
        --shim build/lm-rerank/libduo_shim.so --lm build/lm-rerank/lm_score \
        --model build/lm-rerank/models/Qwen2.5-0.5B.Q4_K_M.gguf --name qwen2.5-0.5b-q4 \
        --out build/lm-rerank/results/rerank-qwen2.5-0.5b-q4
    gh run download RUN_ID --dir artifacts
    python3 scripts/lm-rerank/summarize.py artifacts

## Files

| File | Content |
| --- | --- |
| `build_on_linux.sh` | Builds the engine shim, the readings check, and, against llama.cpp b4846, the scorer and the language model test |
| `fetch_models.sh` | The model files, each at a fixed commit with its SHA-256 value |
| `engine_shim.c` | The engine as a shared library for `rerank.py` |
| `readings_check.c` | Checks `duo_english_readings` against `duo_correct_english` |
| `lm_score.c` | Scores candidate texts after a context |
| `rerank.py` | The keyboard rules, the control, the oracle, the grid search and the two-fold check |
| `summarize.py` | The results tables from the run artifacts |

## Limits of this measurement

- The phone numbers for every model except distilgpt2 Q3_K_M come from x86 Linux ratios. The
  runners differ in processor, and the two estimates for one model differ by up to 4 times.
- The best setting comes from the same dev cases that score it. The two-fold check gives the
  held-out gain inside the dev half, from +11 to +60 cases per fold.
- The Python copy of the keyboard rules matches the macOS run in every group total. It was not
  compared case by case, because the macOS run stores only the totals. It leaves out capitals,
  which the scorer ignores.
- The model reads one space between the text before the span and the reading. The space-after
  term assumes a space follows the span. A correction after a quote mark or before a comma
  would differ. The dev cases hold few of those.
- The readings are the best per last word, so two readings that end in the same word keep only
  the better one. The oracle still reaches 6,688 of 6,799.
- The keyboard runs the distilgpt2 Q3_K_M rule. `scripts/lm-keyboard/README.md` compares the
  keyboard's own code with this harness on the dev half.

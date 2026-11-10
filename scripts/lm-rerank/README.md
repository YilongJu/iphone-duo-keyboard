# Re-ranking of English corrections with a small language model

## Summary

RESULTS_SUMMARY

## Glossary

| Term | Meaning |
| --- | --- |
| reading | One way to read the typed span as words, from `duo_english_readings` in `Engine/duo_engine.c`. The text as typed is always one reading. |
| engine score | The engine's log probability of a reading, slips included. The same number `duo_correct_english` compares. |
| slip cost | The part of the engine score that the assumed slips cost (the channel cost). The rest is the lexicon's log probability. |
| control | The engine's own choice, typed through the Linux copy of the keyboard rules. |
| re-ranked | The choice after the language model scores the readings, with the tuned setting. |
| combined score | engine score + weight * (language-model log probability of the reading after the text before it, plus, when `space after` is 1, the log probability that the next token starts with a space). |

## Method

1. `duo_english_readings` returns up to 8 readings of a typed span: the text as typed, and the
   best reading per last word of each search (the text and each shifted space). It marks the
   reading that `duo_correct_english` returns. `duo_correct_english` itself does not change; the
   workflow checks that `duo_cli` gives the same output as on `engine/small-lm` on the English,
   symbol and Pinyin dev cases.
2. `rerank.py` types each dev case through a Python copy of `correctLastWord`
   (`Shared/KeyboardTextController.swift`), as `Tests/TypingEvaluationTests.swift` does on the
   Mac: the context sits in the field, then the typed characters and one space.
3. At each correction the language model (`lm_score.c`, llama.cpp b4846, the commit the app
   links) scores every reading after the text before the span. The text gets the capitals a
   person would see: the word "I" and the first letter of the field.
4. The engine's choice stays unless another reading's combined score is higher by a margin. The
   margin depends on the move: from the text as typed to a correction, from a correction back to
   the text as typed, and from one correction to another.
5. A grid search over the weight, the three margins and `space after` picks the setting with the
   most right dev cases, among the settings that keep at least as many clean cases right as the
   control (groups `clean` and `clean_symbols`). The test half is never read.
6. A two-fold check inside the dev half tunes on one half of the dev cases (by a hash of the case
   id) and reads the gain on the other half.

## Commands

All runs are on GitHub Actions (`.github/workflows/lm-rerank.yml`, ubuntu-24.04, 4 cores). The
same commands work on any Linux machine, from the repository root:

    bash scripts/lm-rerank/build_on_linux.sh llama
    bash scripts/lm-rerank/fetch_models.sh qwen2.5-0.5b-q4
    LD_LIBRARY_PATH=$PWD/build/lm-rerank/llama/lib python3 scripts/lm-rerank/rerank.py \
        --shim build/lm-rerank/libduo_shim.so --lm build/lm-rerank/lm_score \
        --model build/lm-rerank/models/Qwen2.5-0.5B.Q4_K_M.gguf --name qwen2.5-0.5b-q4 \
        --out build/lm-rerank/results/rerank-qwen2.5-0.5b-q4
    python3 scripts/lm-rerank/summarize.py ARTIFACTS_FOLDER

## Files

| File | Content |
| --- | --- |
| `build_on_linux.sh` | Builds the engine shim, the readings check, and against llama.cpp b4846 the scorer and the language model test |
| `fetch_models.sh` | The model files, each at a fixed commit with its SHA-256 value |
| `engine_shim.c` | The engine as a shared library for `rerank.py` |
| `readings_check.c` | Checks `duo_english_readings` against `duo_correct_english`, built with the memory checks |
| `lm_score.c` | Scores candidate texts after a context |
| `rerank.py` | The keyboard rules, the control, the grid search and the two-fold check |
| `summarize.py` | The results tables from the run artifacts |

RESULTS_BODY

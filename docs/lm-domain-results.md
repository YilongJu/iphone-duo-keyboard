# Results of the domain round of the re-ranker fine-tune with the work area on

## Summary

The shipped file stays. The one candidate of the pick did not pass the replacement rule on the fresh held-out set.

1. Keep `smollm2-lora-typed-seed1.Q4_K_M.gguf` at the shipped setting.
2. Read Table 2: the arm `dom-s100-seed1` passes all seven held-out conditions, and it was not the candidate.
3. Decide whether the pinned dev floors of pick condition 6 should stop an arm that misses them by 1 to 5 cases.
4. Read `scripts/lm-domain/reports/select-tables.md` for every arm on every selection set and on the test half.

This page does not settle the slip rate of the owner. Every number was measured on the symbol cases before the comma and period keys moved.

## Glossary

| Term | Meaning |
| --- | --- |
| `ship` | The shipped file at the shipped setting: weight 1.0, margins 0 / 4 / 2, lead 4. |
| `soup-mix` | The mean of the weights of the three `mix` seeds of round 2. |
| `dom-s100` | A fine-tune of this round on everyday lists plus all 129,760 domain lists. |
| ceiling setting | The setting with the most right tuning cases among those that change at most 0.3 percent of clean tune words. |
| perfect chooser | A search that knows the intended text and takes readings from the lists of the engine. |
| changed word | A correctly typed word of running text that the keyboard changes. |

## Pick of one candidate on the selection sets

The pick names `soup-mix` at its ceiling setting (weight 1.5, margins 1 / 8 / 2, lead 4). It is the only entry of 20 files that passes the nine conditions.
Every `dom-s100` entry misses pick condition 6, the pinned dev floors. The entry `dom-s100-seed1` at its ceiling setting misses that condition alone.

Table 1. Selection sets, work area on. A changed count is changed correct words.

| Count | engine alone | perfect chooser | `ship` | `soup-mix`, ceiling | `dom-s100-seed1`, ceiling |
| --- | --- | --- | --- | --- | --- |
| Dev right, of 6,799 | 6,078 | 6,704 | 6,544 | 6,560 | 6,538 |
| GitHub misspellings right, of 1,500 | 1,269 | 1,447 | 1,280 | 1,288 | 1,295 |
| Select stream, changed of 8,439 words | 96 | 0 | 68 | 22 | 13 |
| Technical and written streams, changed words | 240 | 3 | 238 | 140 | 38 |
| Domain dev slips right, of 3,466 | 2,892 | 3,285 | 2,909 | 2,932 | 3,148 |
| Apostrophe word, next word, of 1,623 | 882, 628 | 1,604, 1,597 | 1,264, 1,432 | 1,317, 1,448 | 1,257, 1,459 |

The more domain lists an arm trains on, the fewer technical words it changes: 149, 103, 81 and 57 changed words at share 0, 0.15, 0.4 and 1.0.

## One read of the fresh held-out set

`soup-mix` at its ceiling setting misses condition 3: it gets 941 clean generated cases right, and `ship` gets 946. It passes the other six conditions.
The plan was committed at c0bdee5 before the read, with the SHA-256 value `9df4367654841b0b4e4edf39cb53bda981c9d3084ed1c9c1fa3c72bbf976c4ca`.

Table 2. Fresh held-out set. Only `soup-mix` was the candidate. The other arms are in the plan for the report.

| Count | engine alone | perfect chooser | `ship` | `soup-mix`, ceiling | `full-mix-seed1` | `dom-s100-seed1` | `dom-s100-seed1`, ceiling |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Generated right, of 6,727 | 6,070 | 6,663 | 6,494 | 6,501 | 6,511 | 6,482 | 6,493 |
| Generated clean, clean symbols | 945, 421 | 971, 429 | 946, 423 | 941, 426 | 947, 425 | 946, 423 | 946, 426 |
| Everyday stream, changed of 25,974 words | 361 | 0 | 188 | 46 | 35 | 63 | 39 |
| GitHub misspellings right, of 1,500 | 1,309 | 1,461 | 1,336 | 1,337 | 1,356 | 1,358 | 1,345 |
| Birkbeck right, of 600 | 329 | 441 | 339 | 346 | 345 | 347 | 337 |
| Domain cases right, of 4,611 | 4,215 | 4,457 | 4,192 | 4,218 | 4,197 | 4,364 | 4,368 |
| Domain slips right, of 1,955 | 1,567 | 1,801 | 1,570 | 1,595 | 1,572 | 1,727 | 1,728 |
| Slips of withheld words right, of 247 | 217 | 247 | 203 | 209 | 208 | 234 | 232 |
| Technical and written streams, changed of 19,925 words | 202 | 4 | 215 | 118 | 120 | 60 | 43 |
| Held-out conditions passed, of 7 | | | reference | 6 | 7 | 7 | 7 |

`dom-s100-seed1` corrects 232 to 234 of 247 slips of withheld words, against 203 for `ship`. So the gain holds for pack words whose slips the arm never trained on.
In 128 documents `dom-s100-seed1` at its ceiling setting changes fewer technical words than `ship`, and in 8 documents more.

## Parity of the converted files

The conversion keeps the tokens, the prompt and the weights. With an F32 file and a 32-bit cache, `lm_score` is within 0.0002 nats of PyTorch float32 for the 19 files with a complete reading. The reading of `dom-s100-seed3` on the domain lists is in `scripts/lm-domain/reports/parity-table.md`.
The f16 file of `check_parity.py` passes the 0.05 limit for 5 of 20 files, and an F32 file with the standard `lm_score` for 15 of 20. The differences come from 16-bit weights and the 16-bit key and value cache of llama.cpp.
The Q4_K_M file that the phone runs takes another reading than PyTorch float32 in 181 to 270 of about 46,970 corrections: 270 for `ship`, 235 for `soup-mix`, 181 for `dom-s100-seed1`.

## Remaining errors of the shipped file

Table 3. Labels of 200 errors of `ship` per set, by `scripts/lm-domain/label-rule.md`.

| Set | label noise | engine recall | model error | unclear |
| --- | --- | --- | --- | --- |
| Dev half | 143 | 40 | 17 | 0 |
| GitHub misspellings | 137 | 19 | 42 | 2 |

Most remaining errors are label noise: a short context that fits both texts, or a spelling variant. The perfect chooser does not reach the intended text in 95 of the 255 dev errors and in 53 of the 220 GitHub errors.

## Other findings

- Setting selection under a ceiling: for `ship` the 0.3 percent ceiling halves the changed words and loses 181 domain slips and 77 GitHub misspellings on the selection sets. On the held-out set it misses two conditions.
- Loss arms: the clean-weighted cross-entropy and the expected-cost loss both score below the base arm of their seed. The loss rule picks neither.
- Apostrophe step: lead 4 fits the shipped file only. At its own lead every arm gets at least as many next-word cases right as `ship`, except `dom-s100-seed2`.
- List builder of rounds 1 and 2: 200 of 54,759 clean running-text lists of round 2 have a target that adds the next word. No arm writes a repeated word on the selection streams, so the effect is not visible there.
- Typing log: `docs/typing-log-design.md`. Run 43258534212 passes its 35 tests among 290.

## Limits of these results

- `dom-s100-seed1` was not the candidate, so its held-out counts are a report and no decision.
- One seed of share 1.0 was read on the held-out set. Seeds 2 and 3 were scored on the selection sets only.
- Pick condition 6 compares with floors from another run. `ship` itself has 6,544 dev cases in this harness.
- The loss comparison has two seeds per loss.

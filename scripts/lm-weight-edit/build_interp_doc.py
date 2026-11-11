"""Writes docs/lm-weight-edit-interpolation-results.md: the prose of the interpolation report, with
the tables that interp_report.py and holdout_report.py printed, so that no table is typed by hand.

Usage: python scripts/lm-weight-edit/build_interp_doc.py
    reads build/lm-weight-edit/results/interp.md and build/lm-weight-edit/holdout/report.md
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTERP = (ROOT / "build" / "lm-weight-edit" / "results" / "interp.md").read_text(encoding="utf-8")
HOLDOUT = (ROOT / "build" / "lm-weight-edit" / "holdout" / "report.md").read_text(encoding="utf-8")

TITLES = {"### SmolLM2-135M, LoRA fine-tune seed 1": "### Tables of SmolLM2-135M with its LoRA fine-tune (`s-wise`)",
          "### distilgpt2, LoRA fine-tune seed 1": "### Tables of distilgpt2 with its LoRA fine-tune of seed 1 (`d-wise`)",
          "### distilgpt2, LoRA fine-tune seed 2": "### Tables of distilgpt2 with its LoRA fine-tune of seed 2 (`d2-wise`)"}
for old, new in TITLES.items():
    if old not in INTERP:
        raise SystemExit(f"interp.md does not hold the heading {old!r}")
    INTERP = INTERP.replace(old, new)


def holdout_table(letter: str) -> str:
    start = HOLDOUT.index(f"Table {letter}.")
    end = HOLDOUT.find("\nTable ", start + 1)
    block = HOLDOUT[start:end if end != -1 else len(HOLDOUT)].strip()
    return block.split("\n", 2)[2].strip()  # the table without its one-line caption


TEXT = """# Interpolation between the stock and the fine-tuned re-ranker weights, measured on clean words

## Summary

At its own tuned setting, an interpolation coefficient does not meet the clean-word rule on dev,
on any of three fine-tunes. On fresh held-out cases the SmolLM2 fine-tune meets that rule at its
tuned setting, and the chosen coefficient does not add clean words to it.

What to do:

1. Do not ship an interpolated model. At the chosen coefficient, a = 0.9, the paired tests do not
   separate it from the fine-tune on generated cases. On SmolLM2 it changes more clean held-out
   sentences.
2. Do not reject the SmolLM2 fine-tune over its 2 clean dev words (955 against 957). On the
   held-out set the same file keeps 952 clean cases against 945 for the engine alone. The two
   sets differ in their clean categories, and neither paired test separates the arm from the control.
3. Keep the distilgpt2 fine-tune out. It keeps fewer clean cases than the engine alone on dev (945
   against 957) and on the held-out set (935 against 945), and interpolation does not repair that.
4. If real typos matter more than real-word slips, test a lower re-ranker weight in the
   fine-tuning round. Weight 0.5 with margins 1, 0, 0 on the unchanged SmolLM2 fine-tune repairs
   1,310 of 1,500 held-out GitHub misspellings against 1,247. It costs 47 generated real-word slips,
   129 GitHub real-word typos (250 against 379) and 62 clean sentences.

This report does not settle phone time or memory, a second SmolLM2 seed, or Q4_K_M files. Every
file here is Q3_K_M.

```mermaid
xychart-beta
    title "Clean dev words right of 973, SmolLM2 at each coefficient"
    x-axis "coefficient a (0 = stock, 1 = fine-tune)" [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1]
    y-axis "clean dev words right" 940 --> 960
    line [948, 953, 945, 948, 951, 945, 949, 954, 956, 954, 955]
    line [957, 957, 957, 957, 957, 957, 957, 957, 957, 957, 957]
```

Figure 1. Clean dev words that SmolLM2 keeps right at each coefficient, each at its own tuned
setting. The flat line is the engine alone at 957. Every coefficient lies below that line, and
the count does not rise or fall steadily with the coefficient.

## Terms and arm labels

| Term | Meaning |
| --- | --- |
| coefficient a | The weights are (1 - a) stock + a fine-tune. This is WiSE-FT interpolation (Wortsman et al. 2022). With one fine-tune it equals task vector scaling at lam = a (Ilharco et al. 2023), so one arm covers both methods. |
| control | The engine's own choice, without a model. |
| setting | The re-ranker weight, its three margins and the space-after switch of `rerank.py`. The tuning split (6,748 cases) picks it for each arm. |
| clean rule | An arm keeps at least as many right cases as the control in the groups clean and clean symbols. |
| stopping cases | 6,740 cases outside dev. They choose the coefficient. |
| dev | 6,799 generated cases, and 751 published misspellings apart. |
| held-out set | The set of the second fine-tuning round, final since 2026-11-11: 6,745 generated cases, 4,000 clean sentences, 2,500 GitHub typos and 721 Mitton pairs. |
| share of the gain kept | Right cases at a, less those at a = 0, divided by the same difference at a = 1. |

Table 1. The arm labels. Every arm is a Q3_K_M file in the typed format.

| Label | Arm | Why it exists |
| --- | --- | --- |
| `s-wise-a` | SmolLM2-135M at coefficient a, from its LoRA fine-tune | The test on SmolLM2 |
| `d-wise-a` | distilgpt2 at coefficient a, from its LoRA fine-tune of seed 1 | The test on distilgpt2 |
| `d2-wise-a` | The same from the LoRA fine-tune of seed 2 | The spread between fine-tuning seeds |
| `s-stock`, `d-stock` | a = 0 | The lower end of each curve |
| `s-lora`, `d-lora` | a = 1, the fine-tune | The upper end of each curve |
| `-weight-w` | The fine-tune, unchanged, at re-ranker weight w | The calibration-only control: a lower weight in place of an interpolation |
| `s-wise-0.7-common` | SmolLM2 at a = 0.7 at the setting of `s-lora` | A row found on dev after the fact |

## Dev result of the chosen coefficient on three fine-tunes

The grid (a from 0.1 to 0.9), the selection rule and the dev criteria were committed in `7783c50`,
before any interpolated arm met dev. The rule chose a = 0.9 for every fine-tune, and no chosen
coefficient meets the clean rule.

Table 2. The chosen coefficient of each fine-tune on dev, at its tuned setting, beside the control
and the fine-tune. The chosen coefficient differs from its fine-tune by 1 clean word, and
it does not reach the control's 957.

| Arm | Clean of 973 | Clean symbols of 429 | Real-word slips of 300 | Dev right of 6,799 | Share of the gain kept | Published misspellings of 751 |
| --- | --- | --- | --- | --- | --- | --- |
| control | 957 | 427 | 62 | 6,069 | | 381 |
| `s-lora` | 955 | 427 | 257 | 6,537 | 1.00 | 372 |
| `s-wise-0.9`, chosen | 954 | 427 | 261 | 6,537 | 1.00 | 384 |
| `d-lora` | 945 | 427 | 250 | 6,491 | 1.00 | 367 |
| `d-wise-0.9`, chosen | 946 | 427 | 251 | 6,494 | 1.01 | 371 |
| `d-lora` seed 2 | 950 | 429 | 241 | 6,486 | 1.00 | 328 |
| `d2-wise-0.9`, chosen | 949 | 429 | 244 | 6,478 | 0.98 | 351 |
| `s-lora-weight-1.0`, chosen calibration-only candidate | 952 | 426 | 258 | 6,537 | 1.00 | 389 |

The design's main comparison is the chosen calibration-only candidate: the fine-tune with the same
extra selection on the stopping cases. That rule chose weight 1.0 for SmolLM2, the tuned setting
itself for distilgpt2 seed 1 (weight 1.5) and for seed 2 (weight 1.0). Not one of the three meets
the clean rule on dev. So neither pre-set selection, of a coefficient or of a weight, gives a
model that meets it.

Across each whole grid, the clean count lies between 944 and 956. Not one of the 27 grid arms
meets the clean rule and keeps more than half the gain. The count of grid values is a description
of dev, read nine times per fine-tune.

The paired tests do not separate these arms from the control on clean cases, and they do not
show that the arms are equal to it either. At a = 0.9, SmolLM2 turns 14 clean dev cases
wrong and 11 right against the control (exact McNemar p = 0.69). distilgpt2 seed 1 turns 19 wrong
and 8 right (p = 0.052). The stock models in the typed format also sit below the control, at 948
and 954. So a return toward the stock weights cannot restore the control's count.

## Re-ranker weight as a simpler explanation of the clean count

The re-ranker adds weight times the model score to the engine score. A lower weight on the
unchanged fine-tune meets the clean rule on dev where the interpolation does not.

Table 3. The fine-tune at re-ranker weight 0.5 on dev. Each row is the best tuning-split setting
of that weight under the clean rule, so its margins differ from the tuned setting too (1, 0, 0 or
2, 0, 0 against 2, 4, 2 or 1, 4, 2). The table does not separate the weight from the margins. The selection rule on the stopping cases did not choose these
rows, so they are readings of dev after the fact. The lower the weight, the more clean words kept
and the fewer real-word slips repaired.

| Arm | Clean of 973 | Clean symbols of 429 | Real-word slips of 300 | Dev right of 6,799 | Published misspellings of 751 |
| --- | --- | --- | --- | --- | --- |
| control | 957 | 427 | 62 | 6,069 | 381 |
| `s-lora-weight-0.5` | 959 | 427 | 213 | 6,485 | 400 |
| `d-lora-weight-0.5` | 957 | 428 | 197 | 6,423 | 378 |
| `d-lora` seed 2 at weight 0.5 | 959 | 429 | 186 | 6,405 | 361 |

The second control scores every coefficient at the setting of its fine-tune. There SmolLM2 meets
the clean rule at a = 0.2 to 0.7, with 957 to 961 clean words. distilgpt2 does not meet it at any
coefficient of 0.2 or more. The tables at the end give every row.

## Held-out comparison on the set of the second fine-tuning round

`read_holdout.py` of the second fine-tuning round read its held-out set once for the eleven arms of
`scripts/lm-weight-edit/holdout-plan.json`. Commit `85fd374` fixed that plan and the criteria
before the read. The three rows found on dev after the fact got their first untouched test here.

Table 4. Counts per arm on the held-out set. The SmolLM2 fine-tune keeps more clean cases than the
control and changes the fewest words of clean running text. The other SmolLM2 arms change more
words than that fine-tune does.

HOLDOUT_A

Table 5. The criteria on the held-out set, against the control. Every SmolLM2 arm built from the
fine-tune meets the clean rule, the fine-tune included. Not one distilgpt2 arm meets it.

HOLDOUT_B

Table 6. Paired counts on the held-out set. Against the SmolLM2 fine-tune, a lower weight or a
lower coefficient repairs more GitHub misspellings and changes more clean sentences.

HOLDOUT_C

Five readings of these tables:

- Clean words: `s-lora` keeps 952 of 972 clean cases and 427 of 429 clean symbols, against 945
  and 421 for the control. `s-wise-0.9` keeps 948 and 427. So interpolation is not needed for the
  clean rule on this set, and a = 0.9 does not add clean words.
- Clean categories: against the control, `s-lora` keeps 5 fewer common words (295 against 300) on
  the held-out set, as on dev. It keeps 7 more names and terms (67 against 60), 2 more rare words
  and 3 more two-word cases. So the held-out count rises through other categories, and the loss
  of common words stays.
- Clean running text: the control changes 332 of 26,060 words, `s-lora` 116, `s-wise-0.9` 140 and
  `s-lora-weight-0.5` 182. Against `s-lora`, `s-wise-0.9` leaves 2 more sentences unchanged and
  changes 22 more (p = 0.00004).
- GitHub misspellings: `s-lora` repairs 1,247 of 1,500, below the control's 1,274 (p = 0.036).
  `s-wise-0.9` repairs 1,265, `s-wise-0.7-common` 1,282 and `s-lora-weight-0.5` 1,310. On the
  1,000 `github_real_word` cases the order reverses: 379 for `s-lora`, 398, 340 and 250.
  On the 721 Mitton pairs the SmolLM2 arms from the fine-tune get 354 to 359, against 368 for the
  control, and none differs from the control at p under 0.05.
- distilgpt2: `d-lora` keeps 935 clean cases and `d-wise-0.9` keeps 939, both below the control's
  945. `d-lora-weight-0.5` keeps 947 clean cases and 418 clean symbols, below the control's 421.

## Limits of this measurement

- One SmolLM2 fine-tune exists. The seed spread of the clean count is known for distilgpt2 only:
  945 and 950 on dev.
- Three arms exceed the 0.05-nat limit of the PyTorch against `lm_score` check on their largest
  gap: `s-wise-0.5` (0.051), `s-wise-0.8` (0.072) and `d2-wise-0.5` (0.081). Their tokens match on
  all 2,000 lists, and their mean gaps are 0.004 to 0.008 nats. The check was left unchanged.
- The stopping cases chose each coefficient, and each fine-tune read the stopping lists for its
  checkpoint. So a count on the stopping cases is optimistic.
- The rows "found on dev after the fact" were picked by reading dev. Only their held-out numbers
  are free of that pick.
- The held-out plan does not hold a = 0.9 at the setting of `s-lora`. `s-wise-0.9` differs from
  `s-lora` in its weights and in one margin (1 against 2), so its 20 extra changed sentences
  cannot be assigned to the weights alone.
- The held-out clean rule compares counts of a few cases. `s-lora` turns 9 clean cases wrong and
  16 right against the control (p = 0.23).
- The fine-tune's own held-out candidate is its Q4_K_M file at another setting. This report used
  Q3_K_M files, so its `s-lora` row is not that candidate.
- The phone time and memory of an interpolated file were not measured. The file has the size and
  the architecture of the fine-tune.

## Full dev tables of the three fine-tunes

Each block gives four things per coefficient: the selection on the stopping cases, dev per group
and per generated category, the paired clean and published counts, and the two controls. The
"half-gain interval" is the 95 percent bootstrap interval of dev right at a, less the mean of
a = 0 and a = 1. It resamples the 6,225 groups of one context and one intended text.

INTERP
"""

TEXT = TEXT.replace("HOLDOUT_A", holdout_table("A")).replace("HOLDOUT_B", holdout_table("B")).replace("HOLDOUT_C", holdout_table("C"))
TEXT = TEXT.replace("INTERP", INTERP.strip() + "\n")
if "—" in TEXT:
    raise SystemExit("the document holds an em-dash")
(ROOT / "docs" / "lm-weight-edit-interpolation-results.md").write_text(TEXT, encoding="utf-8", newline="\n")
print(len(TEXT.splitlines()), "lines")

# Measurement of Apple's stock iOS keyboard on the typing test cases

## Summary

This folder types a sample of the test cases on Apple's own keyboard in the iOS Simulator.
The scores are the reference line for the other engines. The control run shows that the key
taps arrive: 259 of 259 control cases held exactly the typed characters.

1. Read the scores in `scripts/typing-evaluation/results/apple-stock-keyboard/TASK.HALF.summary.json`.
2. Read the checks of each run in `TASK.HALF.checks.json` in the same folder.
3. Run the measurement again with a push to the branch `eval/apple-stock-keyboard`, or start
   the workflow `.github/workflows/eval-apple-stock-keyboard.yml` by hand.

The measurement does not say how a real iPhone with a person's learned words would score.

## Setup of the simulator and the keyboards

Table 1. The setup of the measurement.

| Item | Value |
| --- | --- |
| Runner | GitHub runner `xcode-27`, macOS 27.0.1, Xcode 27.1 |
| Simulator | iPhone 17, iOS 27.2 (build 24B8117), portrait |
| English keyboard | The keyboard of a new simulator, US English, with every setting at its default |
| Pinyin keyboard | Simplified Chinese Pinyin with the QWERTY layout as the only keyboard, with every setting at its default |
| Text view | A `UITextView` with every text input trait at its default |
| Key taps | One synthesized touch for each key, on the center of the key, held for 0.06 seconds |
| Key interval | 0.33 seconds between two touch-downs, about 36 words a minute |
| End of a case | English: one space tap. Pinyin: space taps while the keyboard still holds marked text |
| Sample seed | 20261109 |

The keyboard changes its corrections with the key interval. A trial on 75 English cases gave
equal outputs at 0.25 and 0.33 seconds, and 15 other outputs at 0.50 seconds.

## Sample of the dev half and the test half

`sample_cases.py` sorts the cases by id and draws with a fixed seed. Each half gets the same
sample size.

Table 2. The sample of each half.

| Task | Stratum | Share drawn | Sample of each half |
| --- | --- | --- | --- |
| English | Category | 0.2 | 60 cases of each category with 300 cases, 15 of the 73 `clean_names_and_terms` cases, 1,035 cases |
| Pinyin | Length bin of the base clause | 0.12 | 90 base clauses (18, 36 and 36 in the three length bins) with all their slip cases, 694 dev cases and 692 test cases |

A Pinyin base clause is a clean case with the slip cases that name it in `twin`. The sample
keeps every case of a drawn base clause, so `accuracy_when_twin_right` has its pairs. The Pinyin
dev sample holds 90 clean cases, 517 finger-slip cases and 87 `fuzzy_sound` cases.

Each job types one shard on a new simulator. A Pinyin sample has 8 shards, and one simulator
types each base clause one time. The English dev sample went in 2 shards and the English test
sample in 4 shards.

## Checks of the key taps

Table 3. The checks of the measurement on the dev half.

| Check | Result |
| --- | --- |
| Control run: English cases typed with every correction off whose text view holds exactly the typed characters | 259 of 259 |
| English cases whose text once held the typed letters of the first token | 1,035 of 1,035 |
| Pinyin cases whose marked text held every typed letter before the space | 694 of 694 |
| Cases typed in a second pass after an error | 0 |
| Median time between two key arrivals | 336 ms English, 334 ms Pinyin |
| Cases with a key gap above 495 ms | 52 of 1,035 English, 116 of 694 Pinyin |

The control run typed the first of 4 shards of the English dev sample. The host app turned
autocorrection, spell checking, capitalization, inline prediction and smart punctuation off.

A busy simulator delays some taps. The share of right cases is the same with and without the
cases that have a key gap above 495 ms: 71.0 and 71.1 percent for English, 33.0 and 32.5
percent for Pinyin.

On the test half, the marked text held every typed letter in 690 of 692 Pinyin cases. In the
other 2 cases a delayed tap became a long press and typed a letter with a tone mark. The
scorer counts both cases as wrong.

## Scores on the dev half

Table 4. The scores of the stock keyboard on the dev sample, as right cases of all cases.

| Task | Group | Right | Accuracy |
| --- | --- | --- | --- |
| English | `clean` | 183 of 195 | 0.938 |
| English | `letter_slips` | 318 of 420 | 0.757 |
| English | `space_slips` | 173 of 300 | 0.577 |
| Pinyin | `clean` | 68 of 90 | 0.756 |
| Pinyin | `finger_slips` | 161 of 517 | 0.311 |
| Pinyin | `finger_slips` when the clean twin is right | 161 of 389 | 0.414 |
| Pinyin | `fuzzy_sound` | 0 of 87 | 0.000 |

The stock keyboard repairs about three of four English letter slips and about one of three
Pinyin finger slips. The summary files hold each category and the test half.

## Spell checker of macOS as a second engine

The workflow also asks `NSSpellChecker` on the Mac runner for its correction of each typed
token of all 5,173 English cases of each half. The tool gets a string and never a touch
position. The engine name `apple-nsspellchecker` gives the checker the context, and
`apple-nsspellchecker-word-alone` gives it the token alone. On the dev half
`apple-nsspellchecker` scores 0.967 on `clean`, 0.775 on `letter_slips` and 0.125 on
`space_slips`. The summaries are in `scripts/typing-evaluation/results/apple-nsspellchecker*/`.

## Limits of the measurement

- The keyboard runs in the iOS Simulator, on the language data inside the simulator runtime.
  A real iPhone can hold newer or larger language data.
- Each tap lands on the center of its key. A real finger lands off center, and the keyboard
  uses the touch position.
- Each simulator is new and does not hold learned words. The keyboard can still learn inside
  one job, which types 86 to 518 cases in a row.
- The scores come from a sample. A share from 90 cases has a 95 percent interval of about 9
  points each way, and a share from 420 cases about 4 points.
- The setting for fuzzy Pinyin stays at its default, so `fuzzy_sound` measures the default keyboard.
- The English keyboard is US English, and it changes British spellings such as `authorisation`.

## Files of the adapter and the runs behind the results

| File | Content |
| --- | --- |
| `HostApp/` | The app with one text view. It shows the text and the time of each change in a status label |
| `UITests/` | The UI test that taps the keys and reads the status label |
| `simulator.sh` | Creates a new simulator and sets its keyboard |
| `sample_cases.py` | Draws the sample and its shards |
| `collect_outputs.py` | Merges the shards into outputs and checks |
| `score_outputs.sh` | Runs `score.py` for each engine name and half |
| `NSSpellCheckerTool/` | The command-line tool for the spell checker of macOS |

The results come from two workflow runs. Run 42771475264 typed the control shard, the English
dev sample, the Pinyin dev shards 0 and 2 to 7 and the Pinyin test shard 0. Run 42792045806
typed the Pinyin dev shard 1 and the other test shards, and ran the spell checker.

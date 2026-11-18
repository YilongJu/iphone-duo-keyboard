# Changelog

This file lists what changed in each TestFlight build, the newest build first. Each entry names
the build number, the commit, and the upload time in UTC. An entry says what a person notices
on the phone first, and then what changed behind it.

## Build 65

Commit `25eb14b`, uploaded 2026-11-18 08:41 UTC.

**What you notice**

- The predicted words of the strip come in a new order. The order mixes two values of each
  word: the language model's value at a share of 0.7, and the typing engine's value at a share
  of 0.3. Build 64 used the model's value alone.
- A predicted word takes the capitals that you typed. After "I use py" the strip shows
  "python". Build 64 showed "Python", because the model picked the form. A word of the work
  area keeps its preferred capitals, as "PyTorch".

**Behind it**

- The benchmark of the predicted words chose these two settings
  ([prediction-strip-benchmark-results.md](prediction-strip-benchmark-results.md)). The numbers
  below are saved key presses with 4 to 7 shown words, the counts of the open phone, on the dev
  halves of the benchmark.

  | Word order | Saved key presses |
  | --- | --- |
  | Engine alone (build 62) | 47.4% |
  | Model alone, model's form (builds 63 and 64) | 54.2% |
  | Model and engine mixed, typed capitals (build 65) | 56.7% |

  The more of the engine's value the mix holds, up to the share 0.3, the more key presses the
  strip saves. The benchmark's exact choice gives 57.0% on the dev halves and on the test
  halves. Build 65 is 0.25 points below it, because two details of the choice need changes of
  the engine.
- The benchmark's scripts and result files are in `scripts/prediction-strip/benchmark/`.

## Build 64

Commit `aa19e0e`, uploaded 2026-11-18 07:57 UTC.

**What you notice**

- The Chinese candidates and the proofreader's fix of a sentence show in the place of the
  prediction strip, between Select All and Cut. Before, they covered the whole top row.
- Select All, Cut, Copy and Paste stay in view and react while the candidates show.
- A finger on a predicted word, an emoji or a candidate starts the ripple of a key press at the
  finger's place.

**Behind it**

- The keyboard's process has one language model for all its view controllers. On 2026-11-17
  iOS stopped the keyboard at its memory limit of about 177 MB. The likely cause is one model
  per view controller, and no measurement has confirmed it.
- The report of "duo:lm" has a new line "memory now". The line gives the footprint, the count
  of loaded models and the count of keyboards alive in the process.

## Build 63

Commit `3e72dea`, uploaded 2026-11-18 07:24 UTC.

**What you notice**

- The language model orders the predicted words of the strip. After each space the strip
  shows the engine's order for a moment, and then the model's order takes its place.
- The first word of a field keeps the engine's order.
- On an iPad, Select All starts at the left edge of the keyboard.

**Behind it**

- The keyboard asks the model once per word for the log probability of every token. The new
  file `Shared/word-table-smollm2.bin` maps each word form to its first token.
- A unit test loads the real model in the simulator and orders words with it.

## Build 62

Commit `a8907a2`, uploaded 2026-11-18 05:25 UTC.

**What you notice**

- The top row has a prediction strip between Select All and Cut. The strip shows the emoji of
  the word before the cursor, and then up to 20 predicted words from the typing engine.
- A tap on a predicted word puts the word in place of the typed letters and adds a space. One
  delete brings the typed letters back. Taps chain from one predicted word to the next.
- The Home key and the End key left the top row. Cut, Copy and Paste are small keys at the
  right.

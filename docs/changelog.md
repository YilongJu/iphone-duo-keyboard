# Changelog

This file lists what changed in each TestFlight build, the newest build first. Each entry names
the build number, the commit, and the upload time in UTC. An entry says what a person notices
on the phone first, and then what changed behind it.

## Build 68

Commit `5031aad`, uploaded 2026-11-18 17:25 UTC.

**What you notice**

- The open phone's layout has the return key in the lower right corner, with the width of two
  letter keys. The return key shows the field's action, such as send or search.
- A newline key has the return key's former place, at the right end of the row of "a" to "l"
  and of the fourth row of the symbol layers. The newline key always types a line break and
  never does the field's action.
- Select All of the open phone is twice as wide. The typing speed beside it has the width of
  Cut, so the number sits close to Select All.
- The closed phone's layout is unchanged.

**Behind it**

- In a field without an action, the newline key types "\n". In a field with an action, the key
  types the Unicode character LINE SEPARATOR (U+2028), because such a field reads "\n" as the
  request for its action.
- No test on the phone has shown yet how each app shows and sends the line separator.
- With Pinyin letters waiting, the newline key puts the letters in the text and adds no line
  break, as the return key does.
- The layout check has a new rule: every layer of the wide layout has exactly one newline key.

## Build 67

Commit `ade3caa`, uploaded 2026-11-18 09:57 UTC.

**What you notice**

- The open phone's layout has no arrow keys. A held space bar still moves the cursor left and
  right. No key moves the cursor up or down.
- Comma, period and slash of the letters are as wide as a letter key. The shift key at the
  right is wider.
- The space bar of the bottom row is longer: 7.2 key units in place of 6.5 in the letters, and
  8.3 in place of 7.6 in the symbol layers.
- The lower right corner is empty, with room for two keys of the width of a letter key. A touch
  there does nothing.
- In the symbol layers, the forward delete key is twice as wide.
- The typing speed is steadier. A tap on a predicted word after a pause no longer shows a
  number that is too high, and a delete of older text no longer holds the number at 0.

**Behind it**

- The typing speed counts one change per action: the characters that went in less those that
  came out. A tapped word counts with all its characters. The proofreader's fix counts only
  with the characters that it adds.
- A delete takes the latest counted characters out of the count. A delete of text from before
  the last 10 seconds changes nothing.
- The first action of a run of typing starts the clock and counts no character.
- Pinyin letters keep a run going, although they wait outside the text.
- The lines of a test's report, as after "duo:lm", do not count.
- The closed phone's layout is unchanged. It never had arrow keys.

## Build 66

Commit `6ec01c3`, uploaded 2026-11-18 09:29 UTC.

**What you notice**

- Select All is a small key with an icon: three lines of text in a dashed frame. The key has
  the width of Cut, Copy and Paste.
- The room that became free shows your typing speed: a number with "WPM" below it. After a few
  seconds of typing at 5 characters per second, the number is 60.
- The number counts what goes into the text. A tapped predicted word counts with all its
  characters, a delete takes one character out, and pasted text does not count.
- The number stays while you pause. A dash shows before the first number.

**Behind it**

- One word is 5 characters. The speed covers the last 10 seconds of a run of typing, and a
  pause of more than 3 seconds ends a run. A run gives a number once it is 2 seconds long.
- The image model gpt-image made four candidates for the icon. `scripts/select-all-icon` holds
  the prompts, the chosen candidate and a sheet of all four.
- A touch on the typing speed presses no key, so a finger that misses Select All does not
  select all the text.
- Chinese text gives a low number, because the speed counts characters.

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

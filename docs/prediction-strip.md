# Prediction strip

The prediction strip is the part of the top row of keys between Select All and Cut. It shows
the emoji of the word before the cursor, and then the predicted words. A predicted word is a
word that starts with the letters the person is typing, or a word that often follows the word
before the cursor. A tap on a predicted word types the word and a space.

## The top row

The top row holds Select All, the prediction strip and the small keys Cut, Copy and Paste, in
all three layers. `Shared/keyboard-layout.json` names the strip's place as the key
`predictionStrip`.

| Layout | Select All | Cut, Copy, Paste, each | Prediction strip |
| --- | --- | --- | --- |
| Compact, 10 key units | 1.75 | 0.75 | 6 |
| Wide, 13.5 key units | 2.3 | one third of 2.3 | 8.9 |
| Split, 19.5 key units | 2.3 | one third of 2.3 | 14.9 |

One key unit is the width of one letter key. In the split layout the strip crosses the empty
middle, so the top row has no empty middle of its own.

The row has no Home key and no End key. The wide and split layouts move the cursor with their
arrow keys, and a held space bar moves the cursor in every layout.

## What the strip shows

```mermaid
flowchart TD
    A[Text before the cursor changes] --> B{English mode, a field with autocorrection,<br>no selection}
    B -- no --> C[Empty strip]
    B -- yes --> D[Emoji of the word before the cursor,<br>from the emoji table]
    D --> E{Text right before the cursor}
    E -- typed letters --> G[Engine finds the words that start<br>with the typed letters]
    E -- a word and one space --> I[Engine finds the words<br>after that word]
    E -- other text --> F[Strip shows the emoji only]
    G --> H[Strip shows the emoji,<br>then up to 20 predicted words]
    I --> H
```

- **Emoji.** The emoji of the English word before the cursor take the first places.
  [emoji-suggestions.md](emoji-suggestions.md) describes the table and the tap on an emoji.
- **Typed letters.** The typed letters are the ASCII letters and apostrophes right before the
  cursor (`KeyboardTextLogic.typedLetters`). They start the text, or they follow a space, a
  line break or an opening bracket or quote.
- **A word and one space.** Right after a word and one space, no letter is typed, and the strip
  shows the words that the engine expects after that word.
- **Other text.** The strip shows no predicted words in these cases
  (`KeyboardTextLogic.predictionContext`):
  - No word comes before the cursor: the start of the text, a mark, two spaces or a line break.
  - A letter, a digit or an apostrophe follows the cursor, so the cursor sits inside a word.
  - The letters hold a capital after the first letter and are not all capitals, as "iPh".
  - Another character comes right before the letters, as in "@to" and "2to".
- **Predicted words.** The typing engine gives the words of the lexicon and of the work area
  that start with the typed letters and are longer than them (`duo_predict_english` in
  `Engine/duo_engine.c`). Without a typed letter the engine gives the most probable words after
  the word before. The most probable word comes first. The engine reads the probability of a word after the word before
  it from its word and word-pair statistics, as for a correction. The strip holds up to 20
  words, and a slide to the left shows the words past its right edge.
- **Capitals.** A predicted word takes the capitals of the typed letters: "To" gives
  "Tomorrow", and "TO" gives "TOMORROW". The word "i" and its contractions always get their
  capital. A word of the work area gets its form by the rule of the preferred capitals, as
  "PyTorch" for "Py" ([domain-pack-design.md](domain-pack-design.md)).
- **Other rows.** The Chinese candidates and the proofreader's fix lie over the top row while
  they show, so they cover the strip.

## Order of the predicted words

The strip has two orders for its words. The engine's order needs no model. The model's order
takes its place as soon as the language model has read the text before the word.

```mermaid
flowchart TD
    A[Text before the word changes] --> B[Strip shows the engine's order at once]
    A --> C{Model loaded, and a text with one space at its end}
    C -- no --> D[Engine's order stays]
    C -- yes --> E[Model reads the text once: one number per token]
    E --> F[Engine values each word: number of its first token plus word share]
    F --> G[Strip shows the model's order]
    G --> H[Each typed letter filters the words, with the same numbers]
```

| Order | Value of a word | Where the code is |
| --- | --- | --- |
| Engine's order | The engine's log probability of the word after the word before. | `duo_predict_english` |
| Model's order | The model's log probability of the first token of the word's form, plus the log of the word share. | `duo_predict_english_with_model` |

- **Numbers of the model.** The model gives the log probability of every token right after the
  text (`duo_lm_scorer_next`). The model reads once per word. `scripts/prediction-strip/check_scorer_next.py`
  shows that the phone's scorer gives the numbers of the Linux scorer.
- **Word table.** `Shared/word-table-smollm2.bin` holds the first token and the word share of
  each form of each word. The word share is the word's probability over the summed probability
  of the forms with the same first token. `scripts/typing-engine/build_word_table.py` builds
  the file from the lexicon, the work area and the model's tokenizer.
- **Forms.** A word has up to three forms: lower case, first letter capital, and the preferred
  capitals of the work area. The model's order writes a word in its form with the highest
  value, as "Python" after "I use". A typed capital allows only forms with a capital.
- **First word of a field.** The model has no text to read there, so the engine's order stays.
- **Settings.** `EngineSpellChecker.PredictionSettings` holds the share of the engine's value
  in the order, and the form rule. The benchmark of
  [prediction-strip-benchmark-design.md](prediction-strip-benchmark-design.md) chooses them.

## A tap on a predicted word

1. The word takes the place of the typed letters, and one space follows the word. A word
   that the strip showed right after a space goes in after that space.
2. One backspace right after the tap brings the text before the tap back, as after a
   correction.
3. No correction reads the word, alone or together with the next word, because the word is
   the person's own choice.
4. The space counts as a typed space. A mark right after the tap takes the place of the
   space, and a second space gives a period.

The space bar never picks a predicted word. The words change with each typed letter, so a
space keeps the typed word and corrects it as before.

## Touches

The strip takes the full cell of its place in the row and the keyboard's edge above it. A
touch in that cell never reaches a key, so a finger that misses a word cannot press Select All
or Cut. A finger that comes down on the strip first types the letter of a finger that still
rests on a key. When that letter changes the words, the lift of the first finger selects
nothing.

## Limits

- The model's order is weak after a very short text. After the one word "Thank" at the start
  of a field, the model's first words are not "you".
- The strip shows the engine's order for a moment after each space, until the model answers.
  No phone run has measured that time yet.
- The strip predicts no first word of a text or of a sentence, because no word comes before
  the cursor there.
- The strip holds only words that start with the typed letters. A typed word with a wrong
  letter gets its correction at the space.
- The strip predicts English words only. Chinese mode keeps its own candidate row.

## Checks

| Check | Command or place |
| --- | --- |
| Layout rules, with the rule for the strip | `python scripts/keyboard-preview/check_layout.py` |
| Predicted words of the engine on the PC | `duo_cli predict` (`Engine/duo_cli.c`) |
| Model's order of the engine against a second computation | `scripts/typing-engine-check/check_model_order.py` |
| Word table against the lexicon and the model | `python3 scripts/typing-engine/build_word_table.py --check` |
| Unit tests | `Tests/PredictionStripTests.swift`, `Tests/ModelPredictedWordsTests.swift`, `Tests/TopRowEmojiTests.swift`, `Tests/TypingEngineTests.swift` |

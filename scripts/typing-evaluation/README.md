# Typing-error evaluation for the English and Pinyin keyboards

## Summary

This folder scores how well a typing engine repairs slips and how often it leaves correct
input alone. Every engine, ours and each open-source one, reads the same test cases.

1. Build the cases: `uv run --with wordfreq python scripts/typing-evaluation/build_english_cases.py`,
   `uv run --with pypinyin --with opencc-python-reimplemented python scripts/typing-evaluation/build_pinyin_cases.py`
   and `uv run --with wordfreq python scripts/typing-evaluation/build_external_english_cases.py`.
2. Run an engine on the dev half and write one output per case.
3. Score the outputs: `python scripts/typing-evaluation/score.py --task english --engine NAME --cases ... --predictions ...`.
4. Tune only on the dev half. Read the test half once, for the final table.

The generated cases do not say how often each slip happens in real typing. Two things anchor
them: cases from published misspelling lists, which our generator did not make, and a
measurement of Apple's stock keyboard on the same cases, which is still open.

## Tasks

Table 1. The English task, in the eight rows that define a machine learning task.

| Row | English autocorrection |
| --- | --- |
| Input | Two strings: `context`, the 0 to 11 lower-case words before the typed text, and `typed`, 2 to 23 characters from the set a to z, apostrophe and space. |
| Model | A typing engine that maps the two strings to one string. Our engine has 21 hand-set costs and does not train. Each open-source engine runs with its stock data. |
| Output | One string: the text the engine leaves in the field after the person presses space. |
| Target | `intended`, the lower-case text the person meant, 1 or 2 words. The slip generator made `typed` from `intended`, so the target is exact by construction. For the published misspelling lists, the list gives the target. |
| Training signal | None. An engine's free settings are chosen on the dev half by the share of letter-slip and space-slip cases repaired, with the share of clean cases kept at 99 percent or more. |
| Negatives | The clean cases: `typed` equals `intended`, so any change is an error. 973 clean cases stand beside 3,600 slip cases in each half. |
| Split | The Tatoeba sentence. A sentence with an even id feeds the dev half and one with an odd id the test half. Rare words and names are split by list position, and misspelling-list words by a hash of the word. |
| Eval | Exact match between output and target, ignoring letter case, as a share of cases. Reported per category, then pooled over three groups: clean, letter slips and space slips. Each generated category has 300 cases, except 73 for names and terms. |

Table 2. The Pinyin task.

| Row | Pinyin conversion |
| --- | --- |
| Input | One string: `typed`, 2 to 65 letters a to z with no spaces, the toneless Pinyin of a clause with or without a slip. |
| Model | A Pinyin engine that maps the letters to Chinese text. Our engine has 12 hand-set costs and does not train. Each open-source engine runs with its stock data. |
| Output | One string: the engine's first candidate for all the letters. When the first candidate covers only some letters, the harness takes first candidates until every letter is used. |
| Target | `intended`, a clause of 2 to 20 Simplified Chinese characters from Tatoeba. Its Pinyin comes from pypinyin, which reads about 86 percent of multi-reading characters right on a published test, so a small share of targets has a wrong Pinyin input. |
| Training signal | None. Settings are chosen on the dev half by the share of finger-slip cases repaired, with clean accuracy at most 1 point under the engine's clean accuracy with slip handling off. |
| Negatives | The clean cases: correct Pinyin, where slip handling must not lower accuracy. 750 clean cases stand beside about 4,300 finger-slip cases in each half. |
| Split | The Tatoeba sentence, by id parity. No language-model data comes from Tatoeba. |
| Eval | Exact match between output and target as a share of cases, and character accuracy (1 minus edit distance over target length, floored at 0, averaged over cases). Reported per category, pooled over clean and over finger slips, and for slip cases also among the cases whose clean twin the engine converts right. Several Chinese texts share one Pinyin, so exact match stays under 100 percent for every engine. |

## Case categories

Table 3. The categories. A name that starts with `clean` holds input without a slip.

| Category | Task | Group | Slip | Example, typed to intended |
| --- | --- | --- | --- | --- |
| `clean_common` | English | clean | None, a common word | this to this |
| `clean_rare` | English | clean | None, a rare real word | woolly to woolly |
| `clean_names_and_terms` | English | clean | None, a name, product, technical term or chat word | okonkwo to okonkwo |
| `clean_two_words` | English | clean | None, two words with their space | tell tom to tell tom |
| `substitution_adjacent` | Both | letter or finger slips | A neighbor key in place of a letter | wrofe to wrote |
| `deletion` | Both | letter or finger slips | A letter left out | accpt to accept |
| `double_letter` | Both | letter or finger slips | A letter typed twice | allone to alone |
| `extra_adjacent` | Both | letter or finger slips | An extra neighbor key | injto to into |
| `transposition` | Both | letter or finger slips | Two letters swapped | sepaks to speaks |
| `two_errors` | Both | letter or finger slips | Two letter slips in one word or clause | disqppoibtment to disappointment |
| `short_word_slip` | English | letter slips | One letter slip in a word of 2 or 3 letters | syhe to she |
| `space_missing` | English | space slips | Two words joined | wantedto to wanted to |
| `space_to_letter` | English | space slips | c, v, b, n or m in place of the space | asmyou to as you |
| `space_transposed` | English | space slips | The space one key early or late | tob e to to be |
| `space_extra` | English | space slips | A space inside a word | l aptop to laptop |
| `letter_to_space` | English | space slips | A space in place of c, v, b, n or m | conte t to content |
| `apostrophe_missing` | English | alone | A contraction without its apostrophe | youd to you'd |
| `real_word_slip` | English | alone | A letter slip that gives a common real word | ad to and |
| `real_misspelling_birkbeck`, `_holbrook`, `_aspell` | English | alone | A spelling mistake from a published list | divison to division |
| `clean` | Pinyin | clean | None, clauses of 2 to 20 characters | taduinide to 它对你的 |
| `fuzzy_sound` | Pinyin | alone | One sound swapped for its dialect twin, such as n and l | lixihuan to 你喜欢 |

The more a slip changes the letters, the fewer engines repair it. Three notes on reading the
categories:

- An engine that corrects one word at a time cannot repair a space slip. The space slips form
  their own group so that such an engine is compared on the letter slips alone.
- `real_word_slip` needs the sentence around the word, and a keyboard that sees one word back
  repairs few of them.
- `apostrophe_missing` holds the contractions that are at least ten times as frequent as their
  form without the apostrophe. Our word list uses the same rule, so our engine's score in this
  category is high by construction.

## Paired Pinyin cases

Each Pinyin base clause gives one clean case and one case per slip type, and a slip case names
its clean case in `twin`. The scorer reports the repair rate over all slip cases and over the
slip cases whose clean twin the engine converts right. The second number isolates slip repair
from the engine's vocabulary and word choice.

## Limits of the generated cases

- The case generator and our engine's word list both read word frequencies from wordfreq. A
  high score on generated cases can partly reflect that shared source. The published
  misspelling lists and the Apple measurement do not share it.
- The generated letter slips use neighbor keys only, and they leave out a slip that produces a
  common real word (those sit in `real_word_slip`).
- The Pinyin targets come from pypinyin readings, and a wrong reading gives an unreachable target.

## Engine outputs

An engine adapter lives in `engines/NAME/`. It writes
`build/typing-evaluation/NAME/TASK.HALF.jsonl` with one JSON object per line: the case `id` and
the engine's `output`. A case without an output counts as wrong.

- English: the adapter gets `context` and `typed`. An engine that corrects one word at a time
  corrects each space-separated token of `typed` in order and joins the results with spaces.
- Pinyin: the adapter gets `typed` and returns the first candidate for all the letters.
- An engine with several modes gets one name per mode, such as `symspell-lookup` and
  `symspell-compound`.

## Files

| File | Content |
| --- | --- |
| `keyboard_noise.py` | The slip operators and the key geometry |
| `build_english_cases.py`, `build_pinyin_cases.py` | The case generators |
| `build_external_english_cases.py` | Cases from published misspelling lists, written to `build/` and kept out of git |
| `inputs/names_and_terms.txt` | The hand-written list behind `clean_names_and_terms` |
| `cases/` | The generated cases: 5,173 English per half, 5,754 Pinyin in the dev half and 5,777 in the test half |
| `score.py` | The scorer |
| `run_duo_engine.py` | Runs our engine (`Engine/duo_engine.c`) and scores it |
| `Tests/TypingEvaluationTests.swift` | Runs the shipping Swift keyboard code over the cases in the iOS Simulator |

## Data sources

- Sentences: Tatoeba exports, CC BY 2.0 FR, https://tatoeba.org.
- English word frequencies for the generator: the wordfreq package.
- Pinyin readings and the standard syllable set: the pypinyin package.
- Simplified Chinese filter: OpenCC.
- Published misspellings: Roger Mitton's files (Birkbeck, Holbrook, Aspell), fetched at run
  time because the page does not state a license.

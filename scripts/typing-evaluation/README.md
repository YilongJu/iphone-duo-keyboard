# Typing-error evaluation for the English and Pinyin keyboards

## Summary

This folder scores how well a typing engine repairs slips and how often it leaves correct
input alone. Every engine, ours and each open-source one, reads the same test cases.

1. Build the cases: `uv run --with wordfreq python scripts/typing-evaluation/build_english_cases.py`
   and `uv run --with pypinyin python scripts/typing-evaluation/build_pinyin_cases.py`.
2. Run an engine on the dev half and write one output per case.
3. Score the outputs: `python scripts/typing-evaluation/score.py --task english --engine NAME --cases ... --predictions ...`.
4. Tune only on the dev half. Read the test half once, for the final table.

The cases come from a slip generator, so the scores do not say how often each slip happens in
real typing. A measurement of Apple's stock keyboard on the same cases is the reference line,
and that measurement is still open.

## Tasks

Table 1. The English task, in the eight rows that define a machine learning task.

| Row | English autocorrection |
| --- | --- |
| Input | Two strings: `context`, the 0 to 11 lower-case words before the typed text, and `typed`, 1 to 30 characters from the set a to z, apostrophe and space. |
| Model | A typing engine that maps the two strings to one string. Our engine has 21 hand-set costs and does not train. Each open-source engine runs with its stock data. |
| Output | One string: the text the engine leaves in the field after the person presses space. |
| Target | `intended`, the lower-case text the person meant, 1 or 2 words. The slip generator made `typed` from `intended`, so the target is exact by construction. |
| Training signal | None. An engine's free settings are chosen on the dev half by the share of slip cases repaired, with the share of clean cases kept at 98 percent or more. |
| Negatives | The clean cases: `typed` equals `intended`, so any change is an error. 673 clean cases stand beside 3,600 slip cases in each half. |
| Split | The Tatoeba sentence. A sentence with an even id feeds the dev half and one with an odd id the test half. Rare words and names are split by list position. |
| Eval | Exact match between output and target, ignoring letter case, as a share of cases. Reported per category, then pooled over the clean categories and over the slip categories. Each category has 300 cases, except 73 for names and terms. |

Table 2. The Pinyin task.

| Row | Pinyin conversion |
| --- | --- |
| Input | One string: `typed`, 4 to 80 letters a to z with no spaces, the toneless Pinyin of a clause with or without a slip. |
| Model | A Pinyin engine that maps the letters to Chinese text. Our engine has 12 hand-set costs and does not train. Each open-source engine runs with its stock data. |
| Output | One string: the engine's first candidate for all the letters. When the first candidate covers only some letters, the harness takes first candidates until every letter is used. |
| Target | `intended`, a clause of 2 to 20 Simplified Chinese characters from Tatoeba. Its Pinyin comes from pypinyin, which reads about 86 percent of multi-reading characters right on a published test, so a small share of targets has a wrong Pinyin input. |
| Training signal | None. Settings are chosen on the dev half by the share of slip cases repaired, with clean accuracy within 1 point of the engine's accuracy with slip handling off. |
| Negatives | The clean cases: correct Pinyin, where slip handling must not lower accuracy. 900 clean cases stand beside 2,100 slip cases in each half. |
| Split | The Tatoeba sentence, by id parity. No language-model data comes from Tatoeba. |
| Eval | Exact match between output and target as a share of cases, and character accuracy (1 minus edit distance over target length, floored at 0, averaged over cases). Reported per category, then pooled over clean and over slip categories. Each category has 300 cases. Several Chinese texts share one Pinyin, so exact match stays under 100 percent for every engine. |

## Case categories

Table 3. The categories. A name that starts with `clean` holds input without a slip.

| Category | Task | Slip | Example, typed to intended |
| --- | --- | --- | --- |
| `clean_common` | English | None, a common word | this to this |
| `clean_rare` | English | None, a rare real word | woolly to woolly |
| `clean_names_and_terms` | English | None, a name, product, technical term or chat word | okonkwo to okonkwo |
| `substitution_adjacent` | Both | A neighbor key in place of a letter | wrofe to wrote |
| `deletion` | Both | A letter left out | accpt to accept |
| `double_letter` | Both | A letter typed twice | allone to alone |
| `extra_adjacent` | Both | An extra neighbor key | injto to into |
| `transposition` | Both | Two letters swapped | sepaks to speaks |
| `two_errors` | Both | Two of the five letter slips in one word or clause | oodbyye to goodbye |
| `space_missing` | English | Two words joined | wantedto to wanted to |
| `space_to_letter` | English | c, v, b, n or m in place of the space | asmyou to as you |
| `space_transposed` | English | The space one key early or late | tob e to to be |
| `space_extra` | English | A space inside a word | l aptop to laptop |
| `letter_to_space` | English | A space in place of c, v, b, n or m | conte t to content |
| `apostrophe_missing` | English | A contraction without its apostrophe | youd to you'd |
| `clean_short`, `clean_medium`, `clean_long` | Pinyin | None, clauses of 2 to 3, 4 to 7 and 8 to 20 characters | dadehao to 打得好 |
| `fuzzy_sound` | Pinyin | One sound swapped for its dialect twin, such as n and l | lixihuan to 你喜欢 |

The more a slip changes the letters, the fewer engines repair it. The letter categories leave
out a slip that produces a common real word, because that case needs the whole sentence.

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
| `inputs/names_and_terms.txt` | The hand-written list behind `clean_names_and_terms` |
| `cases/` | The generated cases, 4,273 English and 3,000 Pinyin in each half |
| `score.py` | The scorer |
| `run_duo_engine.py` | Runs our engine (`Engine/duo_engine.c`) and scores it |
| `Tests/TypingEvaluationTests.swift` | Runs the shipping Swift keyboard code over the cases in the iOS Simulator |

## Data sources

- Sentences: Tatoeba exports, CC BY 2.0 FR, https://tatoeba.org.
- English word frequencies for the generator: the wordfreq package.
- Pinyin readings: the pypinyin package.

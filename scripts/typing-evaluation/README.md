# Typing-error evaluation for the English and Pinyin keyboards

## Summary

This folder scores how well a typing engine repairs slips and how often it leaves correct
input alone. Every engine, ours and each open-source one, reads the same test cases.

1. Build the cases: `uv run --with wordfreq python scripts/typing-evaluation/build_english_cases.py`,
   `uv run --with wordfreq python scripts/typing-evaluation/build_english_symbol_cases.py`,
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
| Model | A typing engine that maps the two strings to one string. Our engine has 21 hand-set costs, and 7 more for symbol and digit keys, and does not train. Each open-source engine runs with its stock data. |
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
| `symbol_first_letter` | English symbols | symbol slips | A symbol or digit key in place of the first letter | [lease to please |
| `symbol_inner_letter` | English symbols | symbol slips | A digit or `[` in place of a later letter | wh3n to when |
| `symbol_first_letter_two_words` | English symbols | symbol slips | Two typed words, the slip on the first letter of the second | tell ;ike to tell like |
| `symbol_plus_letter_slip` | English symbols | symbol slips | A symbol or digit key in place of the first letter, and one letter slip after it | 0robabyl to probably |
| `clean_symbol_token` | English symbols | clean symbols | None, a real token with a digit or a symbol | mp3 to mp3 |
| `clean_bracket_or_dot_word` | English symbols | clean symbols | None, a real word right after `[`, `.`, `,`, `;` or `-` | [note to [note |
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

## Cases with a symbol or digit key in place of a letter

A finger that aims at a letter can land on a symbol or digit key beside it. The files
`cases/english-symbols.dev.jsonl` and `cases/english-symbols.test.jsonl` hold those slips. They
stand apart from `english.*.jsonl`, so the scores of every engine on the other files stay as
they are. An engine reads them by the English rules, and `typed` also holds digits and the
characters `[ - ; , .` and, in the clean tokens, other symbols.

Table 4. The symbol and digit keys beside each letter key. `symbol_keys.py` derives the table
from the key positions in `Shared/keyboard-layout.json`, for the wide layout and the compact
layout together.

| Key | Letters beside it | Key | Letters beside it |
| --- | --- | --- | --- |
| `1` | q | `9` | i, o |
| `2` | q, w | `0` | o, p |
| `3` | w, e | `-` | p |
| `4` | e, r | `[` | p |
| `5` | r, t | `;` | l, p |
| `6` | t, y | `,` | k, l, m, and n in the compact layout |
| `7` | y, u | `.` | l, and m in the compact layout |
| `8` | u, i | | |

The more letters a key sits beside, the more words one typed text can stand for: `,ost` can be
lost or most, and only the words around it tell them apart.

- Every symbol key gets the same count of slip cases, 20 per category and half, and 27 for
  `symbol_inner_letter`. One typed text appears at most 3 times in a category.
- A digit or `[` can replace a letter at any place. The keys `-`, `;`, `,` and `.` end a word
  or join two words, so the cases use them only in front of a word.
- `clean_symbol_token` reads `inputs/symbol_tokens.txt`: hand-picked tokens such as 2nd, 7am,
  mp3 and h2o, plus the tokens with one digit that wordfreq lists at Zipf 2.5 or more.
- `clean_bracket_or_dot_word` gives each of the five symbols 60 cases. Half of them hold a word
  that is one key from another real word, such as `[art` beside part.

Text such as `[art` can be part with a slip or art after a bracket, and only word frequency
separates the two readings. A slip case needs the intended word to be at least 1.25 Zipf more
frequent than the word after the symbol: please over lease is 1.49. A clean case needs every
word that a neighbor letter would give to be at most 0.5 Zipf more frequent than the typed
word: part over art is 0.49. The generator leaves out the text between the two limits. A token
with a digit is judged as a whole by the rule for letter slips, because wordfreq lists real
tokens such as 5pm.

Our engine (`Engine/duo_engine.c`) reads a symbol or digit key only as a letter beside it. It
never takes the key for an extra key, and it leaves out the readings that give the text without
the key, so `[please` and `a[pple` stay as typed. Its 7 costs for symbol keys are chosen on the
dev half by the share of symbol slips repaired, with the clean symbol cases kept at 99 percent
or more. Run it with
`python3 scripts/typing-evaluation/run_duo_engine.py --task english-symbols --half dev`.

A comma, a period or a semicolon typed inside or after a word ends that word, and the keyboard
corrects the letters before it at once. The cases do not hold that slip.

## Cases of the vocabulary pack "AI and software"

`build_english_domain_cases.py` writes `cases/english-domain.{dev,test}.jsonl`, 7,137 dev and
7,085 test cases, and `cases/english-domain-stream.{dev,test}.jsonl`. The other case files do
not change. `docs/domain-pack-design.md` describes the pack, the groups and the results.

- The technical sentences come from documents that the pack builder did not read: 10 of 100
  documents of each source feed the dev half and 10 of 100 the test half.
- A case names its `group`, and a case with `scoring` "case" is right only with the intended
  capitals. `rerank.case_is_right` and `rerank.tally_by_group` of `scripts/lm-rerank` score them.
- The stream files hold per half 1,000 technical and 1,000 everyday sentences in lower case, and
  300 technical sentences as their source wrote them.
  Their measure is the count of words that the keyboard changes.
- `scripts/lm-rerank/domain_pack.py` types both files with the pack off and on.

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
- The symbol cases do not say how often a person types a symbol in front of a word on purpose.
  The two frequency limits above set which text counts as a slip, and a different limit would
  move the scores of the symbol groups.
- Our engine refuses a word that holds more than one symbol or digit, fewer than two letters
  beside a symbol or digit, a symbol that is not beside a letter key, or `-`, `;`, `,` or `.`
  after its first place. Such a word stays as typed whatever the costs are. 66 of the 129 dev
  cases of `clean_symbol_token` are of that kind, so the costs decide only the other 63.
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
| `symbol_keys.py` | The symbol and digit keys beside each letter, from the layout file, and the check that the engine and the keyboard hold the same table |
| `build_english_cases.py`, `build_pinyin_cases.py` | The case generators |
| `build_english_symbol_cases.py` | The generator of the cases with a symbol or digit key in place of a letter |
| `build_english_domain_cases.py` | The generator of the cases of the vocabulary pack "AI and software" |
| `build_external_english_cases.py` | Cases from published misspelling lists, written to `build/` and kept out of git |
| `inputs/names_and_terms.txt` | The hand-written list behind `clean_names_and_terms` |
| `inputs/symbol_tokens.txt` | The list behind `clean_symbol_token` |
| `cases/` | The generated cases: 5,173 English per half, 1,626 English symbol cases in the dev half and 1,625 in the test half, 5,754 Pinyin in the dev half and 5,777 in the test half |
| `score.py` | The scorer |
| `run_duo_engine.py` | Runs our engine (`Engine/duo_engine.c`) and scores it |
| `Tests/TypingEvaluationTests.swift` | Runs the shipping Swift keyboard code over the cases in the iOS Simulator |

## Data sources

- Sentences: Tatoeba exports, CC BY 2.0 FR, https://tatoeba.org.
- Technical sentences of the pack's cases: arXiv abstracts, five Stack Exchange sites and the
  documentation of open-source projects. `cases/english-domain-NOTICE.txt` gives the licences.
- English word frequencies for the generator: the wordfreq package.
- Pinyin readings and the standard syllable set: the pypinyin package.
- Simplified Chinese filter: OpenCC.
- Published misspellings: Roger Mitton's files (Birkbeck, Holbrook, Aspell), fetched at run
  time because the page does not state a license.
